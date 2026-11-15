"""Store each reading, apply the CO2 rule and send the command to the Actuator."""

import time
import uuid
from datetime import datetime, timezone

from edge.os1_3_ventilation import decision
from edge.core import storage


def iso_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def keep_last_20(state, key: str, item: dict) -> None:
    """Append to a list in the shared state, keeping the 20 newest items (for the dashboard)."""
    state[key] = (list(state.get(key, [])) + [item])[-20:]


def run_processor(channels, state) -> None:
    # OS1-1: every reading is tagged with the building the node is in.
    building_id = ((state.get("building") or {}).get("node_building") or {}).get("building_id")

    # After the stop flag, finish what is still in the queue.
    while not channels.stop.is_set() or channels.sensor_events.size():
        event = channels.sensor_events.get(timeout=0.2)
        if event is None:
            continue

        event_id = str(uuid.uuid4())
        payload = {"sensor_id": event.sensor_id, "value": event.value, "unit": event.unit, "building_id": building_id}
        storage.save_event(event_id, event.sensor_id, iso_time(event.timestamp), payload)
        state["pending_events"] = storage.count_pending_events()
        keep_last_20(state, "recent_readings", {**payload, "timestamp": iso_time(event.timestamp)})

        if event.sensor_id != decision.CO2_SENSOR:
            continue
        command = decision.make_command(event_id, event.value, event.monotonic)
        if command is None:
            continue

        # Record that the command was issued; the Actuator decides if it is still fresh.
        storage.save_decision(event_id, command.action, command.reason)
        channels.commands.put(command)
        keep_last_20(state, "recent_decisions", {
            "action": command.action,
            "value": command.value,
            "reason": command.reason,
            "timestamp": iso_time(time.time()),
            "expires_in_seconds": max(0, round(command.expires_at - time.monotonic(), 1)),
        })
