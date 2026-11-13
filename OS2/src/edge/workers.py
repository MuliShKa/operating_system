"""Controller and safety monitor processes (sensor -> queue -> controller -> socket -> safety)."""

import json
import logging
import os
from dataclasses import asdict
from itertools import count
from multiprocessing.synchronize import Event
from statistics import fmean
from time import monotonic

from edge import storage
from edge.bounded_queue import BoundedSensorQueue
from edge.config import NodeConfig
from edge.control import (
    RobotSafetyController,
    evaluate_pending_sensor_readings,
    run_periodic_control_loop,
)
from edge.models import ActuatorCommand, SensorReading
from edge.unix_socket import UnixMessageClient, UnixMessageServer

CRUISE_VELOCITY = 0.5
TELEMETRY_TICKS = 20
LATCH_KEY = "estop_latched"

log = logging.getLogger(__name__)


# Safety monitor

class Actuators:
    def __init__(self, config: NodeConfig, latched: bool) -> None:
        self.guard = RobotSafetyController(
            config.obstacle_threshold_m, config.command_ttl_s, estop_latched=latched
        )
        self.motor_vel = 0.0
        self.motor_expires_at = 0.0

    def apply(self, command: ActuatorCommand, now: float) -> bool:
        if command.actuator == "MOTOR_VEL":
            if (
                isinstance(command.value, bool)
                or not isinstance(command.value, (int, float))
                or not 0 <= command.value <= CRUISE_VELOCITY
            ):
                return False
        elif command.actuator == "SAFETY_ESTOP_LATCH":
            if not isinstance(command.value, bool):
                return False
        else:
            return False
        if not self.guard.accepts(command, now):
            return False
        if command.actuator == "MOTOR_VEL":
            self.motor_vel = float(command.value)
            self.motor_expires_at = command.expires_at
        return True

    def stop_if_expired(self, now: float) -> bool:
        if self.motor_vel and now >= self.motor_expires_at:
            self.motor_vel = 0.0
            return True
        return False

    def status(self) -> dict:
        return {"latched": self.guard.estop_latched, "motor_vel": self.motor_vel}


def parse_commands(message: dict) -> list[ActuatorCommand]:
    try:
        return [ActuatorCommand(**item) for item in message["commands"]]
    except (KeyError, TypeError) as error:
        raise ValueError(f"malformed commands: {error}") from error


def save_latch(config: NodeConfig) -> None:
    storage.latch_estop(config.database, config.name)
    log.warning("E-stop latched")


def run_safety_monitor(stop_event: Event, config: NodeConfig) -> None:
    actuators = Actuators(config, storage.load_state(config.database, LATCH_KEY) == "1")

    def handle(message: dict) -> dict:
        if message.get("cmd") == "status":
            return actuators.status()
        was_latched = actuators.guard.estop_latched
        now = monotonic()
        accepted = [c.command_id for c in parse_commands(message) if actuators.apply(c, now)]
        if actuators.guard.estop_latched and not was_latched:
            save_latch(config)
        return {"accepted": accepted, **actuators.status()}

    # The server thread handles one request at a time; the TTL check below
    # only writes motor_vel, so no lock is needed.
    with UnixMessageServer(config.safety_socket, handle):
        while not stop_event.wait(config.period_s):
            if actuators.stop_if_expired(monotonic()):
                log.warning("motor command expired, motor stopped")


# Controller

def cruise_command(command_id: str, now: float, ttl_s: float) -> ActuatorCommand:
    return ActuatorCommand(command_id, "MOTOR_VEL", CRUISE_VELOCITY, now, now + ttl_s)


def zero_velocity_command(command_id: str, now: float, ttl_s: float) -> ActuatorCommand:
    return ActuatorCommand(command_id, "MOTOR_VEL", 0.0, now, now + ttl_s)


def estop_commands(command_id: str, now: float, ttl_s: float) -> tuple[ActuatorCommand, ...]:
    expires_at = now + ttl_s
    return (
        ActuatorCommand(
            f"{command_id}-latch", "SAFETY_ESTOP_LATCH", True, now, expires_at
        ),
        ActuatorCommand(f"{command_id}-stop", "MOTOR_VEL", 0.0, now, expires_at),
    )


def telemetry(config: NodeConfig, ticks: int, jitters: list[float], latched: bool) -> dict:
    return {
        "node": config.name,
        "ticks": ticks,
        "mean_jitter_ms": round(fmean(jitters) * 1000, 3) if jitters else None,
        "max_jitter_ms": round(max(jitters) * 1000, 3) if jitters else None,
        "estop_latched": latched,
    }


def run_controller(
    sensor_queue: BoundedSensorQueue, stop_event: Event, config: NodeConfig
) -> None:
    client = UnixMessageClient(config.safety_socket, timeout=config.command_ttl_s)
    safety = RobotSafetyController(config.obstacle_threshold_m, config.command_ttl_s)
    ids = (f"ctl-{os.getpid()}-{n}" for n in count(1))
    jitters: list[float] = []
    ticks = 0
    last_lidar_reading: SensorReading | None = None

    def on_tick(now: float, jitter: float | None) -> None:
        nonlocal safety, ticks, last_lidar_reading
        ticks += 1
        if jitter is not None:
            jitters.append(jitter)

        latest_readings: dict[str, str] = {}

        def remember_reading(reading: SensorReading) -> None:
            nonlocal last_lidar_reading
            latest_readings[reading.sensor_id] = json.dumps(
                {
                    "value": reading.value,
                    "unit": reading.unit,
                    "observed_at": reading.observed_at,
                },
                separators=(",", ":"),
            )
            if reading.sensor_id == "LIDAR_PROXIMITY_M":
                last_lidar_reading = reading

        evaluate_pending_sensor_readings(
            sensor_queue, safety, now, on_reading=remember_reading
        )
        if latest_readings:
            storage.save_states(config.database, latest_readings)
        if safety.estop_latched:
            commands = estop_commands(next(ids), now, config.command_ttl_s)
        elif (
            last_lidar_reading is not None
            and 0 <= now - last_lidar_reading.observed_at <= config.command_ttl_s
            and last_lidar_reading.value >= config.obstacle_threshold_m
        ):
            commands = (cruise_command(next(ids), now, config.command_ttl_s),)
        else:
            commands = (
                zero_velocity_command(next(ids), now, config.command_ttl_s),
            )
        try:
            reply = client.request(
                {"cmd": "apply", "commands": [asdict(c) for c in commands]}
            )
        except (OSError, ValueError) as error:
            log.warning("safety monitor unreachable: %s", error)
            reply = {}

        # After a restart this process starts unlatched; follow the monitor.
        if reply.get("latched") and not safety.estop_latched:
            safety = RobotSafetyController(
                config.obstacle_threshold_m, config.command_ttl_s, estop_latched=True
            )

        if ticks % TELEMETRY_TICKS == 0:
            storage.record_event(
                config.database,
                "CONTROL_TELEMETRY",
                telemetry(config, ticks, jitters, safety.estop_latched),
            )
            jitters.clear()

    run_periodic_control_loop(stop_event, on_tick, period_s=config.period_s)
