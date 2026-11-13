import random
import time

from edge.models import SensorEvent
from edge.node_config import SENSORS


def run_sensor_gen(channels):
    """
    SensorGen process: simulated indoor CO2 (ppm) and room temperature (°C).
    Receives the 'channels' (IpcChannels) object from the Supervisor process.
    """
    print("[SensorGen] Started: sending SensorEvent objects to the IPC queue", flush=True)

    # Keep running until the supervisor sends the stop signal
    while not channels.stop.is_set():
        wall_time = time.time()
        observed = time.monotonic()

        for sensor in SENSORS:
            event = SensorEvent(
                sensor_id=sensor["id"],
                value=round(random.uniform(sensor["min"], sensor["max"]), 1),
                unit=sensor["unit"],
                timestamp=wall_time,
                monotonic=observed,
            )
            channels.sensor_events.put(event)

        if channels.stop.wait(1):
            break

    print("[SensorGen] Stop signal received. Shutting down gracefully.", flush=True)
