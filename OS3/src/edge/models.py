"""Data models for sensor readings, edge decisions, and process health."""

from dataclasses import dataclass


@dataclass
class SensorEvent:
    """One reading from a sensor."""

    sensor_id: str     # name of the sensor, e.g. "RADAR_SPEED"
    value: float       # number measured by the sensor
    unit: str          # unit of the value, e.g. "km/h"
    timestamp: float   # wall-clock time of the reading, in seconds (time.time())
    monotonic: float = 0.0  # time.monotonic() when the sensor was read (0 = unknown)

    def __str__(self) -> str:
        return f"{self.sensor_id} = {self.value} {self.unit}"


@dataclass
class ActuatorCommand:
    """A command for the speed sign, waiting for the Actuator to apply it."""

    event_id: str      # the reading that caused the command
    action: str        # e.g. "VARIABLE_SPEED_SIGN_KMH"
    value: float       # e.g. 30
    expires_at: float  # time.monotonic() deadline: the command is stale after it
    reason: str        # why the command was issued


@dataclass
class EdgeDecision:
    """One decision taken by the node from the sensor readings."""

    action: str        # what the node decided to do, e.g. "VARIABLE_SPEED_SIGN_KMH"
    value: float       # number that goes with the action, e.g. 30
    reason: str        # why the action was taken
    timestamp: float   # wall-clock time of the decision, in seconds

    def __str__(self) -> str:
        return f"{self.action} = {self.value} ({self.reason})"


@dataclass
class ProcessHealth:
    """The health of one process of the node."""

    process_name: str
    pid: int
    status: str
    cpu_percent: float
    memory_mb: float

    def __str__(self) -> str:
        return (
            f"{self.process_name} (PID {self.pid}): {self.status}, "
            f"CPU {self.cpu_percent}%, RAM {self.memory_mb} MB"
        )
