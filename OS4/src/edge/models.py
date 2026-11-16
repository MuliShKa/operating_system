"""Data models for sensor readings, actuator commands and process health."""

from dataclasses import dataclass


@dataclass
class SensorEvent:
    """One reading, as the Ingest process hands it to the Processor.

    Two clocks travel with every reading (scenario OS4-2):
      observed_at  - wall-clock EVENT time: when the sensor measured it
      received_at  - wall-clock RECEIPT time: when this node received it
    and two monotonic values, because wall clocks can jump (NTP, manual change):
      observed_mono - the event time converted ONCE, at arrival, into this
                      machine's monotonic clock: received_mono - (received_at - observed_at)
      received_mono - time.monotonic() at arrival
    All freshness / TTL / staleness decisions use the monotonic values only.
    """

    sensor_id: str          # "PM25", "NOISE" or "LUX"
    value: float
    unit: str
    observed_at: float      # time.time() at the sensor
    received_at: float      # time.time() at this node
    observed_mono: float
    received_mono: float

    @property
    def lateness_s(self) -> float:
        """How long the reading travelled before arriving (never negative)."""
        return max(0.0, self.received_at - self.observed_at)

    def __str__(self) -> str:
        return f"{self.sensor_id} = {self.value} {self.unit}"


@dataclass
class ActuatorCommand:
    """A command for the mist cannon relay, waiting for the Actuator to apply it."""

    event_id: str      # the reading that caused the command
    action: str        # "MIST_CANNON_RELAY"
    value: float       # 1.0 = ON
    expires_at: float  # time.monotonic() deadline: the command is stale after it
    reason: str        # why the command was issued


@dataclass
class EdgeDecision:
    """One decision taken by the node from the sensor readings."""

    action: str        # e.g. "MIST_CANNON_RELAY"
    value: float
    reason: str
    timestamp: float   # wall-clock time of the decision, in seconds

    def __str__(self) -> str:
        return f"{self.action} = {self.value} ({self.reason})"
