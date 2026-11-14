"""Connect sensor readings to local decisions, the sign state and durable storage."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from edge import decision, storage

PED_SENSOR = "PED_CROSSWALK_COUNT"
MAX_SIGN_UPDATE_TRIES = 3


def _set_sign_limit(speed_limit: int):
    """
    Change the sign with a version-guarded update (scenario OS3-4).

    Returns (sign_state, changed). If another writer wins the race, re-read the
    state and try again, up to MAX_SIGN_UPDATE_TRIES times.
    """
    for _ in range(MAX_SIGN_UPDATE_TRIES):
        current = storage.get_sign_state()
        if current["speed_limit_kmh"] == speed_limit:
            return current, False
        if storage.update_sign_state(speed_limit, current["version"]):
            return storage.get_sign_state(), True
    return storage.get_sign_state(), False


def _publish_sign(state: Any, sign: dict) -> None:
    state["sign_state"] = {
        "speed_limit_kmh": sign["speed_limit_kmh"],
        "version": sign["version"],
        "surge_active": sign["speed_limit_kmh"] == decision.SPEED_LIMIT_SURGE,
    }


def _remember_decision(state: Any, entry: dict) -> None:
    decisions = list(state.get("recent_decisions", []))
    decisions.append(entry)
    state["recent_decisions"] = decisions[-20:]


def _restore_sign_if_expired(state: Any, expires_at: float | None) -> float | None:
    """When the surge command is stale, put the sign back to its normal limit."""
    if expires_at is None or not decision.is_command_expired(expires_at):
        return expires_at

    sign, changed = _set_sign_limit(decision.SPEED_LIMIT_NORMAL)
    _publish_sign(state, sign)
    if changed:
        reason = "Surge command expired (TTL); sign restored"
        storage.save_decision(
            None, decision.SIGN_ACTION, reason, decision.SPEED_LIMIT_NORMAL
        )
        _remember_decision(state, {
            "action": decision.SIGN_ACTION,
            "value": decision.SPEED_LIMIT_NORMAL,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "expires_in_seconds": None,
        })
    return None


def run_processor(channels: Any, state: Any) -> None:
    # Fail-safe at startup: begin from the normal limit, not from a stale surge.
    sign, _ = _set_sign_limit(decision.SPEED_LIMIT_NORMAL)
    _publish_sign(state, sign)
    sign_expires_at = None

    # Keep running until stop is requested AND the queue is drained.
    while not channels.stop.is_set() or channels.sensor_events.size():
        event = channels.sensor_events.get(timeout=0.2)
        sign_expires_at = _restore_sign_if_expired(state, sign_expires_at)
        if event is None:
            continue

        event_id = str(uuid.uuid4())
        event_time = datetime.fromtimestamp(event.timestamp, timezone.utc).isoformat()
        payload = {
            "sensor_id": event.sensor_id,
            "value": event.value,
            "unit": event.unit,
        }
        storage.save_event(event_id, event.sensor_id, event_time, payload)
        state["pending_events"] = storage.get_pending_event_count()

        readings = list(state.get("recent_readings", []))
        readings.append({**payload, "timestamp": event_time})
        state["recent_readings"] = readings[-20:]

        if event.sensor_id != PED_SENSOR:
            continue

        edge_decision, expires_at = decision.make_decision(event.value)
        if edge_decision is None or decision.is_command_expired(expires_at):
            continue

        # A new surge reading always refreshes the command lifetime.
        sign_expires_at = expires_at

        sign, changed = _set_sign_limit(int(edge_decision.value))
        _publish_sign(state, sign)
        if not changed:
            continue  # sign already at the surge limit: nothing new to record

        storage.save_decision(
            event_id, edge_decision.action, edge_decision.reason, edge_decision.value
        )
        _remember_decision(state, {
            "action": edge_decision.action,
            "value": edge_decision.value,
            "reason": edge_decision.reason,
            "timestamp": datetime.fromtimestamp(
                edge_decision.timestamp, timezone.utc
            ).isoformat(),
            "expires_in_seconds": max(0, round(expires_at - time.monotonic(), 1)),
        })
