"""Start and shut down the connected edge-node demo workers."""

from __future__ import annotations

import multiprocessing
import os
import signal
import time

from edge import storage
from edge.SensorGen import run_sensor_gen
from edge.api_server import run_api_server
from edge.ipc import IpcChannels
from edge.processor import run_processor
from edge.receiver import run_receiver
from edge.sync_worker import run_sync_worker

PROCESS_NAMES = (
    "SensorGen",
    "Processor",
    "HealthMon",
    "API",
    "Receiver",
    "SyncWorker",
)
SHUTDOWN_TIMEOUT_SECONDS = 3.0

_shutdown_requested = False


def _worker_main(process_name, target, args, state) -> None:
    # Demo integration: publish worker lifecycle to the dashboard's shared state.
    state[f"worker_status:{process_name}"] = "running"
    state[f"worker_pid:{process_name}"] = os.getpid()
    try:
        target(*args)
    finally:
        state[f"worker_status:{process_name}"] = "stopped"


def _run_health_monitor(state, stop_event) -> None:
    # Demo integration: persist a health heartbeat while the node is running.
    while not stop_event.is_set():
        storage.save_process_health("HealthMon", "running")
        state["last_health_check"] = time.time()
        if stop_event.wait(5):
            break


def _request_shutdown(_signum: int, _frame: object) -> None:
    global _shutdown_requested
    _shutdown_requested = True


def start_processes(context, channels, state):
    # Connect the sensor, processor, health monitor, API, receiver, and sync worker.
    targets = {
        "SensorGen": (run_sensor_gen, (channels,)),
        "Processor": (run_processor, (channels, state)),
        "HealthMon": (_run_health_monitor, (state, channels.stop)),
        "API": (run_api_server, (state, channels.stop, channels)),
        "Receiver": (run_receiver, (channels.stop,)),
        "SyncWorker": (run_sync_worker, (channels, state)),
    }

    workers = {}

    for process_name in PROCESS_NAMES:
        target, args = targets[process_name]
        state[f"worker_status:{process_name}"] = "starting"

        process = context.Process(
            name=process_name,
            target=_worker_main,
            args=(process_name, target, args, state),
        )

        process.start()
        workers[process_name] = process

    return workers

def stop_processes(workers, channels) -> None:
    channels.stop.set()
    for process in workers.values():
        process.join(SHUTDOWN_TIMEOUT_SECONDS)
        if process.is_alive():
            process.terminate()
            process.join()


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
        workers = start_processes(context, channels, state)
        print(
            "Started workers: "
            f"{', '.join(workers)}. Dashboard: http://127.0.0.1:8000",
            flush=True,
        )

        while not _shutdown_requested:
            exited = [
                name for name, process in workers.items()
                if not process.is_alive()
            ]
            if exited:
                print(f"Worker exited unexpectedly: {', '.join(exited)}", flush=True)
                return 1
            time.sleep(0.2)
    finally:
        if workers:
            stop_processes(workers, channels)
        manager.shutdown()

    print("All workers stopped and reaped.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
