# Data models for sensor readings, edge decisions, actuator commands and process health.
#
# Each class has two text versions:
# - __str__: short and readable, used by print(obj), str(obj) and f-strings.
# - __repr__: shows every field, used when the object is inside a list or dict.

import time


class SensorEvent:
    """
    One reading from a sensor.
    """

    def __init__(
        self,
        sensor_id: str,
        value: float,
        unit: str,
        timestamp: float,
        monotonic: float | None = None,
    ) -> None:

        # The sensor_id is the name of the sensor that made the reading.
        self.sensor_id = sensor_id

        # The value is the number measured by the sensor.
        self.value = value

        # The unit is the unit of the value (for example "°C").
        self.unit = unit

        # The timestamp is the time of the reading, in seconds.
        self.timestamp = timestamp

        # The monotonic time of the reading, used for command expiry (OS1-3).
        # It is not the wall clock: it cannot jump when the system time changes.
        self.monotonic = time.monotonic() if monotonic is None else monotonic

    def __str__(self) -> str:
        """
        Return a short, readable text.
        """

        return f"{self.sensor_id} = {self.value} {self.unit}"

    def __repr__(self) -> str:
        """
        Return a text that shows every field.
        """

        return (
            f"SensorEvent(sensor_id={self.sensor_id!r}, value={self.value}, "
            f"unit={self.unit!r}, timestamp={self.timestamp})"
        )


class EdgeDecision:
    """
    One decision taken by the node from the sensor readings.
    """

    def __init__(self, action: str, value: float, reason: str, timestamp: float) -> None:

        # The action is what the node decided to do.
        self.action = action

        # The value is the number that goes with the action.
        self.value = value

        # The reason explains why the action was taken.
        self.reason = reason

        # The timestamp is the time of the decision, in seconds.
        self.timestamp = timestamp

    def __str__(self) -> str:
        """
        Return a short, readable text.
        """

        return f"{self.action} = {self.value} ({self.reason})"

    def __repr__(self) -> str:
        """
        Return a text that shows every field.
        """

        return (
            f"EdgeDecision(action={self.action!r}, value={self.value}, "
            f"reason={self.reason!r}, timestamp={self.timestamp})"
        )


class ActuatorCommand:
    """
    One command sent from the Processor to the Actuator (OS1-3).
    """

    def __init__(self, event_id: str, action: str, value: float, reason: str, expires_at: float) -> None:

        # The event_id is the sensor event that caused the command.
        self.event_id = event_id

        # The action and value say what to do (for example HVAC_DAMPER_PCT = 100).
        self.action = action
        self.value = value

        # The reason explains why the command was issued.
        self.reason = reason

        # The expires_at is a time.monotonic() value: after it, the command is stale.
        self.expires_at = expires_at

    def __str__(self) -> str:
        """
        Return a short, readable text.
        """

        return f"{self.action} = {self.value} for event {self.event_id}"

    def __repr__(self) -> str:
        """
        Return a text that shows every field.
        """

        return (
            f"ActuatorCommand(event_id={self.event_id!r}, action={self.action!r}, "
            f"value={self.value}, reason={self.reason!r}, expires_at={self.expires_at})"
        )


class ProcessHealth:
    """
    The health of one process of the node.
    """

    def __init__(self, process_name: str, pid: int, status: str, cpu_percent: float, memory_mb: float) -> None:

        # The process_name is the name of the process (for example "Processor").
        self.process_name = process_name

        # The pid is the process ID given by the OS.
        self.pid = pid

        # The status is the state of the process (for example "running").
        self.status = status

        # The cpu_percent is how much CPU the process uses.
        self.cpu_percent = cpu_percent

        # The memory_mb is how much RAM the process uses, in MB.
        self.memory_mb = memory_mb

    def __str__(self) -> str:
        """
        Return a short, readable text.
        """

        return (
            f"{self.process_name} (PID {self.pid}): {self.status}, "
            f"CPU {self.cpu_percent}%, RAM {self.memory_mb} MB"
        )

    def __repr__(self) -> str:
        """
        Return a text that shows every field.
        """

        return (
            f"ProcessHealth(process_name={self.process_name!r}, pid={self.pid}, "
            f"status={self.status!r}, cpu_percent={self.cpu_percent}, memory_mb={self.memory_mb})"
        )
