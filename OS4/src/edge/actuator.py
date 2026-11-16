"""Simulated mist cannon relay (Actuator worker).

The Processor only ISSUES commands. This worker is the only one that changes the
relay. Right before acting it compares the command's expiry with ITS OWN
monotonic clock: a command that waited too long is rejected (scenario OS4-3,
rubric item "actuator command freshness").

The relay stays ON only while fresh commands keep renewing it. When the last
command expires the Actuator switches it OFF by itself: if the sensor dies, the
Processor crashes or the machine hangs, the pump stops within 30 s (dead-man
switch). A real installation would ALSO need a hardware timer on the relay;
this software guard does not replace one.

A relay left ON in the database by a previous run is NOT trusted: the Actuator
starts from OFF (fail-safe), like the stale commands it refuses.
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from edge import decision, storage
from edge.models import ActuatorCommand

APPLIED = "MIST_RELAY_ON"
EXPIRED = "MIST_COMMAND_EXPIRED"
RESTORED = "MIST_RELAY_OFF"

MAX_RELAY_UPDATE_TRIES = 3

# Extra delay before each command, to demonstrate expiry with a slow actuator.
DELAY_S = float(os.environ.get("EDGE_ACTUATOR_DELAY_S", "0"))


def set_relay(wanted: str):
    """
    Change the relay with a version-guarded update (compare-and-swap).

    Returns (relay_row, changed). If another writer wins the race, re-read the
    state and try again, up to MAX_RELAY_UPDATE_TRIES times.
    """
    for _ in range(MAX_RELAY_UPDATE_TRIES):
        current = storage.get_relay_state()
        if current["state"] == wanted:
            return current, False
        if storage.update_relay_state(wanted, current["version"]):
            return storage.get_relay_state(), True
    return storage.get_relay_state(), False


class MistActuator:
    """The relay logic, separated from the worker loop so it can be tested."""

    def __init__(self, state: Any) -> None:
        self.state = state
        self.active_until: float | None = None  # deadline of the newest applied command
        self.state["actuator_applied"] = 0
        self.state["actuator_expired"] = 0

    def start(self) -> None:
        """Fail-safe at startup: begin from OFF, not from whatever a crashed run left."""
        relay, _ = set_relay("OFF")
        self._publish(relay)

    def handle(self, command: ActuatorCommand, now: float) -> str:
        """Apply the command if it is still fresh at monotonic time `now`; return the outcome."""
        if decision.is_command_expired(command.expires_at, now):
            late = now - command.expires_at
            reason = f"{command.action} expired {late:.1f} s ago, not applied"
            storage.save_decision(command.event_id, EXPIRED, reason, 0.0)
            self.state["actuator_expired"] = self.state.get("actuator_expired", 0) + 1
            self._remember(EXPIRED, 0.0, reason, None)
            return EXPIRED

        # Several commands arrive during one episode: keep the latest deadline.
        self.active_until = max(self.active_until or 0.0, command.expires_at)
        relay, changed = set_relay("ON")
        self._publish(relay)
        self.state["actuator_applied"] = self.state.get("actuator_applied", 0) + 1
        if not changed:
            return "MIST_REFRESHED"     # already ON: only the deadline moved

        left = command.expires_at - now
        reason = f"{command.action} ON ({left:.1f} s left). {command.reason}"
        storage.save_decision(command.event_id, APPLIED, reason, 1.0)
        self._announce("ON", reason, left)
        self._remember(APPLIED, 1.0, reason, left)
        return APPLIED

    def tick(self, now: float) -> bool:
        """Switch the relay OFF when the last applied command is stale. True if it moved."""
        if self.active_until is None or not decision.is_command_expired(self.active_until, now):
            return False
        self.active_until = None
        return self._switch_off("Command expired (TTL): relay switched OFF")

    def shutdown(self) -> None:
        """Clean stop: never leave the pump ON behind us."""
        self.active_until = None
        self._switch_off("Node stopping: relay switched OFF")

    def _switch_off(self, reason: str) -> bool:
        relay, changed = set_relay("OFF")
        self._publish(relay)
        if changed:
            storage.save_decision(None, RESTORED, reason, 0.0)
            self._announce("OFF", reason, None)
            self._remember(RESTORED, 0.0, reason, None)
        return changed

    def _announce(self, relay_state: str, reason: str, ttl_left: float | None) -> None:
        """Every relay switch is also an EVENT, so the Urban Data Platform sees the actuation."""
        stamp = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        payload = {"sensor_id": decision.MIST_ACTION, "value": 1.0 if relay_state == "ON" else 0.0,
                   "unit": "relay", "state": relay_state, "reason": reason,
                   "ttl_left_s": None if ttl_left is None else round(ttl_left, 1),
                   "observed_at": stamp, "received_at": stamp}
        storage.save_event(str(uuid.uuid4()), decision.MIST_ACTION, stamp, stamp, payload)

    def _publish(self, relay: dict) -> None:
        self.state["relay_state"] = {"state": relay["state"], "version": relay["version"]}

    def _remember(self, action: str, value: float, reason: str, expires_in: float | None) -> None:
        # Own key (not "recent_decisions"): the Processor writes that one, and two
        # processes doing read-modify-write on the same key would lose entries.
        entries = list(self.state.get("recent_actuations", []))
        entries.append({
            "action": action,
            "value": value,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            "expires_in_seconds": None if expires_in is None else round(expires_in, 1),
        })
        self.state["recent_actuations"] = entries[-20:]


def run_actuator(channels: Any, state: Any) -> None:
    actuator = MistActuator(state)
    actuator.start()
    try:
        while not channels.stop.is_set() or channels.commands.size():
            command = channels.commands.get(timeout=0.2)
            if command is None:
                actuator.tick(time.monotonic())
                continue

            if DELAY_S:
                time.sleep(DELAY_S)

            # The freshness check uses THIS process's monotonic clock, right before acting.
            actuator.handle(command, time.monotonic())
            actuator.tick(time.monotonic())
    finally:
        actuator.shutdown()
