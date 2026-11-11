import time
from edge.models import EdgeDecision

# Threshold defined in node.yaml
WATER_THRESHOLD = 2.8
# TTL
COMMAND_TTL = 10.0

def make_decision(water_level: float):
    """
    If the water is above 2.8 m, create BACKUP_SLUICE_GATE_OPEN command.
    """
    if water_level > WATER_THRESHOLD:
        print(f"[Decision] WARNING: Water level at {water_level}m (exceeds {WATER_THRESHOLD}m threshold).")
        
        # Expiry time (TTL) measured by time.monotonic()
        expiry_time = time.monotonic() + COMMAND_TTL
        
        # Issue the command to open the backup gate
        decision = EdgeDecision(
            action="BACKUP_SLUICE_GATE_OPEN",
            value=water_level,
            reason="Water level > 2.8m",
            timestamp=time.time()
        )
        
        print(f"[Decision] Command issued: {decision.action}. Expires in {COMMAND_TTL}s.")
        return decision, expiry_time
        
    return None, None

def is_command_expired(expiry_time: float) -> bool:
    """
    An expired command is rejected
    """
    if expiry_time is None:
        return True
        
    # Check if current monotonic time has passed the expiry time
    if time.monotonic() > expiry_time:
        print("[Decision] Command expired (TTL exceeded) and rejected.")
        return True
        
    return False