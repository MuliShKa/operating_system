"""Local rule: pedestrian surge -> variable speed sign limited to 30 km/h.

The rule runs entirely on the edge node, with no cloud call. Thresholds come
from config/node.yaml (team decisions, not defined by the handbook).
"""

import time

from edge.config import load_config
from edge.models import EdgeDecision

_CONFIG = load_config()

SURGE_THRESHOLD = int(_CONFIG["pedestrian_surge_threshold"])
SPEED_LIMIT_NORMAL = int(_CONFIG["speed_limit_normal_kmh"])
SPEED_LIMIT_SURGE = int(_CONFIG["speed_limit_surge_kmh"])
COMMAND_TTL = float(_CONFIG["command_ttl_seconds"])

SIGN_ACTION = "VARIABLE_SPEED_SIGN_KMH"


def is_pedestrian_surge(pedestrian_count: float) -> bool:
    """Return True when the crosswalk count reaches the surge threshold."""
    return pedestrian_count >= SURGE_THRESHOLD


def make_decision(pedestrian_count: float, observed_monotonic: float):
    """
    If there is a pedestrian surge, create a VARIABLE_SPEED_SIGN_KMH command.

    Return (decision, expires_at), or (None, None) when there is no surge.

    The expiry is counted from the moment the SENSOR was read, not from now:
    a reading that waited in a queue has already used part of its lifetime.
    It uses time.monotonic(), so a wall-clock jump (NTP, manual change) can
    never make a stale command look fresh. The Actuator is the one that checks
    the expiry, right before it moves the sign.
    """
    if not is_pedestrian_surge(pedestrian_count):
        return None, None

    decision = EdgeDecision(
        action=SIGN_ACTION,
        value=SPEED_LIMIT_SURGE,
        reason=f"Pedestrian surge: {int(pedestrian_count)} >= {SURGE_THRESHOLD}",
        timestamp=time.time(),
    )
    return decision, observed_monotonic + COMMAND_TTL


def is_command_expired(expires_at: float | None, now: float | None = None) -> bool:
    """
    A command is expired once the monotonic clock has passed its expiry time.
    A missing expiry counts as expired.

    time.monotonic() never goes back, and on Linux every process of the
    machine reads the same clock, so the Actuator can compare against an
    expiry computed by the Processor.
    """
    if expires_at is None:
        return True
    if now is None:
        now = time.monotonic()
    return now > expires_at
