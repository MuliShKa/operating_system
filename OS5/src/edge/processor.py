"""Connect sensor readings to local decisions and durable storage."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from edge import decision, storage


def run_processor(channels: Any, state: Any) -> None:
    # Demo integration: persist each reading and apply the water-level rule.
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

        if event.sensor_id != "SLUICE_WATER_LEVEL_M":
            continue

        edge_decision, expires_at = decision.make_decision(event.value)
        if edge_decision is None or decision.is_command_expired(expires_at):
            continue

        storage.save_decision(event_id, edge_decision.action, edge_decision.reason)
        decisions = list(state.get("recent_decisions", []))
        decisions.append({
            "action": edge_decision.action,
            "value": edge_decision.value,
            "reason": edge_decision.reason,
            "timestamp": datetime.fromtimestamp(
                edge_decision.timestamp, timezone.utc
            ).isoformat(),
            "expires_in_seconds": max(0, round(expires_at - time.monotonic(), 1)),
        })
        state["recent_decisions"] = decisions[-20:]
