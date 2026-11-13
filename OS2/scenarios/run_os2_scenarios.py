#!/usr/bin/env python3
"""Run the five OS2 acceptance demonstrations against a live local node."""

import argparse
import json
import os
import signal
import time
import uuid
from dataclasses import asdict
from urllib.error import URLError
from urllib.request import Request, urlopen

from edge import storage
from edge.config import load_config
from edge.models import ActuatorCommand
from edge.unix_socket import UnixMessageClient

config = load_config()
BASE_URL = f"http://127.0.0.1:{config.api_port}"
EXPECTED_WORKERS = {
    "api-server",
    "controller",
    "safety-monitor",
    "sensor-generator",
    "sync-worker",
}


def _request(path: str, payload: dict | None = None) -> object:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        BASE_URL + path,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=3) as response:
        return json.loads(response.read())


def _wait_for(predicate, timeout_s: float, description: str):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.05)
    raise RuntimeError(f"timed out waiting for {description}")


def scenario_1_process_topology() -> None:
    status = _request("/api/status")
    processes = {process["process_name"]: process for process in status["processes"]}
    missing = EXPECTED_WORKERS - processes.keys()
    if missing:
        raise RuntimeError(f"worker roles not reported: {sorted(missing)}")
    stopped = [
        name for name in EXPECTED_WORKERS if not processes[name]["alive"]
    ]
    if stopped:
        raise RuntimeError(f"worker roles are not running: {sorted(stopped)}")
    pids = [processes[name]["pid"] for name in EXPECTED_WORKERS]
    if len(set(pids)) != len(pids):
        raise RuntimeError("worker roles do not have distinct process IDs")
    print("OS2-1 PASS: five worker processes are alive with distinct PIDs.")


def scenario_2_monotonic_jitter() -> None:
    telemetry = _wait_for(
        lambda: [
            event["payload"]
            for event in _request("/api/events")
            if event["event_type"] == "CONTROL_TELEMETRY"
            and event["payload"].get("max_jitter_ms") is not None
        ],
        5,
        "control-loop telemetry",
    )
    sample = telemetry[0]
    if sample["ticks"] < 20 or sample["max_jitter_ms"] < 0:
        raise RuntimeError(f"invalid control-loop telemetry: {sample}")
    print(
        "OS2-2 PASS: monotonic 50 ms loop measured jitter "
        f"(max {sample['max_jitter_ms']} ms)."
    )


def scenario_3_obstacle_stop() -> None:
    now = time.monotonic()
    expired = ActuatorCommand(
        command_id=f"scenario-expired-{uuid.uuid4()}",
        actuator="MOTOR_VEL",
        value=0.25,
        issued_at=now - 1,
        expires_at=now - 0.1,
    )
    safety = UnixMessageClient(config.safety_socket, timeout=1)
    if not expired.is_expired(now):
        raise RuntimeError("expired command was not identified as expired")
    reply = safety.request(
        {"cmd": "apply", "commands": [asdict(expired)]}
    )
    if expired.command_id in reply.get("accepted", []):
        raise RuntimeError("safety monitor accepted an expired motor command")

    _request(
        "/api/sensor",
        {"sensor_id": "LIDAR_PROXIMITY_M", "value": 0.5},
    )
    status = _wait_for(
        lambda: (
            current
            if (current := _request("/api/status"))["safety"]["latched"]
            and current["safety"]["motor_vel"] == 0
            else None
        ),
        2,
        "latched E-stop and zero motor velocity",
    )
    if not status["safety"]["latched"]:
        raise RuntimeError("safety monitor did not latch")
    print(
        "OS2-3 PASS: expired command rejected; 0.5 m obstacle latched "
        "E-stop and stopped motion."
    )


def scenario_4_worker_restart() -> None:
    before = _request("/api/status")
    process = next(
        item for item in before["processes"]
        if item["process_name"] == "controller" and item["alive"]
    )
    old_pid = process["pid"]
    os.kill(old_pid, signal.SIGKILL)
    after = _wait_for(
        lambda: next(
            (
                item for item in _request("/api/status")["processes"]
                if item["process_name"] == "controller"
                and item["alive"]
                and item["pid"] != old_pid
            ),
            None,
        ),
        2,
        "controller restart within two seconds",
    )
    print(
        f"OS2-4 PASS: controller restarted within two seconds "
        f"({old_pid} -> {after['pid']})."
    )


def scenario_5_offline_conservation(offline_seconds: int) -> None:
    _wait_for(
        lambda: storage.outbox_counts(config.database)["pending"] == 0,
        10,
        "outbox to drain before WAN cut",
    )
    _request("/api/network", {"online": False})
    checkpoint = storage.latest_outbox_sequence(config.database)
    receiver = UnixMessageClient(config.upstream_socket, timeout=3)
    try:
        deadline = time.monotonic() + offline_seconds
        while time.monotonic() < deadline:
            status = receiver.request({"cmd": "status"})
            if status.get("wan_online") is not False:
                raise RuntimeError("WAN became online before the outage ended")
            time.sleep(min(5, max(0, deadline - time.monotonic())))

        event_ids = storage.outbox_event_ids_after(config.database, checkpoint)
        if not event_ids:
            raise RuntimeError("no events accumulated while WAN was offline")
        pending_ids = {
            event["event_id"]
            for event in storage.pending_events(config.database, len(event_ids))
        }
        if not set(event_ids).issubset(pending_ids):
            raise RuntimeError("offline events were acknowledged before WAN recovery")
    finally:
        _request("/api/network", {"online": True})

    acknowledged = set()

    def all_events_received() -> bool:
        for offset in range(0, len(event_ids), config.sync_batch_size):
            batch = event_ids[offset : offset + config.sync_batch_size]
            response = receiver.request({"cmd": "contains", "event_ids": batch})
            present = response.get("present")
            if not isinstance(present, list):
                raise RuntimeError(f"invalid upstream lookup response: {response}")
            acknowledged.update(present)
        return len(acknowledged) == len(event_ids)

    _wait_for(all_events_received, max(30, len(event_ids)), "offline events to drain")
    print(
        f"OS2-5 PASS: {len(event_ids)} offline events were acknowledged "
        "without loss or duplicate IDs."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline-seconds",
        type=int,
        default=600,
        help="WAN outage duration (default: 600 seconds)",
    )
    args = parser.parse_args()
    if args.offline_seconds < 1:
        parser.error("--offline-seconds must be positive")

    try:
        scenario_1_process_topology()
        scenario_2_monotonic_jitter()
        scenario_3_obstacle_stop()
        scenario_4_worker_restart()
        scenario_5_offline_conservation(args.offline_seconds)
    except (OSError, URLError, RuntimeError, StopIteration, KeyError) as error:
        raise SystemExit(f"OS2 scenario failed: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
