"""OS1-3: the simulated HVAC damper. It applies a command only if it has not expired."""

import os
import time

from edge.os1_3_ventilation import decision
from edge.core import storage
from edge.core.models import ActuatorCommand

APPLIED = "DAMPER_APPLIED"
EXPIRED = "COMMAND_EXPIRED"

# Extra delay before each command, to demonstrate expiry with a slow actuator.
DELAY_S = float(os.environ.get("EDGE_ACTUATOR_DELAY_S", "0"))


def check_command(command: ActuatorCommand, now: float) -> tuple[str, str]:
    """Return (APPLIED or EXPIRED, reason) for a command looked at, at monotonic time `now`."""
    seconds_left = command.expires_at - now
    if decision.is_expired(command.expires_at, now):
        return EXPIRED, f"{command.action} expired {-seconds_left:.1f} s ago, not applied"
    return APPLIED, f"{command.action} = {command.value:g} applied ({seconds_left:.1f} s left)"


def run_actuator(channels, state) -> None:
    state["damper_pct"] = 0
    state["actuator_applied"] = 0
    state["actuator_expired"] = 0

    while not channels.stop.is_set() or channels.commands.size():
        command = channels.commands.get(timeout=0.2)
        if command is None:
            continue
        time.sleep(DELAY_S)

        # Checked with the Actuator's OWN clock, right before acting.
        outcome, reason = check_command(command, time.monotonic())
        storage.save_decision(command.event_id, outcome, reason)

        if outcome == APPLIED:
            state["damper_pct"] = command.value
            state["actuator_applied"] += 1
        else:
            state["actuator_expired"] += 1
