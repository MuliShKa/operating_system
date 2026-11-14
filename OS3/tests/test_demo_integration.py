"""Integration test: queue -> rule -> SQLite -> dashboard state.

Run: PYTHONPATH=src python tests/test_demo_integration.py -v
"""

import multiprocessing
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edge import storage  # noqa: E402
from edge.ipc import IpcChannels  # noqa: E402
from edge.models import SensorEvent  # noqa: E402
from edge.processor import run_processor  # noqa: E402


class TestDemoIntegration(unittest.TestCase):
    def test_surge_flows_through_rule_sign_and_storage(self) -> None:
        original_database_path = storage.DATABASE_PATH
        with tempfile.TemporaryDirectory() as temporary_directory:
            try:
                storage.DATABASE_PATH = Path(temporary_directory) / "demo.db"
                storage.initialize_database()

                context = multiprocessing.get_context("spawn")
                channels = IpcChannels(context)
                state = {}

                # A normal radar reading and a pedestrian surge (urgent lane).
                channels.sensor_events.put(SensorEvent("RADAR_SPEED", 62.0, "km/h", 1_798_000_000))
                channels.sensor_events.put(
                    SensorEvent("PED_CROSSWALK_COUNT", 20, "people", 1_798_000_001),
                    urgent=True,
                )
                channels.stop.set()

                # Same code path as the live Processor worker.
                run_processor(channels, state)

                with closing(sqlite3.connect(storage.DATABASE_PATH)) as connection:
                    event_count = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                    decision_rows = connection.execute(
                        "SELECT decision_type, value FROM decisions"
                    ).fetchall()
                    outbox_count = connection.execute(
                        "SELECT COUNT(*) FROM outbox WHERE status = 'pending'"
                    ).fetchone()[0]

                self.assertEqual(event_count, 2)
                self.assertEqual(decision_rows, [("VARIABLE_SPEED_SIGN_KMH", 30.0)])
                self.assertEqual(outbox_count, 2)
                self.assertEqual(len(state["recent_readings"]), 2)
                # The urgent alarm was processed before the radar reading.
                self.assertEqual(state["recent_readings"][0]["sensor_id"], "PED_CROSSWALK_COUNT")
                self.assertEqual(state["sign_state"]["speed_limit_kmh"], 30)
                self.assertEqual(state["sign_state"]["version"], 1)
                self.assertTrue(state["sign_state"]["surge_active"])
                self.assertEqual(state["pending_events"], 2)
            finally:
                storage.DATABASE_PATH = original_database_path


if __name__ == "__main__":
    unittest.main()
