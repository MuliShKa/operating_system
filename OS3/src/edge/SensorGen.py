"""SensorGen process: simulated radar speed and crosswalk pedestrian counts.

All values are SIMULATED. Pedestrian surges are injected periodically so the
local rule fires during a demo.
"""

import random
import time

from edge import decision
from edge.models import SensorEvent

# A simulated surge starts every SURGE_EVERY_S seconds and lasts SURGE_DURATION_S.
SURGE_EVERY_S = 30.0
SURGE_DURATION_S = 12.0


def run_sensor_gen(channels):
    """
    Produce one radar reading and one pedestrian count per second.

    Pedestrian counts that reach the surge threshold go to the URGENT lane of
    the priority queue; everything else goes to the NORMAL lane (scenario OS3-2).
    """
    print("[SensorGen] Started: sending SensorEvent objects to the IPC queue.", flush=True)

    now = time.monotonic()
    next_surge_at = now + SURGE_EVERY_S
    surge_until = 0.0

    while not channels.stop.is_set():
        now = time.monotonic()
        if now >= next_surge_at:
            surge_until = now + SURGE_DURATION_S
            next_surge_at = now + SURGE_EVERY_S

        if now < surge_until:
            pedestrians = random.randint(
                decision.SURGE_THRESHOLD, decision.SURGE_THRESHOLD + 15
            )
        else:
            pedestrians = random.randint(0, max(0, decision.SURGE_THRESHOLD - 5))

        speed = round(random.uniform(30.0, 70.0), 1)
        current_time = time.time()
        # Each reading carries its monotonic read time: command TTLs start from it.
        read_at = time.monotonic()

        radar_event = SensorEvent("RADAR_SPEED", speed, "km/h", current_time, read_at)
        pedestrian_event = SensorEvent(
            "PED_CROSSWALK_COUNT", pedestrians, "people", current_time, read_at
        )

        channels.sensor_events.put(radar_event)
        channels.sensor_events.put(
            pedestrian_event, urgent=decision.is_pedestrian_surge(pedestrians)
        )

        # Event.wait() instead of time.sleep(): shutdown is not delayed by 1 s.
        if channels.stop.wait(1.0):
            break

    print("[SensorGen] Stop signal received. Shutting down gracefully.", flush=True)
