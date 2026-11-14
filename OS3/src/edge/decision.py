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


def make_decision(pedestrian_count: float):
    """
    If there is a pedestrian surge, create a VARIABLE_SPEED_SIGN_KMH command.

    Return (decision, expiry_time), or (None, None) when there is no surge.
    The expiry time uses time.monotonic(), so a wall-clock jump (NTP, manual
    change) can never make a stale command look fresh.
    """
    if not is_pedestrian_surge(pedestrian_count):
        return None, None

    expiry_time = time.monotonic() + COMMAND_TTL
    decision = EdgeDecision(
        action=SIGN_ACTION,
        value=SPEED_LIMIT_SURGE,
        reason=f"Pedestrian surge: {int(pedestrian_count)} >= {SURGE_THRESHOLD}",
        timestamp=time.time(),
    )
    return decision, expiry_time


def is_command_expired(expiry_time: float | None) -> bool:
    """An expired command must be rejected (a missing expiry counts as expired)."""
    if expiry_time is None:
        return True
    return time.monotonic() > expiry_time
