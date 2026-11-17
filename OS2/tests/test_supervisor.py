import dataclasses
import math
import signal
import tempfile
import threading
import time
import unittest
from pathlib import Path

from edge import storage
from edge.config import load_config
from edge.supervisor import ProcessSupervisor, RestartBudget


class RestartBudgetTests(unittest.TestCase):
    def test_limits_restarts_to_a_rolling_window(self) -> None:
        budget = RestartBudget(limit=2, window_s=10)

        self.assertTrue(budget.try_restart(1.0))
        self.assertTrue(budget.try_restart(2.0))
        self.assertFalse(budget.try_restart(3.0))
        self.assertTrue(budget.try_restart(11.0))

    def test_rejects_non_finite_restart_time(self) -> None:
        budget = RestartBudget(limit=1, window_s=10)

        with self.assertRaises(ValueError):
            budget.try_restart(math.nan)


class ProcessSupervisorLifecycleTests(unittest.TestCase):
    def test_restarts_one_worker_then_stops_all_workers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = dataclasses.replace(
                load_config(),
                safety_socket=root / "safety.sock",
                upstream_socket=root / "upstream.sock",
                database=root / "os2.db",
                upstream_database=root / "upstream.db",
                api_port=0,
            )
            supervisor = ProcessSupervisor(config, shutdown_timeout_s=1)
            errors: list[BaseException] = []
            expected_workers = {
                "api-server",
                "controller",
                "safety-monitor",
                "sensor-generator",
                "sync-worker",
            }

            def crash_then_stop() -> None:
                try:
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        processes = supervisor._processes.copy()
                        if (
                            processes.keys() == expected_workers
                            and all(process.is_alive() for process in processes.values())
                        ):
                            break
                        time.sleep(0.05)
                    else:
                        raise AssertionError("all workers did not start")

                    before = supervisor._processes.copy()
                    original_pids = {
                        name: process.pid
                        for name, process in before.items()
                        if name != "controller"
                    }
                    original_controller_pid = before["controller"].pid
                    before["controller"].kill()

                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        controller = supervisor._processes.get("controller")
                        if (
                            controller is not None
                            and controller.pid != original_controller_pid
                            and controller.is_alive()
                        ):
                            break
                        time.sleep(0.05)
                    else:
                        raise AssertionError("controller was not restarted")

                    current = supervisor._processes.copy()
                    for name, pid in original_pids.items():
                        self.assertEqual(current[name].pid, pid)
                        self.assertTrue(current[name].is_alive())
                except BaseException as error:
                    errors.append(error)
                finally:
                    supervisor._request_shutdown_from_signal(signal.SIGTERM)

            coordinator = threading.Thread(target=crash_then_stop, daemon=True)
            coordinator.start()
            supervisor.run()
            coordinator.join(timeout=5)

            self.assertFalse(coordinator.is_alive(), "shutdown coordinator did not finish")
            self.assertEqual(errors, [])
            latest = {
                item["process_name"]: item["status"]
                for item in storage.latest_process_health(config.database)
            }
            self.assertEqual(set(latest), expected_workers)
            self.assertTrue(all(status == "stopped" for status in latest.values()))


if __name__ == "__main__":
    unittest.main()
