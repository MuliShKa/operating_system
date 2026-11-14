"""Integration test: queue -> Processor -> command queue -> Actuator -> SQLite and state.

Run: PYTHONPATH=src python tests/test_demo_integration.py -v
"""

import multiprocessing
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edge import storage  # noqa: E402
from edge.actuator import run_actuator  # noqa: E402
from edge.ipc import IpcChannels  # noqa: E402
from edge.models import SensorEvent  # noqa: E402
from edge.processor import run_processor  # noqa: E402


class TestDemoIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.original_database_path = storage.DATABASE_PATH
        self.tmp = tempfile.TemporaryDirectory()
        storage.DATABASE_PATH = Path(self.tmp.name) / "demo.db"
        storage.initialize_database()
        self.channels = IpcChannels(multiprocessing.get_context("spawn"))

    def tearDown(self) -> None:
        storage.DATABASE_PATH = self.original_database_path
        self.tmp.cleanup()

    def rows(self, sql: str) -> list:
        with closing(sqlite3.connect(storage.DATABASE_PATH)) as connection:
            return connection.execute(sql).fetchall()

    def test_surge_flows_through_rule_actuator_and_storage(self) -> None:
        now = time.monotonic()
        # A normal radar reading and a pedestrian surge (urgent lane), both just read.
        self.channels.sensor_events.put(SensorEvent("RADAR_SPEED", 62.0, "km/h", 1_798_000_000, now))
        self.channels.sensor_events.put(
            SensorEvent("PED_CROSSWALK_COUNT", 20, "people", 1_798_000_001, now), urgent=True
        )
        self.channels.stop.set()

        # Same code paths as the live workers: Processor issues, Actuator applies.
        state: dict = {}
        run_processor(self.channels, state)
        run_actuator(self.channels, state)

        self.assertEqual(self.rows("SELECT COUNT(*) FROM events")[0][0], 2)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM outbox WHERE status='pending'")[0][0], 2)
        self.assertEqual(
            self.rows("SELECT decision_type, value FROM decisions ORDER BY decision_id"),
            [("VARIABLE_SPEED_SIGN_KMH", 30.0), ("SIGN_APPLIED", 30.0)],
        )
        # The urgent alarm was processed before the radar reading.
        self.assertEqual(state["recent_readings"][0]["sensor_id"], "PED_CROSSWALK_COUNT")
        self.assertEqual(state["sign_state"]["speed_limit_kmh"], 30)
        self.assertEqual(state["sign_state"]["version"], 1)
        self.assertEqual(state["actuator_applied"], 1)
        self.assertEqual(state["actuator_expired"], 0)

    def test_stale_reading_never_moves_the_sign(self) -> None:
        # A reading that waited longer than the TTL before reaching the Actuator.
        very_old = time.monotonic() - 3600
        self.channels.sensor_events.put(
            SensorEvent("PED_CROSSWALK_COUNT", 25, "people", 1_798_000_000, very_old), urgent=True
        )
        self.channels.stop.set()

        state: dict = {}
        run_processor(self.channels, state)
        run_actuator(self.channels, state)

        self.assertEqual(state["sign_state"]["speed_limit_kmh"], 50)
        self.assertEqual(state["sign_state"]["version"], 0)
        self.assertEqual(state["actuator_expired"], 1)
        self.assertEqual(state["actuator_applied"], 0)
        types = [row[0] for row in self.rows("SELECT decision_type FROM decisions ORDER BY decision_id")]
        self.assertEqual(types, ["VARIABLE_SPEED_SIGN_KMH", "SIGN_COMMAND_EXPIRED"])


if __name__ == "__main__":
    unittest.main()
