"""OS1-3: simulated HVAC damper. Applies a command only if it has not expired."""

from __future__ import annotations

import os
import time
from typing import Any

from edge import decision, storage
from edge.models import ActuatorCommand

APPLIED = "DAMPER_APPLIED"
EXPIRED = "COMMAND_EXPIRED"

# Extra delay before each command, to demonstrate expiry with a slow actuator.
DELAY_S = float(os.environ.get("EDGE_ACTUATOR_DELAY_S", "0"))


def handle_command(command: ActuatorCommand, now: float) -> tuple[str, str]:
    """
    Decide what happens to one command at monotonic time `now`.
    Return (outcome, reason); the outcome is APPLIED or EXPIRED.
    """
    age_over = now - command.expires_at
    if decision.is_command_expired(command.expires_at, now):
        return EXPIRED, f"{command.action} expired {age_over:.1f} s ago, not applied"
    return APPLIED, f"{command.action} = {command.value:g} applied ({-age_over:.1f} s left)"


def run_actuator(channels: Any, state: Any) -> None:
    # The Actuator compares the command expiry with ITS OWN monotonic clock,
    # right before acting: a command that waited too long is rejected.
    state["damper_pct"] = 0
    state["actuator_applied"] = 0
    state["actuator_expired"] = 0

    while not channels.stop.is_set() or channels.commands.size():
        command = channels.commands.get(timeout=0.2)
        if command is None:
            continue

        if DELAY_S:
            time.sleep(DELAY_S)

        outcome, reason = handle_command(command, time.monotonic())
        storage.save_decision(command.event_id, outcome, reason)

        if outcome == APPLIED:
            state["damper_pct"] = command.value
            state["actuator_applied"] = state.get("actuator_applied", 0) + 1
        else:
            state["actuator_expired"] = state.get("actuator_expired", 0) + 1
