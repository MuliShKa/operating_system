"""Start and shut down the OS4 edge-node workers."""

from __future__ import annotations

import multiprocessing
import os
import signal
import time

from edge import storage
from edge.actuator import run_actuator
from edge.api_server import run_api_server
from edge.config import API_PORT
from edge.health import run_health_monitor
from edge.ingest import run_ingest
from edge.ipc import IpcChannels
from edge.processor import run_processor
from edge.receiver import run_receiver
from edge.sensor_gen import run_sensor_gen
from edge.sync_worker import run_sync_worker

# Start order matters a little: Receiver and Ingest create their listening
# sockets first, so the devices and the SyncWorker find them ready.
PROCESS_NAMES = (
    "Receiver",
    "Ingest",
    "Actuator",
    "Processor",
    "SensorGen",
    "SyncWorker",
    "HealthMon",
    "API",
)
SHUTDOWN_TIMEOUT_SECONDS = 5.0

_shutdown_requested = False


def _worker_main(process_name, target, args, state) -> None:
    # Publish the worker lifecycle to the dashboard's shared state.
    state[f"worker_status:{process_name}"] = "running"
    state[f"worker_pid:{process_name}"] = os.getpid()
    try:
        target(*args)
    finally:
        state[f"worker_status:{process_name}"] = "stopped"


def _request_shutdown(_signum: int, _frame: object) -> None:
    global _shutdown_requested
    _shutdown_requested = True


def start_processes(context, channels, state):
    """Start every worker as a separate OS process."""
    targets = {
        "Receiver": (run_receiver, (channels.stop,)),
        "Ingest": (run_ingest, (channels, state)),
        "Actuator": (run_actuator, (channels, state)),
        "Processor": (run_processor, (channels, state)),
        "SensorGen": (run_sensor_gen, (channels,)),
        "SyncWorker": (run_sync_worker, (channels, state)),
        "HealthMon": (run_health_monitor, (state, channels.stop)),
        "API": (run_api_server, (state, channels.stop, channels)),
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
    """Ask every worker to stop, then join (reap) it so no zombie is left."""
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

    # "spawn": every worker starts a clean interpreter (no inherited locks or threads).
    context = multiprocessing.get_context("spawn")
    manager = context.Manager()
    state = manager.dict()
    channels = IpcChannels(context)
    workers = {}

    try:
        # Initialize the database before any worker writes to it.
        storage.initialize_database()
        state["pending_events"] = storage.get_pending_event_count()
        workers = start_processes(context, channels, state)
        print(
            "Started workers: "
            f"{', '.join(workers)}. Dashboard: http://127.0.0.1:{API_PORT}",
            flush=True,
        )

        while not _shutdown_requested:
            exited = [
                name for name, process in workers.items()
                if not process.is_alive()
            ]
            if exited:
                # Exit code 1 lets systemd / Docker restart the whole node.
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
