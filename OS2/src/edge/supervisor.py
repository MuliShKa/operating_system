"""Start and supervise the OS2 application worker processes."""

import logging
import multiprocessing as mp
import signal
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import isfinite
from multiprocessing.process import BaseProcess
from multiprocessing.synchronize import Event
from time import monotonic

from edge import storage
from edge.api_server import run_api_server
from edge.bounded_queue import BoundedSensorQueue
from edge.config import NodeConfig, load_config
from edge.sensor import run_sensor_generator
from edge.sync_worker import run_sync_worker
from edge.workers import run_controller, run_safety_monitor

POLL_INTERVAL_S = 0.1
SHUTDOWN_TIMEOUT_S = 2.0
FORCED_SHUTDOWN_TIMEOUT_S = 1.0

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WorkerSpec:
    """A named process role and the arguments passed to its worker function."""

    name: str
    target: Callable[..., object]
    args: tuple[object, ...]


class RestartBudget:
    """Limit restarts for one process role within a rolling time window."""

    def __init__(self, limit: int, window_s: float) -> None:
        if limit < 1:
            raise ValueError("restart limit must be positive")
        if not isfinite(window_s) or window_s <= 0:
            raise ValueError("restart window must be finite and positive")
        self.limit = limit
        self.window_s = window_s
        self._restarts: deque[float] = deque()

    def try_restart(self, now: float) -> bool:
        """Record a restart unless the role has exhausted its rolling budget."""
        if not isfinite(now):
            raise ValueError("restart time must be finite")
        while self._restarts and now - self._restarts[0] >= self.window_s:
            self._restarts.popleft()
        if len(self._restarts) >= self.limit:
            return False
        self._restarts.append(now)
        return True


