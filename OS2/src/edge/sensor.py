"""Generate simulated LiDAR and IMU readings for the OS2 robot node."""

import random
from collections.abc import Callable
from math import isfinite
from multiprocessing.synchronize import Event
from time import monotonic

from edge.bounded_queue import BoundedSensorQueue
from edge.models import SensorReading


def make_simulated_readings(
    rng: random.Random,
    observed_at: float,
) -> tuple[SensorReading, SensorReading]:
    """Create one LiDAR distance sample and one IMU yaw-rate sample."""
    if not isfinite(observed_at):
        raise ValueError("observed_at must be finite")

    # Keep values inside plausible teaching-demo ranges, including close obstacles.
    proximity_m = round(rng.uniform(0.2, 3.0), 2)
    yaw_rate = round(rng.uniform(-1.5, 1.5), 3)
    return (
        SensorReading("LIDAR_PROXIMITY_M", proximity_m, "m", observed_at),
        SensorReading("IMU_YAW_RATE", yaw_rate, "rad/s", observed_at),
    )


def run_sensor_generator(
    sensor_queue: BoundedSensorQueue,
    stop_event: Event,
    interval_s: float = 0.05,
    seed: int | None = None,
    clock: Callable[[], float] = monotonic,
) -> None:
    """Publish simulated sensor readings until the shared stop event is set."""
    if not isfinite(interval_s) or interval_s <= 0:
        raise ValueError("interval_s must be finite and positive")

    # A local random generator makes tests repeatable when a seed is supplied.
    rng = random.Random(seed)
    while not stop_event.is_set():
        observed_at = clock()
        for reading in make_simulated_readings(rng, observed_at):
            sensor_queue.put(reading)

        # Event.wait can end early when the supervisor requests shutdown.
        stop_event.wait(interval_s)
