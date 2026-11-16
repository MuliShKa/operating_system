import multiprocessing
import sys
import tempfile
import threading
import time
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edge import storage, supervisor
from edge.ipc import IpcChannels


def _wait_for_stop(stop_event):
    stop_event.wait()


class TestRestartBudget(unittest.TestCase):
    def test_limits_restarts_inside_the_window_and_allows_them_afterward(self):
        restart_times = deque()

        self.assertTrue(supervisor._allow_restart(restart_times, 0.0))
        self.assertTrue(supervisor._allow_restart(restart_times, 1.0))
        self.assertTrue(supervisor._allow_restart(restart_times, 2.0))
        self.assertFalse(supervisor._allow_restart(restart_times, 3.0))
        self.assertTrue(supervisor._allow_restart(restart_times, 62.0))


class TestWorkerRecovery(unittest.TestCase):
    def test_only_exited_worker_restarts_with_shared_channels(self):
        context = multiprocessing.get_context("spawn")
        channels = IpcChannels(context)
        state = {}
        targets = {
            "Processor": (_wait_for_stop, (channels.stop,)),
            "SensorGen": (_wait_for_stop, (channels.stop,)),
        }
        original_database_path = storage.DATABASE_PATH
        previous_shutdown = supervisor._shutdown_requested
        workers = {}
        monitor = None

        with tempfile.TemporaryDirectory() as temporary_directory:
            try:
                storage.DATABASE_PATH = Path(temporary_directory) / "recovery.db"
                storage.initialize_database()

                workers = {
                    name: supervisor._start_worker(
                        context, state, name, *target
                    )
                    for name, target in targets.items()
                }
                original_processor = workers["Processor"]
                unaffected_pid = workers["SensorGen"].pid
                original_processor.kill()
                original_processor.join(timeout=5)

                supervisor._shutdown_requested = False
                monitor = threading.Thread(
                    target=supervisor._monitor_workers,
                    args=(context, state, workers, targets),
                )
                monitor.start()

                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    replacement = workers.get("Processor")
                    if (
                        state.get("worker_restart_count:Processor", 0) >= 1
                        and replacement is not None
                        and replacement is not original_processor
                        and replacement.is_alive()
                    ):
                        break
                    time.sleep(0.02)

                self.assertEqual(state["worker_restart_count:Processor"], 1)
                self.assertIsNot(workers["Processor"], original_processor)
                self.assertEqual(
                    state["worker_pid:Processor"], workers["Processor"].pid
                )
                self.assertTrue(workers["Processor"].is_alive())
                self.assertEqual(state["worker_last_exit_code:Processor"], -9)
                self.assertEqual(workers["SensorGen"].pid, unaffected_pid)
                self.assertTrue(workers["SensorGen"].is_alive())
                self.assertEqual(
                    storage.get_latest_process_health()["Processor"]["status"],
                    "restarting",
                )

            finally:
                supervisor._shutdown_requested = True
                channels.stop.set()
                if monitor is not None:
                    monitor.join(timeout=5)
                if workers:
                    supervisor.stop_processes(workers, channels)
                storage.DATABASE_PATH = original_database_path
                supervisor._shutdown_requested = previous_shutdown


if __name__ == "__main__":
    unittest.main()
