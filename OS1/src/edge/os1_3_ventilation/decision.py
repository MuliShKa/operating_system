"""OS1-3: the ventilation rule and the command expiry (TTL)."""

import time

from edge.core.models import ActuatorCommand
from edge.node_config import RULE

CO2_SENSOR = RULE["sensor"]
CO2_THRESHOLD_PPM = float(RULE["above"])
COMMAND_TTL_S = float(RULE["ttl_s"])


def make_command(event_id: str, co2_ppm: float, read_at: float) -> ActuatorCommand | None:
    """
    CO2 strictly above 1000 ppm -> command to open the damper to 100 %, otherwise None.

    The 15 s are counted from the moment the sensor was READ (`read_at`, monotonic),
    not from now: a reading that waited in the queue has already used part of them.
    """
    if co2_ppm <= CO2_THRESHOLD_PPM:
        return None
    return ActuatorCommand(
        event_id=event_id,
        action=RULE["action"],
        value=float(RULE["value"]),
        reason=f"CO2 {co2_ppm:g} ppm > {CO2_THRESHOLD_PPM:g} ppm",
        expires_at=read_at + COMMAND_TTL_S,
    )


def is_expired(expires_at: float, now: float | None = None) -> bool:
    """
    True once the monotonic clock has passed the expiry time.
    time.monotonic() never goes back, and on Linux all processes read the same clock.
    """
    if now is None:
        now = time.monotonic()
    return now > expires_at
