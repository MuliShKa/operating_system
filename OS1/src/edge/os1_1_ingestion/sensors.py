"""SensorGen worker: simulated indoor CO2 (ppm) and room temperature (°C), one reading each per second."""

import random
import time

from edge.core.models import SensorEvent
from edge.node_config import SENSORS


def run_sensors(channels) -> None:
    while not channels.stop.is_set():
        wall_time, read_at = time.time(), time.monotonic()
        for sensor in SENSORS:
            value = round(random.uniform(sensor["min"], sensor["max"]), 1)
            channels.sensor_events.put(SensorEvent(sensor["id"], value, sensor["unit"], wall_time, read_at))
        channels.stop.wait(1)
