import unittest

from edge.bounded_queue import BoundedSensorQueue
from edge.control import (
    JitterMonitor,
    RobotSafetyController,
    evaluate_pending_sensor_readings,
    run_periodic_control_loop,
)
from edge.models import ActuatorCommand, SensorReading


class JitterMonitorTests(unittest.TestCase):
    """Check measured timing error and periodic scheduling behavior."""

    def test_measures_deviation_from_fifty_millisecond_period(self) -> None:
        """A 53 ms interval has 3 ms of jitter against the 50 ms target."""
        monitor = JitterMonitor(target_period_s=0.05)

        self.assertIsNone(monitor.record_tick(10.0))
        self.assertAlmostEqual(monitor.record_tick(10.053), 0.003)

    def test_rejects_non_monotonic_ticks(self) -> None:
        """Control tick times must not go backward or repeat."""
        monitor = JitterMonitor()
        monitor.record_tick(10.0)

        with self.assertRaises(ValueError):
            monitor.record_tick(10.0)

    def test_control_loop_runs_on_periodic_deadlines(self) -> None:
        """A fake clock makes the 50 ms schedule test fast and repeatable."""
        class FakeClock:
            now = 0.0

            def __call__(self) -> float:
                return self.now

        class StopAfterWaits:
            waits = 0

            def is_set(self) -> bool:
                return self.waits >= 2

            def wait(self, timeout: float) -> None:
                clock.now += timeout
                self.waits += 1

        clock = FakeClock()
        stop_event = StopAfterWaits()
        ticks: list[tuple[float, float | None]] = []

        run_periodic_control_loop(
            stop_event, lambda now, jitter: ticks.append((now, jitter)), clock=clock
        )

        self.assertEqual(ticks, [(0.0, None), (0.05, 0.0)])


class RobotSafetyControllerTests(unittest.TestCase):
    """Check the LiDAR threshold, stop latch, and actuator safety rules."""

    def setUp(self) -> None:
        """Use the handbook's 0.8 m threshold and 500 ms command TTL."""
        self.controller = RobotSafetyController(
            obstacle_threshold_m=0.8,
            command_ttl_s=0.5,
        )

    def reading(self, distance: float) -> SensorReading:
        """Build a LiDAR sample for a specific distance."""
        return SensorReading("LIDAR_PROXIMITY_M", distance, "m", 10.0)

    def test_trips_estop_only_below_obstacle_threshold(self) -> None:
        """The threshold itself is safe; a closer obstacle trips E-stop."""
        self.assertEqual(self.controller.evaluate_proximity(self.reading(0.8), 20.0), ())

        commands = self.controller.evaluate_proximity(self.reading(0.79), 20.05)

        self.assertTrue(self.controller.estop_latched)
        self.assertEqual(
            [(command.actuator, command.value) for command in commands],
            [("SAFETY_ESTOP_LATCH", True), ("MOTOR_VEL", 0.0)],
        )
        self.assertTrue(all(command.expires_at == 20.55 for command in commands))

    def test_estop_remains_latched_after_obstacle_clears(self) -> None:
        """Moving the obstacle away does not automatically restart the robot."""
        self.controller.evaluate_proximity(self.reading(0.5), 20.0)

        commands = self.controller.evaluate_proximity(self.reading(1.0), 20.05)

        self.assertTrue(self.controller.estop_latched)
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[1].value, 0.0)

    def test_rejects_expired_and_unsafe_motor_commands(self) -> None:
        """Expired commands and non-zero speed are rejected during E-stop."""
        self.controller.evaluate_proximity(self.reading(0.5), 20.0)
        fresh_motor_command = ActuatorCommand("drive", "MOTOR_VEL", 1.0, 20.1, 20.6)
        expired_motor_command = ActuatorCommand("old", "MOTOR_VEL", 0.0, 19.0, 20.0)

        self.assertFalse(self.controller.accepts(fresh_motor_command, 20.2))
        self.assertFalse(self.controller.accepts(expired_motor_command, 20.2))


class QueuedSensorControlTests(unittest.TestCase):
    """Check that queued sensor samples reach the safety controller."""

    def test_batch_applies_close_lidar_even_if_a_safe_sample_follows(self) -> None:
        """A later safe sample must not erase a close obstacle in the same batch."""
        sensor_queue = BoundedSensorQueue(maxsize=8)
        controller = RobotSafetyController()
        sensor_queue.put(SensorReading("IMU_YAW_RATE", 0.1, "rad/s", 1.0))
        sensor_queue.put(SensorReading("LIDAR_PROXIMITY_M", 0.5, "m", 1.1))
        sensor_queue.put(SensorReading("LIDAR_PROXIMITY_M", 1.2, "m", 1.2))

        commands = evaluate_pending_sensor_readings(sensor_queue, controller, 20.0)

        self.assertTrue(controller.estop_latched)
        self.assertEqual(
            [(command.actuator, command.value) for command in commands],
            [("SAFETY_ESTOP_LATCH", True), ("MOTOR_VEL", 0.0)],
        )
        self.assertIsNone(sensor_queue.get(timeout=0.001))

    def test_imu_reading_alone_does_not_trigger_lidar_safety(self) -> None:
        """Yaw-rate data is not used as a LiDAR distance measurement."""
        sensor_queue = BoundedSensorQueue(maxsize=4)
        controller = RobotSafetyController()
        sensor_queue.put(SensorReading("IMU_YAW_RATE", 0.1, "rad/s", 1.0))

        commands = evaluate_pending_sensor_readings(sensor_queue, controller, 20.0)

        self.assertEqual(commands, ())
        self.assertFalse(controller.estop_latched)


if __name__ == "__main__":
    unittest.main()