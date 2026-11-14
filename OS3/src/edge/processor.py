"""Connect sensor readings to local decisions and durable storage.

The Processor stores every reading, applies the local rule and ISSUES speed
sign commands. It never moves the sign itself: the Actuator worker does that,
after checking that the command is still fresh.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from edge import bis_loader, decision, storage
from edge.config import PROJECT_DIR, load_config
from edge.models import ActuatorCommand

PED_SENSOR = "PED_CROSSWALK_COUNT"


def _load_bus_context() -> bis_loader.BusContext:
    """OS3-1: read the cached bus stop file from local disk (works offline)."""
    config = load_config()
    return bis_loader.build_context(
        latitude=float(config["latitude"]),
        longitude=float(config["longitude"]),
        radius_m=float(config["bis_radius_m"]),
        primary_csv=PROJECT_DIR / str(config["bis_stops_csv"]),
        fallback_csv=PROJECT_DIR / str(config["bis_sample_csv"]),
    )


def run_processor(channels: Any, state: Any) -> None:
    # OS3-1: bus stop context, loaded once at startup from the local cache.
    bus_context = _load_bus_context()
    state["bus_context"] = bus_context.to_dict()
    bus_note = bus_context.describe()

    # Deadline of the last command this process issued; used only to tell a NEW
    # surge (record a decision) from a refresh of the surge already running.
    last_command_expires_at = None

    # Keep running until stop is requested AND the queue is drained.
    while not channels.stop.is_set() or channels.sensor_events.size():
        event = channels.sensor_events.get(timeout=0.2)
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

        # The TTL starts when the SENSOR was read, not now.
        observed = event.monotonic or time.monotonic()
        edge_decision, expires_at = decision.make_decision(event.value, observed)
        if edge_decision is None:
            continue

        # Hand the command to the Actuator, which checks freshness before acting.
        channels.commands.put(ActuatorCommand(
            event_id=event_id,
            action=edge_decision.action,
            value=edge_decision.value,
            expires_at=expires_at,
            reason=edge_decision.reason,
        ))

        new_surge = decision.is_command_expired(last_command_expires_at)
        last_command_expires_at = max(last_command_expires_at or 0.0, expires_at)
        if not new_surge:
            continue

        # Correlate the surge with the bus stop context (OS3-1).
        reason = f"{edge_decision.reason}; {bus_note}" if bus_note else edge_decision.reason
        storage.save_decision(event_id, edge_decision.action, reason, edge_decision.value)
        decisions = list(state.get("recent_decisions", []))
        decisions.append({
            "action": edge_decision.action,
            "value": edge_decision.value,
            "reason": reason,
            "timestamp": datetime.fromtimestamp(
                edge_decision.timestamp, timezone.utc
            ).isoformat(),
            "expires_in_seconds": max(0, round(expires_at - time.monotonic(), 1)),
        })
        state["recent_decisions"] = decisions[-20:]