class ProcessSupervisor:
    """Run worker roles continuously and shut them down without leaving children."""

    def __init__(
        self,
        config: NodeConfig,
        *,
        context: mp.context.BaseContext | None = None,
        stop_event: Event | None = None,
        worker_specs: Sequence[WorkerSpec] | None = None,
        poll_interval_s: float = POLL_INTERVAL_S,
        shutdown_timeout_s: float = SHUTDOWN_TIMEOUT_S,
    ) -> None:
        if not isfinite(poll_interval_s) or poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be finite and positive")
        if not isfinite(shutdown_timeout_s) or shutdown_timeout_s <= 0:
            raise ValueError("shutdown_timeout_s must be finite and positive")

        self.config = config
        self.context = context or mp.get_context("spawn")
        self.stop_event = (
            stop_event if stop_event is not None else self.context.Event()
        )
        self.poll_interval_s = poll_interval_s
        self.shutdown_timeout_s = shutdown_timeout_s
        self._sensor_queue: BoundedSensorQueue | None = None
        self._worker_specs = tuple(worker_specs) if worker_specs is not None else None
        self._processes: dict[str, BaseProcess] = {}
        self._restart_budgets: dict[str, RestartBudget] = {}

    def request_shutdown(self) -> None:
        """Ask the supervisor loop and all workers to stop."""
        self.stop_event.set()

    def run(self) -> None:
        """Initialize local storage, launch workers, and supervise until stopped."""
        storage.init_db(self.config.database)
        if self._worker_specs is None:
            self._worker_specs = self._default_worker_specs()
        if not self._worker_specs:
            raise ValueError("at least one worker role is required")
        if len({spec.name for spec in self._worker_specs}) != len(self._worker_specs):
            raise ValueError("worker role names must be unique")

        self._restart_budgets = {
            spec.name: RestartBudget(
                self.config.restart_burst, self.config.restart_window_s
            )
            for spec in self._worker_specs
        }

        try:
            for spec in self._worker_specs:
                self._start_worker(spec, restarted=False)
            self._monitor_workers()
        finally:
            try:
                self._shutdown_workers()
            finally:
                if self._sensor_queue is not None:
                    self._sensor_queue.close()
                    self._sensor_queue.join_thread()

    def _default_worker_specs(self) -> tuple[WorkerSpec, ...]:
        self._sensor_queue = BoundedSensorQueue(
            self.config.queue_size, context=self.context
        )
        return (
            WorkerSpec(
                "safety-monitor",
                run_safety_monitor,
                (self.stop_event, self.config),
            ),
            WorkerSpec(
                "sensor-generator",
                run_sensor_generator,
                (self._sensor_queue, self.stop_event, self.config.period_s),
            ),
            WorkerSpec(
                "controller",
                run_controller,
                (self._sensor_queue, self.stop_event, self.config),
            ),
            WorkerSpec(
                "sync-worker",
                run_sync_worker,
                (self.stop_event, self.config),
            ),
            WorkerSpec(
                "api-server",
                run_api_server,
                (self.stop_event, self.config, self._sensor_queue),
            ),
        )

    def _start_worker(self, spec: WorkerSpec, *, restarted: bool) -> None:
        process = self.context.Process(
            target=spec.target,
            args=spec.args,
            name=f"os2-{spec.name}",
        )
        process.start()
        self._processes[spec.name] = process
        status = "restarted" if restarted else "running"
        storage.record_health(
            self.config.database, spec.name, process.pid, status
        )
        log.info("%s started with pid %s", spec.name, process.pid)

    def _monitor_workers(self) -> None:
        assert self._worker_specs is not None
        specs = {spec.name: spec for spec in self._worker_specs}

        while not self.stop_event.wait(self.poll_interval_s):
            for name, process in tuple(self._processes.items()):
                if process.is_alive():
                    continue
                process.join()
                exitcode = process.exitcode
                storage.record_health(
                    self.config.database,
                    name,
                    process.pid,
                    "exited",
                    f"unexpected worker exit (exit code {exitcode})",
                )
                self._processes.pop(name)
                process.close()
                log.error("%s exited unexpectedly with code %s", name, exitcode)

                if not self._restart_budgets[name].try_restart(monotonic()):
                    storage.record_health(
                        self.config.database,
                        name,
                        None,
                        "failed",
                        "restart limit exceeded within configured window",
                    )
                    raise RuntimeError(
                        f"{name} exceeded its restart limit "
                        f"({self.config.restart_burst} in "
                        f"{self.config.restart_window_s:g}s)"
                    )
                if self.stop_event.is_set():
                    return
                self._start_worker(specs[name], restarted=True)

    def _shutdown_workers(self) -> None:
        """Give workers time to exit, then terminate and reap any stragglers."""
        self.stop_event.set()
        processes = list(self._processes.items())
        deadline = monotonic() + self.shutdown_timeout_s
        for _, process in processes:
            if process.is_alive():
                process.join(timeout=max(0.0, deadline - monotonic()))

        forced: set[str] = set()
        for name, process in processes:
            if process.is_alive():
                forced.add(name)
                process.terminate()
        forced_deadline = monotonic() + FORCED_SHUTDOWN_TIMEOUT_S
        for _, process in processes:
            if process.is_alive():
                process.join(timeout=max(0.0, forced_deadline - monotonic()))
        for name, process in processes:
            if process.is_alive():
                process.kill()
                process.join(timeout=FORCED_SHUTDOWN_TIMEOUT_S)
            if process.is_alive():
                raise RuntimeError(f"could not stop worker process {name}")
            process.join()

            storage.record_health(
                self.config.database,
                name,
                process.pid,
                "stopped",
                "forced termination" if name in forced else None,
            )
            process.close()
            log.info("%s stopped", name)
        self._processes.clear()


def main() -> int:
    """Run the configured OS2 service until SIGINT or SIGTERM."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(processName)s %(levelname)s %(message)s",
    )
    supervisor = ProcessSupervisor(load_config())

    def handle_signal(signum: int, _frame: object) -> None:
        log.info("received signal %s; shutting down", signum)
        supervisor.request_shutdown()

    previous_handlers = {
        signum: signal.signal(signum, handle_signal)
        for signum in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        supervisor.run()
    except RuntimeError as error:
        log.critical("OS2 supervisor stopped: %s", error)
        return 1
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
