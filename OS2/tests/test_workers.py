import dataclasses
import multiprocessing as mp
import tempfile
import time
import unittest
from pathlib import Path

from edge import storage
from edge.bounded_queue import BoundedSensorQueue
from edge.config import load_config
from edge.models import ActuatorCommand
from edge.sensor import run_sensor_generator
from edge.unix_socket import UnixMessageClient
from edge.workers import Actuators, run_controller, run_safety_monitor


def temp_config(directory: str):
    root = Path(directory)
    return dataclasses.replace(
        load_config(),
        safety_socket=root / "safety.sock",
        upstream_socket=root / "upstream.sock",
        database=root / "os2.db",
        upstream_database=root / "upstream.db",
    )


class ActuatorStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.config = temp_config(self.directory.name)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_motor_stops_when_command_expires(self) -> None:
        actuators = Actuators(self.config, latched=False)
        actuators.apply(ActuatorCommand("c1", "MOTOR_VEL", 0.5, 10.0, 10.5), 10.1)

        self.assertFalse(actuators.stop_if_expired(10.4))
        self.assertEqual(actuators.motor_vel, 0.5)
        self.assertTrue(actuators.stop_if_expired(10.5))
        self.assertEqual(actuators.motor_vel, 0.0)

    def test_restored_latch_rejects_motion(self) -> None:
        actuators = Actuators(self.config, latched=True)

        accepted = actuators.apply(
            ActuatorCommand("c1", "MOTOR_VEL", 0.5, 10.0, 10.5), 10.1
        )

        self.assertFalse(accepted)
        self.assertEqual(actuators.motor_vel, 0.0)


class ProcessTopologyTests(unittest.TestCase):
    """Sensor, controller and safety monitor as three separate processes."""

    def test_pipeline_runs_and_writes_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = temp_config(directory)
            storage.init_db(config.database)
            context = mp.get_context("spawn")
            stop_event = context.Event()
            sensor_queue = BoundedSensorQueue(config.queue_size, context)
            processes = [
                context.Process(target=run_safety_monitor, args=(stop_event, config)),
                context.Process(
                    target=run_sensor_generator,
                    args=(sensor_queue, stop_event, config.period_s, 7),
                ),
                context.Process(
                    target=run_controller, args=(sensor_queue, stop_event, config)
                ),
            ]
            for process in processes:
                process.start()

            try:
                deadline = time.monotonic() + 10
                while storage.outbox_counts(config.database)["total"] < 2:
                    self.assertLess(time.monotonic(), deadline, "no outbox events")
                    time.sleep(0.1)
                status = UnixMessageClient(config.safety_socket).request(
                    {"cmd": "status"}
                )
            finally:
                stop_event.set()
                for process in processes:
                    process.join(timeout=5)
                    if process.is_alive():
                        process.terminate()
                        process.join()

            self.assertEqual([p.exitcode for p in processes], [0, 0, 0])
            types = {e["event_type"] for e in storage.pending_events(config.database, 100)}
            self.assertIn("CONTROL_TELEMETRY", types)
            if status["latched"]:
                self.assertEqual(storage.load_state(config.database, "estop_latched"), "1")
                self.assertEqual(status["motor_vel"], 0.0)


if __name__ == "__main__":
    unittest.main()
