"""Connect sensor readings to local decisions and durable storage."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from edge import decision, storage


def run_processor(channels: Any, state: Any) -> None:
    # Drain queued readings even after shutdown is requested, so events already
    # produced by SensorGen are not discarded while the node is stopping.
    while not channels.stop.is_set() or channels.sensor_events.size():
        event = channels.sensor_events.get(timeout=0.2)
        if event is None:
            continue

        # Give every stored event a unique key and normalize its timestamp to UTC.
        event_id = str(uuid.uuid4())
        event_time = datetime.fromtimestamp(event.timestamp, timezone.utc).isoformat()
        payload = {
            "sensor_id": event.sensor_id,
            "value": event.value,
            "unit": event.unit,
        }
        storage.save_event(event_id, event.sensor_id, event_time, payload)
        state["pending_events"] = storage.get_pending_event_count()

        # Keep only the latest 20 readings in shared state for the dashboard.
        readings = list(state.get("recent_readings", []))
        readings.append({**payload, "timestamp": event_time})
        state["recent_readings"] = readings[-20:]

        # The current edge rule applies to water level only, not mains voltage.
        if event.sensor_id != "SLUICE_WATER_LEVEL_M":
            continue

        # Ignore missing or expired commands so stale decisions are not stored
        # or presented as actionable results.
        edge_decision, expires_at = decision.make_decision(event.value)
        if edge_decision is None or decision.is_command_expired(expires_at):
            continue

        storage.save_decision(event_id, edge_decision.action, edge_decision.reason)
        # Store a short recent-decision history and show its remaining lifetime.
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
