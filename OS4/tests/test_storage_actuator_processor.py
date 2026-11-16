"""Unit tests: storage, Actuator (TTL freshness), StreamProcessor (ordering, faults, policy), Ingest.

Run: python tests/test_storage_actuator_processor.py -v
"""

import multiprocessing
import os
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path

os.environ.setdefault("EDGE_SOCKET_DIR", f"/tmp/songdo-os4-test-{os.getpid()}")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edge import baseline as baseline_module  # noqa: E402
from edge import storage  # noqa: E402
from edge.actuator import EXPIRED, MistActuator, RESTORED  # noqa: E402
from edge.ingest import run_ingest  # noqa: E402
from edge.ipc import IpcChannels  # noqa: E402
from edge.models import ActuatorCommand, SensorEvent  # noqa: E402
from edge.processor import StreamProcessor, iso  # noqa: E402
from edge.sensors import load_specs  # noqa: E402


class DatabaseTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.original = storage.DATABASE_PATH
        self.tmp = tempfile.TemporaryDirectory()
        storage.DATABASE_PATH = Path(self.tmp.name) / "test.db"
        storage.initialize_database()

    def tearDown(self) -> None:
        storage.DATABASE_PATH = self.original
        self.tmp.cleanup()

    def rows(self, sql: str) -> list:
        with closing(sqlite3.connect(storage.DATABASE_PATH)) as connection:
            return connection.execute(sql).fetchall()


class TestStorage(DatabaseTestCase):
    def test_both_timestamps_are_stored_and_event_is_queued_once(self) -> None:
        self.assertTrue(storage.save_event("e1", "PM25", "2026-01-01T00:00:00.000001+00:00",
                                           "2026-01-01T00:00:09.000002+00:00", {"value": 1}))
        self.assertFalse(storage.save_event("e1", "PM25", "x", "y", {"value": 2}))   # duplicate id ignored
        self.assertEqual(self.rows("SELECT observed_at, received_at FROM events"),
                         [("2026-01-01T00:00:00.000001+00:00", "2026-01-01T00:00:09.000002+00:00")])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM outbox"), [(1,)])

    def test_wal_mode(self) -> None:
        self.assertEqual(self.rows("PRAGMA journal_mode"), [("wal",)])

    def test_decision_needs_a_real_event(self) -> None:
        with self.assertRaises(ValueError):
            storage.save_decision("missing", "X")
        storage.save_decision(None, "RELAY_OFF")     # no cause event is allowed

    def test_outbox_sent_only_once(self) -> None:
        storage.save_event("e1", "PM25", "a", "b", {})
        self.assertEqual(storage.get_pending_event_count(), 1)
        self.assertTrue(storage.mark_event_sent("e1"))
        self.assertFalse(storage.mark_event_sent("e1"))
        self.assertEqual(storage.get_pending_event_count(), 0)

    def test_relay_update_is_version_guarded(self) -> None:
        row = storage.get_relay_state()
        self.assertEqual((row["state"], row["version"]), ("OFF", 0))
        self.assertTrue(storage.update_relay_state("ON", 0))
        self.assertFalse(storage.update_relay_state("OFF", 0))     # stale writer loses
        self.assertEqual(storage.get_relay_state()["state"], "ON")
        with self.assertRaises(ValueError):
            storage.update_relay_state("MAYBE", 1)


