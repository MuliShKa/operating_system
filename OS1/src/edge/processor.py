"""Connect sensor readings to local decisions, durable storage and the actuator."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from edge import decision, storage
from edge.models import ActuatorCommand


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def run_processor(channels: Any, state: Any) -> None:
    # Persist each reading, apply the CO2 rule and hand the command to the Actuator.
    while not channels.stop.is_set() or channels.sensor_events.size():
        event = channels.sensor_events.get(timeout=0.2)
        if event is None:
            continue

        event_id = str(uuid.uuid4())
        event_time = _iso(event.timestamp)
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

        if event.sensor_id != decision.CO2_SENSOR:
            continue

        edge_decision, expires_at = decision.make_decision(event.value, event.monotonic)
        if edge_decision is None:
            continue

        # Record that the command was issued, then let the Actuator decide
        # whether it is still fresh enough to apply.
        storage.save_decision(event_id, edge_decision.action, edge_decision.reason)
        channels.commands.put(ActuatorCommand(
            event_id=event_id,
            action=edge_decision.action,
            value=edge_decision.value,
            reason=edge_decision.reason,
            expires_at=expires_at,
        ))

        decisions = list(state.get("recent_decisions", []))
        decisions.append({
            "action": edge_decision.action,
            "value": edge_decision.value,
            "reason": edge_decision.reason,
            "timestamp": _iso(edge_decision.timestamp),
            "expires_in_seconds": max(0, round(expires_at - time.monotonic(), 1)),
        })
        state["recent_decisions"] = decisions[-20:]
