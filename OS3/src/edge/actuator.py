"""Simulated variable speed sign (Actuator worker).

The Processor only ISSUES commands. This worker is the only one that changes
the sign. Right before acting it compares the command's expiry with ITS OWN
monotonic clock: a command that waited too long is rejected (scenario OS3-5,
rubric item "actuator command freshness"). The sign change itself is a
version-guarded SQLite update (scenario OS3-4).
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

from edge import decision, storage
from edge.models import ActuatorCommand

APPLIED = "SIGN_APPLIED"
EXPIRED = "SIGN_COMMAND_EXPIRED"
RESTORED = "SIGN_RESTORED"
REFRESHED = "SIGN_REFRESHED"   # sign already at the surge limit: only the deadline moves

MAX_SIGN_UPDATE_TRIES = 3

# Extra delay before each command, to demonstrate expiry with a slow actuator.
DELAY_S = float(os.environ.get("EDGE_ACTUATOR_DELAY_S", "0"))


def set_sign_limit(speed_limit: int):
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


class SignActuator:
    """The sign logic, separated from the worker loop so it can be tested."""

    def __init__(self, state: Any) -> None:
        self.state = state
        self.active_until: float | None = None  # deadline of the newest applied command
        self.state["actuator_applied"] = 0
        self.state["actuator_expired"] = 0

    def start(self) -> None:
        """Fail-safe at startup: begin from the normal limit, not from a stale surge."""
        sign, _ = set_sign_limit(decision.SPEED_LIMIT_NORMAL)
        self._publish(sign)

    def handle(self, command: ActuatorCommand, now: float) -> str:
        """Apply the command if it is still fresh at monotonic time `now`; return the outcome."""
        if decision.is_command_expired(command.expires_at, now):
            late = now - command.expires_at
            reason = f"{command.action} = {command.value:g} expired {late:.1f} s ago, not applied"
            storage.save_decision(command.event_id, EXPIRED, reason, command.value)
            self.state["actuator_expired"] = self.state.get("actuator_expired", 0) + 1
            self._remember(EXPIRED, command.value, reason, None)
            return EXPIRED

        # Several commands can arrive during one surge: keep the latest deadline.
        self.active_until = max(self.active_until or 0.0, command.expires_at)
        sign, changed = set_sign_limit(int(command.value))
        self._publish(sign)
        self.state["actuator_applied"] = self.state.get("actuator_applied", 0) + 1
        if not changed:
            return REFRESHED

        reason = f"{command.action} = {command.value:g} applied ({command.expires_at - now:.1f} s left)"
        storage.save_decision(command.event_id, APPLIED, reason, command.value)
        self._remember(APPLIED, command.value, reason, command.expires_at - now)
        return APPLIED

    def tick(self, now: float) -> bool:
        """Put the sign back to normal when the last applied command is stale. True if it moved."""
        if self.active_until is None or not decision.is_command_expired(self.active_until, now):
            return False
        self.active_until = None
        sign, changed = set_sign_limit(decision.SPEED_LIMIT_NORMAL)
        self._publish(sign)
        if changed:
            reason = "Surge command expired (TTL); sign restored"
            storage.save_decision(None, RESTORED, reason, decision.SPEED_LIMIT_NORMAL)
            self._remember(RESTORED, decision.SPEED_LIMIT_NORMAL, reason, None)
        return changed

    def _publish(self, sign: dict) -> None:
        self.state["sign_state"] = {
            "speed_limit_kmh": sign["speed_limit_kmh"],
            "version": sign["version"],
            "surge_active": sign["speed_limit_kmh"] == decision.SPEED_LIMIT_SURGE,
        }

    def _remember(self, action: str, value: float, reason: str, expires_in: float | None) -> None:
        # Own key (not "recent_decisions"): the Processor writes that one, and two
        # processes doing read-modify-write on the same key would lose entries.
        entries = list(self.state.get("recent_actuations", []))
        entries.append({
            "action": action,
            "value": value,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "expires_in_seconds": None if expires_in is None else round(expires_in, 1),
        })
        self.state["recent_actuations"] = entries[-20:]


def run_actuator(channels: Any, state: Any) -> None:
    actuator = SignActuator(state)
    actuator.start()

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