class TestActuator(DatabaseTestCase):
    def command(self, expires_at: float) -> ActuatorCommand:
        storage.save_event("evt", "PM25", "a", "b", {})
        return ActuatorCommand("evt", "MIST_CANNON_RELAY", 1.0, expires_at, "test")

    def test_fresh_command_switches_on_and_ttl_switches_off(self) -> None:
        actuator = MistActuator({})
        actuator.start()
        self.assertEqual(actuator.handle(self.command(130.0), now=100.0), "MIST_RELAY_ON")
        self.assertEqual(storage.get_relay_state()["state"], "ON")
        self.assertFalse(actuator.tick(129.9))
        self.assertTrue(actuator.tick(130.1))
        self.assertEqual(storage.get_relay_state()["state"], "OFF")
        self.assertIn(RESTORED, [r[0] for r in self.rows("SELECT decision_type FROM decisions")])

    def test_stale_command_is_rejected(self) -> None:
        state: dict = {}
        actuator = MistActuator(state)
        actuator.start()
        self.assertEqual(actuator.handle(self.command(130.0), now=131.0), EXPIRED)
        self.assertEqual(storage.get_relay_state()["state"], "OFF")
        self.assertEqual(state["actuator_expired"], 1)

    def test_second_command_only_renews_the_deadline(self) -> None:
        actuator = MistActuator({})
        actuator.start()
        actuator.handle(self.command(130.0), now=100.0)
        self.assertEqual(actuator.handle(ActuatorCommand("evt", "MIST_CANNON_RELAY", 1.0, 150.0, "again"), now=120.0), "MIST_REFRESHED")
        self.assertFalse(actuator.tick(135.0))     # renewed: still alive past the first deadline
        self.assertTrue(actuator.tick(150.5))

    def test_startup_does_not_trust_a_relay_left_on(self) -> None:
        storage.update_relay_state("ON", 0)
        MistActuator({}).start()
        self.assertEqual(storage.get_relay_state()["state"], "OFF")

    def test_clean_shutdown_never_leaves_the_pump_on(self) -> None:
        actuator = MistActuator({})
        actuator.start()
        actuator.handle(self.command(10_000.0), now=1.0)
        actuator.shutdown()
        self.assertEqual(storage.get_relay_state()["state"], "OFF")


class FakeQueue:
    def __init__(self) -> None:
        self.items: list = []

    def put(self, item) -> None:
        self.items.append(item)


def reading(sensor: str, value: float, age: float = 0.0, lateness: float = 0.0) -> SensorEvent:
    """A reading measured `age` seconds ago that arrived `lateness` s after being measured."""
    unit = {"PM25": "ug/m3", "NOISE": "dB", "LUX": "lux"}[sensor]
    now_w, now_m = time.time(), time.monotonic()
    received_at = now_w - age + lateness
    return SensorEvent(sensor, value, unit, observed_at=now_w - age, received_at=received_at,
                       observed_mono=now_m - age, received_mono=now_m)


