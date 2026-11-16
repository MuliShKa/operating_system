"""Start and shut down the connected edge-node demo workers."""

from __future__ import annotations

import json
import multiprocessing
import os
import signal
import time
from collections import deque
from time import monotonic

import psutil

from edge import storage
from edge.SensorGen import run_sensor_gen
from edge.api_server import run_api_server
from edge.health import REQUIRED_WORKERS
from edge.ipc import IpcChannels
from edge.processor import run_processor
from edge.receiver import run_receiver
from edge.sync_worker import run_sync_worker

PROCESS_NAMES = REQUIRED_WORKERS
SHUTDOWN_TIMEOUT_SECONDS = 3.0
MAX_RESTARTS = 3
RESTART_WINDOW_SECONDS = 60.0

_shutdown_requested = False


def _worker_main(process_name, target, args, state) -> None:
    # Demo integration: publish worker lifecycle to the dashboard's shared state.
    state[f"worker_pid:{process_name}"] = os.getpid()
    state[f"worker_status:{process_name}"] = "running"
    try:
        target(*args)
    finally:
        state[f"worker_status:{process_name}"] = "stopped"


def _run_health_monitor(state, stop_event) -> None:
    # Persist a heartbeat for each required process, not just the monitor itself.
    while not stop_event.is_set():
        for process_name in PROCESS_NAMES:
            pid = state.get(f"worker_pid:{process_name}")
            status = state.get(f"worker_status:{process_name}", "starting")
            if status == "running":
                if not isinstance(pid, int):
                    status = "unknown"
                else:
                    try:
                        process = psutil.Process(pid)
                        status = (
                            "running"
                            if process.is_running()
                            and process.status() != psutil.STATUS_ZOMBIE
                            else "stopped"
                        )
                    except psutil.NoSuchProcess:
                        status = "stopped"
                    except psutil.AccessDenied:
                        status = "unknown"

            details = json.dumps({"pid": pid}, separators=(",", ":"))
            storage.save_process_health(process_name, status, details)

        state["last_health_check"] = time.time()
        if stop_event.wait(5):
            break


def _request_shutdown(_signum: int, _frame: object) -> None:
    global _shutdown_requested
    _shutdown_requested = True


def start_processes(context, channels, state, targets=None):
    if targets is None:
        targets = _worker_targets(channels, state)
    return {
        process_name: _start_worker(
            context, state, process_name, target, args
        )
        for process_name, (target, args) in targets.items()
    }


def _worker_targets(channels, state):
    """Return each worker's entry point and the shared IPC objects it uses."""
    return {
        "SensorGen": (run_sensor_gen, (channels,)),
        "Processor": (run_processor, (channels, state)),
        "HealthMon": (_run_health_monitor, (state, channels.stop)),
        "API": (run_api_server, (state, channels.stop, channels)),
        "Receiver": (run_receiver, (channels.stop,)),
        "SyncWorker": (run_sync_worker, (channels, state)),
    }


def _start_worker(context, state, process_name, target, args):
    state[f"worker_status:{process_name}"] = "starting"
    state[f"worker_pid:{process_name}"] = None
    state.setdefault(f"worker_restart_count:{process_name}", 0)
    state.setdefault(f"worker_last_exit_code:{process_name}", None)

    process = context.Process(
        name=process_name,
        target=_worker_main,
        args=(process_name, target, args, state),
    )
    process.start()
    state[f"worker_pid:{process_name}"] = process.pid
    return process


def _allow_restart(restart_times, now):
    while restart_times and now - restart_times[0] >= RESTART_WINDOW_SECONDS:
        restart_times.popleft()
    if len(restart_times) >= MAX_RESTARTS:
        return False
    restart_times.append(now)
    return True


def _monitor_workers(context, state, workers, targets) -> bool:
    restart_times = {name: deque() for name in PROCESS_NAMES}

    while not _shutdown_requested:
        for process_name, process in tuple(workers.items()):
            if _shutdown_requested:
                break
            if process.is_alive():
                continue

            process.join()
            exit_code = process.exitcode
            process.close()
            restart_window = restart_times[process_name]
            if not _allow_restart(restart_window, monotonic()):
                state[f"worker_status:{process_name}"] = "failed"
                state[f"worker_last_exit_code:{process_name}"] = exit_code
                workers.pop(process_name)
                details = json.dumps(
                    {
                        "exit_code": exit_code,
                        "restart_count": state[
                            f"worker_restart_count:{process_name}"
                        ],
                        "reason": "restart limit exceeded",
                    },
                    separators=(",", ":"),
                )
                storage.save_process_health(process_name, "failed", details)
                print(
                    f"{process_name} exceeded the restart limit "
                    f"({MAX_RESTARTS} in {RESTART_WINDOW_SECONDS:g}s).",
                    flush=True,
                )
                return False

            restart_count = state[f"worker_restart_count:{process_name}"] + 1
            state[f"worker_status:{process_name}"] = "restarting"
            state[f"worker_last_exit_code:{process_name}"] = exit_code
            state[f"worker_restart_count:{process_name}"] = restart_count
            storage.save_process_health(
                process_name,
                "restarting",
                json.dumps(
                    {
                        "exit_code": exit_code,
                        "restart_count": restart_count,
                        "window_attempts": len(restart_window),
                    },
                    separators=(",", ":"),
                ),
            )

            target, args = targets[process_name]
            workers[process_name] = _start_worker(
                context, state, process_name, target, args
            )
            print(
                f"Restarted {process_name} after exit code {exit_code} "
                f"(restart {restart_count}).",
                flush=True,
            )

        time.sleep(0.2)

    return True


def stop_processes(workers, channels) -> None:
    channels.stop.set()
    failed_to_stop = []
    for process_name, process in workers.items():
        process.join(SHUTDOWN_TIMEOUT_SECONDS)
        if process.is_alive():
            process.terminate()
            process.join(SHUTDOWN_TIMEOUT_SECONDS)
        if process.is_alive():
            process.kill()
            process.join(SHUTDOWN_TIMEOUT_SECONDS)
        if process.is_alive():
            failed_to_stop.append(process_name)
        else:
            process.close()

    if failed_to_stop:
        raise RuntimeError(
            "could not stop worker processes: " + ", ".join(failed_to_stop)
        )


def main() -> int:
    global _shutdown_requested
    _shutdown_requested = False
    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)

    context = multiprocessing.get_context("spawn")
    manager = context.Manager()
    state = manager.dict()
    channels = IpcChannels(context)
    workers = {}

    try:
        # Demo integration: initialize the database before the Processor starts.
        storage.initialize_database()
        state["pending_events"] = storage.get_pending_event_count()
        targets = _worker_targets(channels, state)
        workers = start_processes(context, channels, state, targets)
        print(
            "Started workers: "
            f"{', '.join(workers)}. Dashboard: http://127.0.0.1:8000",
            flush=True,
        )

        if not _monitor_workers(context, state, workers, targets):
            return 1
    finally:
        try:
            if workers:
                stop_processes(workers, channels)
        finally:
            manager.shutdown()

    print("All workers stopped and reaped.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
