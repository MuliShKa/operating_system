"""Data models for sensor readings, edge decisions, and process health."""

from dataclasses import dataclass


@dataclass
class SensorEvent:
    """One reading from a sensor."""

    sensor_id: str     # name of the sensor, e.g. "RADAR_SPEED"
    value: float       # number measured by the sensor
    unit: str          # unit of the value, e.g. "km/h"
    timestamp: float   # wall-clock time of the reading, in seconds (time.time())

    def __str__(self) -> str:
        return f"{self.sensor_id} = {self.value} {self.unit}"


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
