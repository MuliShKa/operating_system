import multiprocessing
import os
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edge import storage, supervisor
from edge.ipc import IpcChannels
from edge.models import SensorEvent
from edge.processor import run_processor
from edge.receiver import run_receiver
from edge.sync_worker import run_sync_worker


ENVIRONMENT_KEYS = (
    "EDGE_DATABASE_PATH",
    "EDGE_RECEIVER_DATABASE_PATH",
    "EDGE_RECEIVER_HOST",
    "EDGE_RECEIVER_PORT",
    "EDGE_RECEIVER_URL",
)


def _wait_until(predicate, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("timed out waiting for compound-failure scenario")


def _unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _receiver_ready(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.1) as connection:
            connection.sendall(b"GET / HTTP/1.0\r\nHost: localhost\r\n\r\n")
            return connection.recv(1024).startswith(b"HTTP/")
    except OSError:
        return False


def _received_count(database_path: Path) -> int:
    with sqlite3.connect(database_path) as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM received_events"
        ).fetchone()[0]


def _event_count(database_path: Path) -> int:
    with sqlite3.connect(database_path) as connection:
        return connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]


def _sent_count(database_path: Path) -> int:
    with sqlite3.connect(database_path) as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM outbox WHERE status = 'sent'"
        ).fetchone()[0]


class TestCompoundFailure(unittest.TestCase):
    def test_wan_outage_and_processor_restart_preserve_outbox_delivery(self):
        original_database_path = storage.DATABASE_PATH
        original_environment = {
            key: os.environ.get(key) for key in ENVIRONMENT_KEYS
        }
        previous_shutdown = supervisor._shutdown_requested
        manager = None
        channels = None
        receiver_process = None
        sync_process = None
        workers = {}
        monitor = None

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            edge_database = root / "edge.db"
            receiver_database = root / "receiver.db"
            receiver_port = _unused_port()
            os.environ["EDGE_DATABASE_PATH"] = str(edge_database)
            os.environ["EDGE_RECEIVER_DATABASE_PATH"] = str(receiver_database)
            os.environ["EDGE_RECEIVER_HOST"] = "127.0.0.1"
            os.environ["EDGE_RECEIVER_PORT"] = str(receiver_port)
            os.environ["EDGE_RECEIVER_URL"] = (
                f"http://127.0.0.1:{receiver_port}/api/events"
            )
            storage.DATABASE_PATH = edge_database

            try:
                storage.initialize_database()
                context = multiprocessing.get_context("spawn")
                manager = context.Manager()
                state = manager.dict()
                channels = IpcChannels(context)
                channels.wan_online.clear()

                receiver_process = context.Process(
                    name="TestReceiver",
                    target=run_receiver,
                    args=(channels.stop,),
                )
                receiver_process.start()
                _wait_until(lambda: _receiver_ready(receiver_port))

                sync_process = context.Process(
                    name="TestSyncWorker",
                    target=run_sync_worker,
                    args=(channels, state),
                )
                sync_process.start()

                processor_target = (run_processor, (channels, state))
                targets = {"Processor": processor_target}
                workers["Processor"] = supervisor._start_worker(
                    context, state, "Processor", *processor_target
                )

                for number in range(2):
                    channels.sensor_events.put(
                        SensorEvent(
                            "SLUICE_WATER_LEVEL_M",
                            2.0 + number / 10,
                            "m",
                            time.time(),
                        )
                    )

                _wait_until(lambda: _event_count(edge_database) == 2)
                self.assertEqual(storage.get_pending_event_count(), 2)
                self.assertEqual(_received_count(receiver_database), 0)
                self.assertFalse(channels.wan_online.is_set())

                workers["Processor"].kill()
                workers["Processor"].join(timeout=5)
                self.assertFalse(workers["Processor"].is_alive())

                supervisor._shutdown_requested = False
                monitor = threading.Thread(
                    target=supervisor._monitor_workers,
                    args=(context, state, workers, targets),
                )
                monitor.start()
                _wait_until(
                    lambda: state.get("worker_restart_count:Processor", 0) == 1
                    and workers["Processor"].is_alive()
                )
                self.assertEqual(state["worker_restart_count:Processor"], 1)
                self.assertFalse(channels.wan_online.is_set())

                channels.sensor_events.put(
                    SensorEvent(
                        "SLUICE_WATER_LEVEL_M",
                        2.2,
                        "m",
                        time.time(),
                    )
                )
                _wait_until(lambda: _event_count(edge_database) == 3)
                self.assertEqual(storage.get_pending_event_count(), 3)
                self.assertEqual(_received_count(receiver_database), 0)

                channels.wan_online.set()
                _wait_until(
                    lambda: storage.get_pending_event_count() == 0
                    and _received_count(receiver_database) == 3
                )
                self.assertEqual(_event_count(edge_database), 3)
                self.assertEqual(_received_count(receiver_database), 3)
                self.assertEqual(_sent_count(edge_database), 3)

            finally:
                supervisor._shutdown_requested = True
                if monitor is not None:
                    monitor.join(timeout=5)
                try:
                    if workers and channels is not None:
                        supervisor.stop_processes(workers, channels)
                finally:
                    for process in (sync_process, receiver_process):
                        if process is None or process.pid is None:
                            continue
                        process.join(timeout=5)
                        if process.is_alive():
                            process.terminate()
                            process.join(timeout=5)
                        if process.is_alive():
                            process.kill()
                            process.join(timeout=5)
                        if not process.is_alive():
                            process.close()
                    if manager is not None:
                        manager.shutdown()
                    storage.DATABASE_PATH = original_database_path
                    for key, value in original_environment.items():
                        if value is None:
                            os.environ.pop(key, None)
                        else:
                            os.environ[key] = value
                    supervisor._shutdown_requested = previous_shutdown


if __name__ == "__main__":
    unittest.main()
