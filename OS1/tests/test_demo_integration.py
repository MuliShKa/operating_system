"""The live path: SensorEvent -> Processor -> SQLite + command -> Actuator."""

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
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.original = storage.DATABASE_PATH
        storage.DATABASE_PATH = Path(self.folder.name) / "demo.db"
        storage.initialize_database()

    def tearDown(self):
        storage.DATABASE_PATH = self.original
        self.folder.cleanup()

    def run_node_path(self, readings):
        channels = IpcChannels(multiprocessing.get_context("spawn"))
        state = {}
        for event in readings:
            channels.sensor_events.put(event)
        channels.stop.set()
        # Same functions as the live workers, run one after the other.
        run_processor(channels, state)
        run_actuator(channels, state)
        with closing(sqlite3.connect(storage.DATABASE_PATH)) as connection:
            decisions = [row[0] for row in connection.execute(
                "SELECT decision_type FROM decisions ORDER BY decision_id"
            )]
            pending = connection.execute(
                "SELECT COUNT(*) FROM outbox WHERE status = 'pending'"
            ).fetchone()[0]
        return state, decisions, pending

    def test_high_co2_is_stored_decided_and_applied(self):
        now = time.monotonic()
        state, decisions, pending = self.run_node_path([
            SensorEvent("INDOOR_CO2_PPM", 1250, "ppm", 1_798_000_000, now),
            SensorEvent("ROOM_TEMP_C", 23.5, "°C", 1_798_000_000, now),
            SensorEvent("INDOOR_CO2_PPM", 800, "ppm", 1_798_000_001, now),
        ])
        self.assertEqual(decisions, ["HVAC_DAMPER_PCT", "DAMPER_APPLIED"])
        self.assertEqual(pending, 3)
        self.assertEqual(state["damper_pct"], 100)
        self.assertEqual(len(state["recent_readings"]), 3)

    def test_reading_older_than_ttl_is_rejected_by_actuator(self):
        stale = time.monotonic() - 16
        state, decisions, _ = self.run_node_path([
            SensorEvent("INDOOR_CO2_PPM", 1250, "ppm", 1_798_000_000, stale),
        ])
        self.assertEqual(decisions, ["HVAC_DAMPER_PCT", "COMMAND_EXPIRED"])
        self.assertEqual(state["damper_pct"], 0)
        self.assertEqual(state["actuator_expired"], 1)


if __name__ == "__main__":
    unittest.main()
