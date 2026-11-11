"""Prepare, monitor, and shut down the connected edge-node worker processes."""

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

PROCESS_NAMES = ("SensorGen", "Processor", "HealthMon", "API")
SHUTDOWN_TIMEOUT_SECONDS = 3.0

_shutdown_requested = False


def _worker_main(process_name, target, args, state) -> None:
    # Publish lifecycle metadata before calling the worker so the dashboard can
    # distinguish a process that is starting from one that is running.
    state[f"worker_status:{process_name}"] = "running"
    state[f"worker_pid:{process_name}"] = os.getpid()
    try:
        target(*args)
    finally:
        # The finally block also records a stopped state if the worker raises.
        state[f"worker_status:{process_name}"] = "stopped"


def _run_health_monitor(state, stop_event) -> None:
    # Store a persistent heartbeat and a live timestamp for the dashboard.
    # Event.wait keeps the five-second interval interruptible during shutdown.
    while not stop_event.is_set():
        storage.save_process_health("HealthMon", "running")
        state["last_health_check"] = time.time()
        if stop_event.wait(5):
            break


def _request_shutdown(_signum: int, _frame: object) -> None:
    global _shutdown_requested
    _shutdown_requested = True


def start_processes(context, channels, state):
    # Keep each worker's entry point and arguments together so all processes
    # receive the same IPC channels and shared state where needed.
    targets = {
        "SensorGen": (run_sensor_gen, (channels,)),
        "Processor": (run_processor, (channels, state)),
        "HealthMon": (_run_health_monitor, (state, channels.stop)),
        "API": (run_api_server, (state, channels.stop)),
    }
    workers = {}
    for process_name in PROCESS_NAMES:
        target, args = targets[process_name]
        # Set this before start() so the dashboard has a status during startup.
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
    # Ask cooperative workers to exit first, allowing them to finish cleanup.
    channels.stop.set()
    for process in workers.values():
        process.join(SHUTDOWN_TIMEOUT_SECONDS)
        if process.is_alive():
            # Bound shutdown time if a worker ignores the stop request.
            process.terminate()
            # Reap the terminated child so it does not remain as a zombie.
            process.join()


def main() -> int:
    global _shutdown_requested
    _shutdown_requested = False
    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)

    # Use an explicit start method for consistent, isolated child initialization.
    context = multiprocessing.get_context("spawn")
    manager = context.Manager()
    state = manager.dict()
    # Create IPC resources once and share them with every worker process.
    channels = IpcChannels(context)
    workers = {}

    try:
        # The Processor writes events immediately, so prepare the database first.
        storage.initialize_database()
        state["pending_events"] = storage.get_pending_event_count()
        workers = start_processes(context, channels, state)
        print(
            "Started workers: "
            f"{', '.join(workers)}. Dashboard: http://127.0.0.1:8000",
            flush=True,
        )

        while not _shutdown_requested:
            # Detect dead workers promptly; this version reports a failure and
            # shuts down the remaining workers rather than restarting the child.
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
