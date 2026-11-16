"""Processor: store every reading, order by EVENT time, apply the local rules (OS4-2, OS4-3, OS4-6, OS4-7).

What it does with each reading, in this order:
  1. stores it (events + outbox in ONE transaction), keeping observed_at AND received_at;
  2. tells the channel guard the device is alive;
  3. checks whether the reading is OUT OF ORDER (older, by event time, than the
     newest reading of the same sensor we already have);
  4. for PM2.5 only: runs the mist rule, unless the reading is out of order or
     the channel is not trustworthy (stale / stuck).

It never moves the relay itself: it ISSUES commands, the Actuator applies them.

The logic lives in the class StreamProcessor, which has no process or queue
code, so the tests can feed it readings directly.
"""

from __future__ import annotations

import bisect
import statistics
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from edge import baseline as baseline_module
from edge import decision, guard, storage
from edge.config import PROJECT_DIR, load_config
from edge.models import ActuatorCommand, SensorEvent
from edge.sensors import load_specs

RECENT_READINGS = 30


def iso(epoch: float) -> str:
    """UTC ISO-8601 with microseconds: fixed width, so text order = time order."""
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="microseconds")


class StreamProcessor:
    def __init__(self, state: Any, commands: Any, baseline: baseline_module.Baseline | None = None) -> None:
        config = load_config()
        specs = load_specs()
        self.state = state
        self.commands = commands          # object with .put(command); the real one is a BoundedQueue
        self.baseline = baseline or baseline_module.Baseline(station=str(config["airkorea_station"]), source="", is_sample=False)
        self.config = config
        self.context_max_age = float(config["context_max_age_s"])
        self.window_s = float(config["baseline_window_s"])
        self.min_readings = int(config["baseline_min_readings"])
        self.check_every = float(config["baseline_check_every_s"])
        self.tolerance = float(config["baseline_tolerance_ugm3"])

        self.guards = {
            sid: guard.ChannelGuard(spec.stale_after_s, spec.stuck_check, int(config["stuck_repeat_count"]))
            for sid, spec in specs.items()
        }
        self.status = {sid: guard.NO_DATA for sid in specs}     # last status we reported
        # Newest reading BY EVENT TIME for each sensor: value, observed_at, observed_mono.
        self.latest: dict[str, dict[str, float]] = {}
        self.counters = {sid: {"stored": 0, "out_of_order": 0, "max_lateness_s": 0.0} for sid in specs}
        self.pm25_window: list[tuple[float, float]] = []        # (observed_at, value), kept sorted by event time

        self.last_command_expires_at: float | None = None       # tells a NEW episode from a refresh
        self.held = False                                       # a quiet-night hold is being reported
        self.next_baseline_check = time.monotonic() + self.check_every
        self.last_baseline: dict | None = None
        self.recent_readings: list[dict] = []
        self.recent_decisions: list[dict] = []

    # ------------------------------------------------------------------ readings

    def handle_event(self, event: SensorEvent) -> None:
        event_id = str(uuid.uuid4())
        payload = {
            "sensor_id": event.sensor_id,
            "value": event.value,
            "unit": event.unit,
            "observed_at": iso(event.observed_at),
            "received_at": iso(event.received_at),
        }
        storage.save_event(event_id, event.sensor_id, payload["observed_at"], payload["received_at"], payload)
        self.state["pending_events"] = storage.get_pending_event_count()

        self.guards[event.sensor_id].heard(event.received_mono)
        newest = self.latest.get(event.sensor_id)
        in_order = newest is None or event.observed_at >= newest["observed_at"]

        counters = self.counters[event.sensor_id]
        counters["stored"] += 1
        counters["max_lateness_s"] = round(max(counters["max_lateness_s"], event.lateness_s), 2)
        if not in_order:
            counters["out_of_order"] += 1
        else:
            self.latest[event.sensor_id] = {
                "value": event.value,
                "observed_at": event.observed_at,
                "observed_mono": event.observed_mono,
            }
            self.guards[event.sensor_id].value_seen(event.value)

        if event.sensor_id == "PM25":
            # A late reading still belongs in the window, at its EVENT-time position.
            bisect.insort(self.pm25_window, (event.observed_at, event.value))
            del self.pm25_window[:-500]

        self.recent_readings.append({
            **{k: payload[k] for k in ("sensor_id", "value", "unit", "observed_at", "received_at")},
            "lateness_s": round(event.lateness_s, 2),
            "in_order": in_order,
        })
        del self.recent_readings[:-RECENT_READINGS]
        self.state["recent_readings"] = list(self.recent_readings)

        if event.sensor_id == "PM25":
            self._decide_mist(event, event_id, in_order)
        self.publish(time.monotonic())

    def _context(self, sensor_id: str, now_mono: float) -> float | None:
        """Latest lux / noise value, or None if we have none or it is too old to trust."""
        newest = self.latest.get(sensor_id)
        if newest is None or now_mono - newest["observed_mono"] > self.context_max_age:
            return None
        return newest["value"]

    def _decide_mist(self, event: SensorEvent, event_id: str, in_order: bool) -> None:
        if not in_order:
            # A newer reading already exists. This one is history: it must not
            # start or extend a spray, whatever its value (OS4-2).
            return

        now = time.monotonic()
        self._update_channel_status(now)
        if self.status["PM25"] in (guard.STALE, guard.STUCK):
            return        # fail-safe (OS4-6): no spraying on a sensor we do not trust

        verdict = decision.evaluate_mist(
            event.value, event.observed_mono,
            lux=self._context("LUX", now), noise_db=self._context("NOISE", now),
        )
        if verdict.kind == decision.NONE:
            self.held = False
            return

        if verdict.kind == decision.HOLD:
            if not self.held:     # report the hold once, not at every reading
                self.held = True
                self._record(event_id, "MIST_HELD_QUIET_HOURS", verdict.reason, event.value, None)
            return

        self.held = False
        self.commands.put(ActuatorCommand(
            event_id=event_id,
            action=decision.MIST_ACTION,
            value=1.0,
            expires_at=verdict.expires_at,
            reason=verdict.reason,
        ))
        new_episode = decision.is_command_expired(self.last_command_expires_at)
        self.last_command_expires_at = max(self.last_command_expires_at or 0.0, verdict.expires_at)
        if new_episode:
            left = max(0.0, verdict.expires_at - time.monotonic())
            self._record(event_id, decision.MIST_ACTION, verdict.reason, 1.0, round(left, 1))

    def _record(self, event_id: str | None, action: str, reason: str, value: float, expires_in: float | None) -> None:
        storage.save_decision(event_id, action, reason, value)
        self.recent_decisions.append({
            "action": action,
            "value": value,
            "reason": reason,
            "timestamp": iso(time.time()),
            "expires_in_seconds": expires_in,
        })
        del self.recent_decisions[:-20]
        self.state["recent_decisions"] = list(self.recent_decisions)

    # ------------------------------------------------------------------ channel health

    def _update_channel_status(self, now_mono: float) -> None:
        """Record every change of channel status (OK / STALE / STUCK) as a decision."""
        for sid, channel_guard in self.guards.items():
            current = channel_guard.status(now_mono)
            previous = self.status[sid]
            if current == previous:
                continue
            self.status[sid] = current
            if current == guard.STALE:
                silence = channel_guard.silence_s(now_mono) or 0.0
                self._record(None, "SENSOR_STALE", f"{sid}: no data for {silence:.0f} s (limit {channel_guard.stale_after_s:g} s)", 0.0, None)
            elif current == guard.STUCK:
                self._record(None, "SENSOR_STUCK", f"{sid}: same value {channel_guard.repeat} times in a row", 0.0, None)
            elif current == guard.OK and previous in (guard.STALE, guard.STUCK):
                self._record(None, "SENSOR_RECOVERED", f"{sid}: channel healthy again", 1.0, None)

    # ------------------------------------------------------------------ periodic work

    def tick(self, now_mono: float) -> None:
        """Called every ~0.2 s, also when no reading arrived (silence is the symptom of a hung sensor)."""
        self._update_channel_status(now_mono)
        if now_mono >= self.next_baseline_check:
            self.next_baseline_check = now_mono + self.check_every
            self.baseline_check()
        self.publish(now_mono)

    def baseline_check(self) -> dict | None:
        """Compare the median of the last window of local PM2.5 with the station value (OS4-5)."""
        if not self.pm25_window or not self.baseline.available:
            return None
        newest_at = self.pm25_window[-1][0]
        recent = [value for at, value in self.pm25_window if at >= newest_at - self.window_s]
        if len(recent) < self.min_readings:
            return None
        found = self.baseline.lookup(newest_at)
        if found is None:
            return None
        station_value, match_kind = found
        local_median = statistics.median(recent)
        comparison = baseline_module.compare(local_median, station_value, self.tolerance)
        storage.save_baseline_check(
            self.baseline.station, self.baseline.source, self.baseline.is_sample, match_kind,
            round(station_value, 2), round(local_median, 2), len(recent), comparison,
        )
        self.last_baseline = {
            "station_value": round(station_value, 1),
            "local_median": round(local_median, 1),
            "window_readings": len(recent),
            "match_kind": match_kind,
            "checked_at": iso(time.time()),
            **comparison,
        }
        return self.last_baseline

    def publish(self, now_mono: float) -> None:
        channels = {}
        for sid, channel_guard in self.guards.items():
            newest = self.latest.get(sid)
            silence = channel_guard.silence_s(now_mono)
            channels[sid] = {
                "status": self.status[sid],
                "value": None if newest is None else newest["value"],
                "silence_s": None if silence is None else round(silence, 1),
                **self.counters[sid],
            }
        self.state["channels"] = channels
        self.state["baseline"] = {"source": self.baseline.to_dict(), "last_check": self.last_baseline}


def run_processor(channels: Any, state: Any) -> None:
    config = load_config()
    baseline = baseline_module.load_baseline(
        str(config["airkorea_station"]),
        PROJECT_DIR / str(config["airkorea_csv"]),
        PROJECT_DIR / str(config["airkorea_sample_csv"]),
    )
    processor = StreamProcessor(state, channels.commands, baseline)
    processor.publish(time.monotonic())

    stop_seen_at = None
    while True:
        event = channels.sensor_events.get(timeout=0.2)
        if event is not None:
            processor.handle_event(event)
        else:
            processor.tick(time.monotonic())

        if channels.stop.is_set():
            stop_seen_at = stop_seen_at or time.monotonic()
            drained = channels.sensor_events.size() == 0
            # Leave once Ingest is finished and the queue is empty (or after 2 s, if Ingest died).
            if drained and (channels.ingest_done.is_set() or time.monotonic() - stop_seen_at > 2.0):
                break
