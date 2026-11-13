"""Validated data contracts used by the OS2 robot edge controller.

These small immutable objects carry sensor readings and actuator commands
between parts of the application. Validation happens when an object is made,
so later code can trust its basic fields.
"""

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class SensorReading:
    """One measured value and the time when the sensor observed it."""

    sensor_id: str  # Stable name, for example LIDAR_PROXIMITY_M.
    value: float  # Numeric sensor value, such as distance in metres.
    unit: str  # Unit used by the value, such as m or deg/s.
    observed_at: float  # Event time in seconds, supplied by the caller.

    def __post_init__(self) -> None:
        """Reject invalid data as soon as the reading is created."""
        if not isinstance(self.sensor_id, str) or not self.sensor_id.strip():
            raise ValueError("sensor_id must not be empty")
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise ValueError("unit must not be empty")
        if (
            isinstance(self.value, bool)
            or not isinstance(self.value, (int, float))
            or not isfinite(self.value)
        ):
            raise ValueError("sensor value must be finite")
        if (
            isinstance(self.observed_at, bool)
            or not isinstance(self.observed_at, (int, float))
            or not isfinite(self.observed_at)
        ):
            raise ValueError("observed_at must be finite")


@dataclass(frozen=True, slots=True)
class ActuatorCommand:
    """A command with a validity window, measured on a monotonic clock."""

    command_id: str  # Unique ID used to identify this command.
    actuator: str  # Output name, such as MOTOR_VEL or SAFETY_ESTOP_LATCH.
    value: float | bool  # Requested numeric output or on/off state.
    issued_at: float  # Monotonic time when the command was created.
    expires_at: float  # Monotonic deadline after which the command is unsafe.

    def __post_init__(self) -> None:
        """Check names, values, and the command's time window."""
        if not isinstance(self.command_id, str) or not self.command_id.strip():
            raise ValueError("command_id must not be empty")
        if not isinstance(self.actuator, str) or not self.actuator.strip():
            raise ValueError("actuator must not be empty")
        if not isinstance(self.value, bool) and (
            not isinstance(self.value, (int, float)) or not isfinite(self.value)
        ):
            raise ValueError("command value must be finite")
        if (
            isinstance(self.issued_at, bool)
            or not isinstance(self.issued_at, (int, float))
            or isinstance(self.expires_at, bool)
            or not isinstance(self.expires_at, (int, float))
            or not isfinite(self.issued_at)
            or not isfinite(self.expires_at)
        ):
            raise ValueError("command timestamps must be finite")
        # A zero-length or negative validity window can never be accepted.
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be later than issued_at")

    def is_expired(self, now: float) -> bool:
        """Return True at or after the expiry deadline."""
        if (
            isinstance(now, bool)
            or not isinstance(now, (int, float))
            or not isfinite(now)
        ):
            raise ValueError("current time must be finite")
        return now >= self.expires_at