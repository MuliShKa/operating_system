"""Local water-level decision rules and command expiry."""

from __future__ import annotations

import math
import time
from pathlib import Path

import yaml

from edge.models import EdgeDecision

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "node.yaml"
COMMAND_TTL = 10.0


def _finite_nonnegative_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number.")

    try:
        number = float(value)
    except OverflowError as error:
        raise ValueError(f"{name} must be finite.") from error

    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite.")
    if number < 0:
        raise ValueError(f"{name} must be at least 0.")
    return number


def load_water_threshold(config_path: Path = CONFIG_PATH) -> float:
    """Load and validate the water-level threshold from node.yaml."""
    with config_path.open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)

    if not isinstance(config, dict) or "threshold" not in config:
        raise ValueError(f"Missing water-level threshold in {config_path}.")
    return _finite_nonnegative_number(config["threshold"], "threshold")


WATER_THRESHOLD = load_water_threshold()


def validate_water_level(water_level: object) -> float:
    """Return a finite, nonnegative water-level reading or reject it."""
    return _finite_nonnegative_number(water_level, "water level")


def make_decision(water_level: object) -> tuple[EdgeDecision | None, float | None]:
    """Create a gate-open decision only when the reading exceeds the threshold."""
    level = validate_water_level(water_level)
    if level <= WATER_THRESHOLD:
        return None, None

    expiry_time = time.monotonic() + COMMAND_TTL
    decision = EdgeDecision(
        action="BACKUP_SLUICE_GATE_OPEN",
        value=level,
        reason=f"Water level {level}m exceeds {WATER_THRESHOLD}m threshold.",
        timestamp=time.time(),
    )
    return decision, expiry_time


def is_command_expired(expiry_time: float | None) -> bool:
    """Reject missing, invalid, or elapsed monotonic command deadlines."""
    if (
        isinstance(expiry_time, bool)
        or not isinstance(expiry_time, (int, float))
    ):
        return True
    try:
        if not math.isfinite(expiry_time):
            return True
    except OverflowError:
        return True
    return time.monotonic() >= expiry_time
