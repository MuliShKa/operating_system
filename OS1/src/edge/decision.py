"""OS1-3: local ventilation rule and command expiry (TTL)."""

import time

from edge.models import EdgeDecision
from edge.node_config import RULE

CO2_SENSOR = RULE["sensor"]
CO2_THRESHOLD_PPM = float(RULE["above"])
DAMPER_ACTION = RULE["action"]
DAMPER_PCT = float(RULE["value"])
COMMAND_TTL_S = float(RULE["ttl_s"])


def make_decision(co2_ppm: float, observed_monotonic: float):
    """
    If CO2 is above 1000 ppm, return a command to open the damper to 100 %.

    The expiry is counted from the moment the sensor was read, not from now:
    a reading that waited in the queue already used part of its 15 s.
    Return (decision, expires_at) or (None, None) when no action is needed.
    """
    if co2_ppm <= CO2_THRESHOLD_PPM:
        return None, None

    decision = EdgeDecision(
        action=DAMPER_ACTION,
        value=DAMPER_PCT,
        reason=f"CO2 {co2_ppm:g} ppm > {CO2_THRESHOLD_PPM:g} ppm",
        timestamp=time.time(),
    )
    return decision, observed_monotonic + COMMAND_TTL_S


def is_command_expired(expires_at: float, now: float | None = None) -> bool:
    """
    A command is expired once the monotonic clock has passed its expiry time.

    time.monotonic() never goes back, even if the wall clock is changed,
    and on Linux every process of the machine reads the same clock.
    """
    if expires_at is None:
        return True
    if now is None:
        now = time.monotonic()
    return now > expires_at
