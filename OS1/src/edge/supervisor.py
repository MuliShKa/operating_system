"""
The supervisor: starts the 8 worker processes, watches them, and stops them cleanly.

Run: PYTHONPATH=src python -m edge.supervisor
"""

import multiprocessing
import os
import signal
import time

from edge.core import storage
from edge.core.api_server import run_api_server
from edge.core.ipc import IpcChannels
from edge.node_config import API_PORT
from edge.os1_1_ingestion import inventory
from edge.os1_1_ingestion.processor import run_processor
from edge.os1_1_ingestion.sensors import run_sensors
from edge.os1_3_ventilation.actuator import run_actuator
from edge.os1_4_contention.proc_sampler import run_proc_sampler
from edge.os1_5_wan_outage.receiver import run_receiver
from edge.os1_5_wan_outage.sync_worker import run_sync_worker

SHUTDOWN_TIMEOUT_S = 3.0
stop_requested = False


def run_health_monitor(channels) -> None:
    """Write a heartbeat into process_health every 5 s."""
    while not channels.stop.is_set():
        storage.save_process_health("HealthMon", "running")
        channels.stop.wait(5)


def run_worker(name, target, args, state) -> None:
    """Runs inside each child process: publish its PID for the dashboard, then do the work."""
    state[f"worker:{name}"] = {"pid": os.getpid(), "status": "running"}
    try:
        target(*args)
    finally:
        state[f"worker:{name}"] = {"pid": os.getpid(), "status": "stopped"}


def on_signal(_signum, _frame) -> None:
    # Ctrl+C (SIGINT) or systemd/docker stop (SIGTERM): only set a flag, the main loop does the rest.
    global stop_requested
    stop_requested = True


def main() -> int:
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    # "spawn": every worker is a fresh Python process with its own memory.
    context = multiprocessing.get_context("spawn")
    manager = context.Manager()
    state = manager.dict()  # shared dictionary read by the dashboard
    channels = IpcChannels(context)

    storage.initialize_database()
    state["pending_events"] = storage.count_pending_events()
    # OS1-1: read the cached building inventory once, before the sensors start.
    state["building"] = inventory.load_inventory()
    print(f"Building inventory: {state['building']}", flush=True)

    workers = {
        "SensorGen": (run_sensors, (channels,)),
        "Processor": (run_processor, (channels, state)),
        "Actuator": (run_actuator, (channels, state)),
        "HealthMon": (run_health_monitor, (channels,)),
        "ProcSampler": (run_proc_sampler, (channels, state)),
        "API": (run_api_server, (channels, state)),
        "Receiver": (run_receiver, (channels.stop,)),
        "SyncWorker": (run_sync_worker, (channels, state)),
    }
    processes = {
        name: context.Process(name=name, target=run_worker, args=(name, target, args, state))
        for name, (target, args) in workers.items()
    }
    for process in processes.values():
        process.start()
    print(f"Started workers: {', '.join(processes)}. Dashboard: http://127.0.0.1:{API_PORT}", flush=True)

    exit_code = 0
    try:
        while not stop_requested:
            dead = [name for name, process in processes.items() if not process.is_alive()]
            if dead:
                print(f"Worker exited unexpectedly: {', '.join(dead)}", flush=True)
                exit_code = 1  # systemd / docker restart the whole node
                break
            time.sleep(0.2)
    finally:
        # Ask every worker to stop, then join() each one so no zombie is left.
        channels.stop.set()
        for process in processes.values():
            process.join(SHUTDOWN_TIMEOUT_S)
            if process.is_alive():
                process.terminate()
                process.join()
        manager.shutdown()

    print("All workers stopped and reaped.", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
