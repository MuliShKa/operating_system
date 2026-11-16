"""Local rules for the mist cannon. They run entirely on the edge node, no cloud call.

OS4-3: PM2.5 above the "Bad" threshold -> MIST_CANNON_RELAY, valid for 30 s.
OS4-7 (extra): at night, on a quiet street, an ordinary "Bad" reading does NOT
start the loud pump; only a "Very Bad" reading does (emergency override).

Thresholds come from config/node.yaml (the handbook fixes 50 ug/m3 and 30 s;
the rest are team decisions).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from edge.config import load_config

_CONFIG = load_config()

BAD_THRESHOLD = float(_CONFIG["pm25_bad_threshold"])
VERY_BAD_THRESHOLD = float(_CONFIG["pm25_very_bad_threshold"])
COMMAND_TTL = float(_CONFIG["mist_command_ttl_seconds"])
NIGHT_LUX = float(_CONFIG["quiet_night_lux"])
QUIET_DB = float(_CONFIG["quiet_night_noise_db"])

MIST_ACTION = "MIST_CANNON_RELAY"

NONE = "NONE"          # below the threshold: nothing to do
DISPATCH = "DISPATCH"  # send the command to the Actuator
HOLD = "HOLD"          # above the threshold but policy says: do not spray now


@dataclass(frozen=True)
class Verdict:
    kind: str
    reason: str
    expires_at: float | None = None   # monotonic deadline, only for DISPATCH


def is_quiet_night(lux: float | None, noise_db: float | None) -> bool:
    """Dark AND quiet. If either context reading is unknown we do not block the action."""
    if lux is None or noise_db is None:
        return False
    return lux < NIGHT_LUX and noise_db < QUIET_DB


def evaluate_mist(
    pm25: float,
    observed_mono: float,
    lux: float | None = None,
    noise_db: float | None = None,
) -> Verdict:
    """
    Decide what to do with one PM2.5 reading.

    The expiry is counted from the moment the SENSOR measured, not from now:
    a reading that travelled for 8 s has already used 8 s of its 30 s of life.
    It is a time.monotonic() value, so a wall-clock jump (NTP, manual change)
    can never make a stale command look fresh. The Actuator checks it right
    before acting. Because the relay only stays ON while fresh readings keep
    renewing the command, a dead sensor or a crashed Processor switches the
    pump OFF by itself after at most 30 s (a dead-man switch).
    """
    if pm25 <= BAD_THRESHOLD:
        return Verdict(NONE, f"PM2.5 {pm25:g} <= {BAD_THRESHOLD:g}")

    quiet = is_quiet_night(lux, noise_db)
    if quiet and pm25 <= VERY_BAD_THRESHOLD:
        return Verdict(
            HOLD,
            f"Quiet night (lux {lux:g} < {NIGHT_LUX:g}, noise {noise_db:g} dB < {QUIET_DB:g}): "
            f"PM2.5 {pm25:g} is Bad but not Very Bad (> {VERY_BAD_THRESHOLD:g}), pump held off",
        )

    reason = f"PM2.5 {pm25:g} > {BAD_THRESHOLD:g}"
    if quiet:
        reason += f"; quiet-night override: Very Bad (> {VERY_BAD_THRESHOLD:g})"
    return Verdict(DISPATCH, reason, observed_mono + COMMAND_TTL)


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
