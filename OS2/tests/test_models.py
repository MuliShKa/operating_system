import unittest

from edge.models import ActuatorCommand, SensorReading


class SensorReadingTests(unittest.TestCase):
    """Check validation of sensor values and their identifying fields."""

    def test_accepts_finite_reading(self) -> None:
        """A normal LiDAR value should be stored without changes."""
        reading = SensorReading("LIDAR_PROXIMITY_M", 1.2, "m", 10.0)

        self.assertEqual(reading.sensor_id, "LIDAR_PROXIMITY_M")
        self.assertEqual(reading.value, 1.2)

    def test_rejects_non_finite_reading(self) -> None:
        """NaN must not enter the queue as a sensor measurement."""
        with self.assertRaises(ValueError):
            SensorReading("LIDAR_PROXIMITY_M", float("nan"), "m", 10.0)


class ActuatorCommandTests(unittest.TestCase):
    """Check command validity windows and their expiry boundary."""

    def test_expires_at_ttl_boundary(self) -> None:
        """A command is valid before, but not at, its expiry time."""
        command = ActuatorCommand(
            command_id="cmd-1",
            actuator="MOTOR_VEL",
            value=0.5,
            issued_at=10.0,
            expires_at=10.5,
        )

        self.assertFalse(command.is_expired(10.499))
        self.assertTrue(command.is_expired(10.5))

    def test_rejects_non_positive_ttl(self) -> None:
        """A command must have a positive amount of time to be useful."""
        with self.assertRaises(ValueError):
            ActuatorCommand("cmd-2", "MOTOR_VEL", 0.0, 10.0, 10.0)


if __name__ == "__main__":
    unittest.main()