class TestStreamProcessor(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.state: dict = {}
        self.commands = FakeQueue()
        self.processor = StreamProcessor(self.state, self.commands)

    def decisions(self) -> list[str]:
        return [r[0] for r in self.rows("SELECT decision_type FROM decisions ORDER BY decision_id")]

    def test_high_reading_issues_command_with_ttl_from_event_time(self) -> None:
        self.processor.handle_event(reading("PM25", 70.0, age=8.0, lateness=8.0))
        self.assertEqual(len(self.commands.items), 1)
        left = self.commands.items[0].expires_at - time.monotonic()
        self.assertTrue(21.0 < left < 22.5, left)        # 30 s TTL minus 8 s already travelled

    def test_late_high_reading_is_stored_but_cannot_start_a_spray(self) -> None:
        self.processor.handle_event(reading("PM25", 20.0, age=0.0))
        self.processor.handle_event(reading("PM25", 95.0, age=5.0, lateness=5.0))
        self.assertEqual(self.commands.items, [])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM events WHERE event_type='PM25'"), [(2,)])
        self.assertEqual(self.state["channels"]["PM25"]["out_of_order"], 1)
        self.assertGreaterEqual(self.state["channels"]["PM25"]["max_lateness_s"], 5.0)

    def test_both_clocks_reach_the_database(self) -> None:
        event = reading("PM25", 20.0, age=3.0, lateness=3.0)
        self.processor.handle_event(event)
        observed, received = self.rows("SELECT observed_at, received_at FROM events")[0]
        self.assertEqual(observed, iso(event.observed_at))
        self.assertEqual(received, iso(event.received_at))

    def test_one_dispatch_decision_per_episode_but_every_reading_renews(self) -> None:
        for _ in range(4):
            self.processor.handle_event(reading("PM25", 70.0))
        self.assertEqual(len(self.commands.items), 4)
        self.assertEqual(self.decisions().count("MIST_CANNON_RELAY"), 1)

    def test_frozen_sensor_blocks_the_rule(self) -> None:
        for _ in range(5):
            self.processor.handle_event(reading("PM25", 70.0))
        issued = len(self.commands.items)
        self.processor.handle_event(reading("PM25", 70.0))      # 6th identical value: STUCK
        self.assertEqual(len(self.commands.items), issued)
        self.assertIn("SENSOR_STUCK", self.decisions())
        self.processor.handle_event(reading("PM25", 71.0))      # value changes: recovered
        self.assertIn("SENSOR_RECOVERED", self.decisions())
        self.assertEqual(len(self.commands.items), issued + 1)

    def test_silence_marks_the_channel_stale_and_recovers(self) -> None:
        self.processor.handle_event(reading("PM25", 20.0))
        self.processor.tick(time.monotonic() + 11.0)
        self.assertEqual(self.state["channels"]["PM25"]["status"], "STALE")
        self.assertIn("SENSOR_STALE", self.decisions())
        self.processor.handle_event(reading("PM25", 21.0))
        self.assertIn("SENSOR_RECOVERED", self.decisions())

    def test_quiet_night_holds_once_and_very_bad_overrides(self) -> None:
        self.processor.handle_event(reading("LUX", 2.0))
        self.processor.handle_event(reading("NOISE", 38.0))
        for _ in range(3):
            self.processor.handle_event(reading("PM25", 60.0 + _))
        self.assertEqual(self.commands.items, [])
        self.assertEqual(self.decisions().count("MIST_HELD_QUIET_HOURS"), 1)
        self.processor.handle_event(reading("PM25", 85.0))
        self.assertEqual(len(self.commands.items), 1)
        self.assertIn("override", self.commands.items[0].reason)

    def test_old_context_is_not_trusted(self) -> None:
        self.processor.handle_event(reading("LUX", 2.0, age=40.0))      # older than context_max_age_s
        self.processor.handle_event(reading("NOISE", 38.0, age=40.0))
        self.processor.handle_event(reading("PM25", 60.0))
        self.assertEqual(len(self.commands.items), 1)

    def test_baseline_check_is_stored(self) -> None:
        path = Path(self.tmp.name) / "b.csv"
        rows = "".join(f"2026-11-15 {h:02d}:00,20\n" for h in range(24))   # every hour: the test may run at any time
        path.write_text("datetime,pm25\n" + rows, encoding="utf-8")
        base = baseline_module.load_baseline("131233", path, Path("/none"))
        processor = StreamProcessor(self.state, self.commands, base)
        for i in range(6):
            processor.handle_event(reading("PM25", 22.0 + i * 0.1, age=10 - i))
        result = processor.baseline_check()
        self.assertEqual(result["status"], "AGREE")
        row = self.rows("SELECT station, is_sample, status FROM baseline_checks")
        self.assertEqual(row, [("131233", 0, "AGREE")])


class TestIngestProcess(unittest.TestCase):
    def test_one_process_serves_three_sockets_without_blocking(self) -> None:
        specs = load_specs()
        channels = IpcChannels(multiprocessing.get_context("spawn"))
        state: dict = {}
        thread = threading.Thread(target=run_ingest, args=(channels, state), daemon=True)
        thread.start()
        deadline = time.monotonic() + 5
        while not all(s.socket_path.exists() for s in specs.values()):
            self.assertLess(time.monotonic(), deadline, "sockets were not created")
            time.sleep(0.05)

        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
            # Only NOISE and LUX talk; the silent PM25 socket must not stall them.
            for i in range(5):
                client.sendto(specs["NOISE"].encode(50.0 + i, time.time()), str(specs["NOISE"].socket_path))
            client.sendto(specs["LUX"].encode(300.0, time.time()), str(specs["LUX"].socket_path))
            client.sendto(b"garbage", str(specs["PM25"].socket_path))
        time.sleep(0.5)
        channels.stop.set()
        thread.join(5)

        self.assertFalse(thread.is_alive())
        self.assertTrue(channels.ingest_done.is_set())
        received = []
        while channels.sensor_events.size():
            received.append(channels.sensor_events.get(timeout=0.1))
        self.assertEqual(sorted(e.sensor_id for e in received), ["LUX"] + ["NOISE"] * 5)
        self.assertEqual(state["ingest"]["channels"]["PM25"]["parse_errors"], 1)
        self.assertFalse(any(s.socket_path.exists() for s in specs.values()))   # cleaned up


if __name__ == "__main__":
    unittest.main()
