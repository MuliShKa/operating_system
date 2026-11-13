"""Local robot safety decisions and control-loop timing measurements.

This module contains pure control decisions and a scheduler helper. It does
not connect to real motors or sensors; a later process layer will provide I/O.
"""

from collections.abc import Callable
from itertools import count
from math import isfinite
from threading import Event
from time import monotonic

from edge.bounded_queue import BoundedSensorQueue
from edge.models import ActuatorCommand, SensorReading


class JitterMonitor:
    """Measure how far each observed control interval is from its target."""

    def __init__(self, target_period_s: float = 0.05) -> None:
        """Set a positive target period in seconds, such as 0.05 for 50 ms."""
        if not isfinite(target_period_s) or target_period_s <= 0:
            raise ValueError("target_period_s must be finite and positive")
        self.target_period_s = target_period_s
        self._previous_tick: float | None = None

    def record_tick(self, tick_time: float) -> float | None:
        """Record a monotonic tick and return its absolute timing error."""
        if not isfinite(tick_time):
            raise ValueError("tick_time must be finite")
        if self._previous_tick is None:
            # The first tick has no previous interval, so it has no jitter value.
            self._previous_tick = tick_time
            return None
        if tick_time <= self._previous_tick:
            raise ValueError("tick times must increase monotonically")

        actual_period = tick_time - self._previous_tick
        self._previous_tick = tick_time
        return abs(actual_period - self.target_period_s)


def run_periodic_control_loop(
    stop_event: Event,
    on_tick: Callable[[float, float | None], None],
    period_s: float = 0.05,
    clock: Callable[[], float] = monotonic,
) -> None:
    """Call on_tick on monotonic deadlines until stop_event is set.

    If a tick runs late, missed deadlines are skipped instead of running many
    immediate catch-up ticks. The callback receives the actual time and jitter.
    """
    if not isfinite(period_s) or period_s <= 0:
        raise ValueError("period_s must be finite and positive")

    jitter_monitor = JitterMonitor(period_s)
    next_deadline = clock()
    while not stop_event.is_set():
        now = clock()
        delay = next_deadline - now
        if delay > 0:
            # Event.wait can wake early when shutdown is requested.
            stop_event.wait(delay)
            continue

        jitter = jitter_monitor.record_tick(now)
        on_tick(now, jitter)

        next_deadline += period_s
        if next_deadline <= now:
            # Skip missed periods so one slow callback cannot cause a busy loop.
            missed_periods = int((now - next_deadline) // period_s) + 1
            next_deadline += missed_periods * period_s


def evaluate_pending_sensor_readings(
    sensor_queue: BoundedSensorQueue,
    controller: "RobotSafetyController",
    now_monotonic: float,
    first_read_timeout_s: float = 0.01,
    drain_timeout_s: float = 0.001,
) -> tuple[ActuatorCommand, ...]:
    """Apply queued LiDAR samples and return the latest safety commands.

    The first read may wait briefly for a sensor sample. Later reads drain the
    current batch, so a close obstacle cannot be hidden by a newer sample that
    arrives before the controller examines the queue.
    """
    if not isfinite(now_monotonic):
        raise ValueError("now_monotonic must be finite")
    if not isfinite(first_read_timeout_s) or first_read_timeout_s < 0:
        raise ValueError("first_read_timeout_s must be finite and non-negative")
    if not isfinite(drain_timeout_s) or drain_timeout_s < 0:
        raise ValueError("drain_timeout_s must be finite and non-negative")

    latest_commands: tuple[ActuatorCommand, ...] = ()
    reading = sensor_queue.get(timeout=first_read_timeout_s)
    while reading is not None:
        if reading.sensor_id == "LIDAR_PROXIMITY_M":
            latest_commands = controller.evaluate_proximity(reading, now_monotonic)
        reading = sensor_queue.get(timeout=drain_timeout_s)
    return latest_commands


class RobotSafetyController:
    """Latch an emergency stop when LiDAR reports an unsafe distance."""

    def __init__(
        self,
        obstacle_threshold_m: float = 0.8,
        command_ttl_s: float = 0.5,
        estop_latched: bool = False,
    ) -> None:
        """Set the obstacle threshold and validity period for issued commands.

        estop_latched restores a latch saved before a process restart.
        """
        if not isfinite(obstacle_threshold_m) or obstacle_threshold_m <= 0:
            raise ValueError("obstacle_threshold_m must be finite and positive")
        if not isfinite(command_ttl_s) or command_ttl_s <= 0:
            raise ValueError("command_ttl_s must be finite and positive")

        self.obstacle_threshold_m = obstacle_threshold_m
        self.command_ttl_s = command_ttl_s
        self._estop_latched = estop_latched
        self._command_ids = count(1)

    @property
    def estop_latched(self) -> bool:
        """Return whether this controller has entered its emergency-stop state."""
        return self._estop_latched

    def evaluate_proximity(
        self,
        reading: SensorReading,
        now_monotonic: float,
    ) -> tuple[ActuatorCommand, ...]:
        """Issue stop commands below threshold and keep them latched afterward."""
        if reading.sensor_id != "LIDAR_PROXIMITY_M":
            raise ValueError("reading must come from LIDAR_PROXIMITY_M")
        if not isfinite(now_monotonic):
            raise ValueError("now_monotonic must be finite")

        # Equality is safe here; only a strictly smaller distance trips the latch.
        if reading.value < self.obstacle_threshold_m:
            self._estop_latched = True

        if not self._estop_latched:
            return ()

        # Use the caller's monotonic clock for both issue and expiry times.
        expires_at = now_monotonic + self.command_ttl_s
        return (
            self._new_command("SAFETY_ESTOP_LATCH", True, now_monotonic, expires_at),
            self._new_command("MOTOR_VEL", 0.0, now_monotonic, expires_at),
        )

    def accepts(self, command: ActuatorCommand, now_monotonic: float) -> bool:
        """Reject expired commands and movement that conflicts with a latched stop."""
        if command.is_expired(now_monotonic):
            return False
        if command.actuator == "SAFETY_ESTOP_LATCH" and command.value is True:
            self._estop_latched = True
        if (
            self._estop_latched
            and command.actuator == "MOTOR_VEL"
            and command.value != 0
        ):
            return False
        if (
            self._estop_latched
            and command.actuator == "SAFETY_ESTOP_LATCH"
            and command.value is False
        ):
            return False
        return True

    def _new_command(
        self,
        actuator: str,
        value: float | bool,
        issued_at: float,
        expires_at: float,
    ) -> ActuatorCommand:
        """Create a command with a predictable ID for this process instance."""
        command_id = f"os2-{next(self._command_ids)}"
        return ActuatorCommand(command_id, actuator, value, issued_at, expires_at)