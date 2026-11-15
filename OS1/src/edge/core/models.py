"""The two kinds of messages that travel between the node's processes."""

import time


class SensorEvent:
    """One sensor reading, sent from SensorGen to the Processor."""

    def __init__(self, sensor_id, value, unit, timestamp, monotonic=None):
        self.sensor_id = sensor_id    # for example "INDOOR_CO2_PPM"
        self.value = value
        self.unit = unit              # for example "ppm"
        self.timestamp = timestamp    # wall-clock time, for the logs and the database
        # Monotonic time of the reading, used for the command expiry (OS1-3).
        # Unlike the wall clock, it never jumps when the system time changes.
        if monotonic is None:
            monotonic = time.monotonic()
        self.monotonic = monotonic


class ActuatorCommand:
    """One damper command, sent from the Processor to the Actuator (OS1-3)."""

    def __init__(self, event_id, action, value, reason, expires_at):
        self.event_id = event_id      # the reading that caused the command
        self.action = action          # "HVAC_DAMPER_PCT"
        self.value = value            # 100
        self.reason = reason
        self.expires_at = expires_at  # a time.monotonic() value: after it, the command is stale
