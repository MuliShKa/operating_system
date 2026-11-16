"""SensorGen process: the three simulated devices on the tower (scenarios OS4-1, OS4-2).

Everything here is SIMULATED. The three devices run at different rates and speak
different wire formats (see sensors.py). To mimic delayed sensor nodes, a share
of the readings is HELD BACK before sending, so they reach the gateway late and
out of order while still carrying their original `observed_at` time.

Simulation knobs (environment, read once at start):
  EDGE_SIM_SENSORS          comma list of devices to run (default PM25,NOISE,LUX)
  EDGE_SIM_LATE_PROB        chance that a reading is delayed (default 0.15)
  EDGE_SIM_MAX_LATE_S       longest delay in seconds (default 6)
  EDGE_SIM_AUTO_EPISODES    1 = a dust episode starts by itself (default 1)
and the live switches in channels.sim (episode, extreme, night, mute_pm25, ...).
"""

from __future__ import annotations

import heapq
import os
import random
import socket
import time
from typing import Any

from edge import baseline
from edge.config import PROJECT_DIR, load_config
from edge.sensors import SENSOR_IDS, SensorSpec, load_specs

AUTO_EPISODE_EVERY_S = 45.0
AUTO_EPISODE_LENGTH_S = 15.0
TICK_S = 0.05


class DeviceSimulator:
    """Produces plausible values for the three sensors. No I/O: easy to test."""

    def __init__(self, baseline_pm25: float, rng: random.Random | None = None) -> None:
        self.baseline_pm25 = baseline_pm25
        self.rng = rng or random.Random()
        self.last_pm25 = baseline_pm25

    def pm25(self, episode: bool, extreme: bool, stuck: bool) -> float:
        if stuck:
            return self.last_pm25                       # a frozen device repeats itself
        if episode:
            value = self.rng.uniform(80, 100) if extreme else self.rng.uniform(58, 72)
        else:
            # Background follows the station's typical level, always below the Bad threshold.
            value = min(45.0, max(1.0, self.baseline_pm25 + self.rng.gauss(0, 3)))
        self.last_pm25 = round(value, 1)
        return self.last_pm25

    def noise(self, night: bool) -> float:
        if night:
            return round(self.rng.uniform(34, 42), 1)
        return round(max(35.0, self.rng.gauss(58, 4)), 1)

    def lux(self, night: bool) -> float:
        value = self.rng.uniform(0.5, 5.0) if night else self.rng.gauss(450, 60)
        return round(max(0.5, value), 1)


def _background_pm25() -> float:
    """Typical PM2.5 for this hour, taken from the cached station baseline."""
    config = load_config()
    base = baseline.load_baseline(
        str(config["airkorea_station"]),
        PROJECT_DIR / str(config["airkorea_csv"]),
        PROJECT_DIR / str(config["airkorea_sample_csv"]),
    )
    found = base.lookup(time.time())
    return found[0] if found else 20.0


def run_sensor_gen(channels: Any) -> None:
    specs = load_specs()
    enabled = [s.strip().upper() for s in os.environ.get("EDGE_SIM_SENSORS", ",".join(SENSOR_IDS)).split(",") if s.strip()]
    late_prob = float(os.environ.get("EDGE_SIM_LATE_PROB", "0.15"))
    max_late_s = float(os.environ.get("EDGE_SIM_MAX_LATE_S", "6"))
    auto_episodes = os.environ.get("EDGE_SIM_AUTO_EPISODES", "1") != "0"
    print(f"[SensorGen] Started: devices={enabled}, late_prob={late_prob}, auto_episodes={auto_episodes}", flush=True)

    devices = DeviceSimulator(_background_pm25())
    client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    client.settimeout(0.2)   # never block forever if the gateway is not reading

    now = time.monotonic()
    next_due = {sid: now + random.uniform(0, specs[sid].period_s) for sid in enabled if sid in specs}
    next_episode_at = now + AUTO_EPISODE_EVERY_S
    episode_until = 0.0
    held: list[tuple[float, int, SensorSpec, bytes]] = []   # (deliver_at, sequence, spec, datagram)
    sequence = 0

    while not channels.stop.is_set():
        now = time.monotonic()
        sim = channels.sim

        if auto_episodes and now >= next_episode_at:
            episode_until = now + AUTO_EPISODE_LENGTH_S
            next_episode_at = now + AUTO_EPISODE_EVERY_S
        episode = sim["episode"].is_set() or now < episode_until

        for sid, due in list(next_due.items()):
            if now < due:
                continue
            spec = specs[sid]
            # +-10 % jitter: the devices are NOT synchronised with each other.
            next_due[sid] = due + spec.period_s * random.uniform(0.9, 1.1)
            if sim["pause"].is_set() or (sid == "PM25" and sim["mute_pm25"].is_set()):
                continue
            observed_at = time.time()
            if sid == "PM25":
                value = devices.pm25(episode, sim["extreme"].is_set(), sim["stuck_pm25"].is_set())
            elif sid == "NOISE":
                value = devices.noise(sim["night"].is_set())
            else:
                value = devices.lux(sim["night"].is_set())
            delay = random.uniform(0.5, max_late_s) if random.random() < late_prob else 0.0
            sequence += 1
            heapq.heappush(held, (now + delay, sequence, spec, spec.encode(value, observed_at)))

        # Send everything whose delivery time has come (late ones go out after newer ones).
        while held and held[0][0] <= now:
            _, _, spec, datagram = heapq.heappop(held)
            try:
                client.sendto(datagram, str(spec.socket_path))
            except OSError:
                pass   # gateway not listening yet (or its queue is full): this reading is lost

        # Event.wait() instead of time.sleep(): shutdown is not delayed.
        if channels.stop.wait(TICK_S):
            break

    client.close()
    print("[SensorGen] Stop signal received. Shutting down gracefully.", flush=True)
