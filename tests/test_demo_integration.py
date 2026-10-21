import multiprocessing
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edge import storage
from edge.ipc import IpcChannels
from edge.models import SensorEvent
from edge.processor import run_processor


class TestDemoIntegration(unittest.TestCase):
    def test_sensor_queue_flows_through_decision_and_storage(self):
        original_database_path = storage.DATABASE_PATH
        with tempfile.TemporaryDirectory() as temporary_directory:
            try:
                storage.DATABASE_PATH = Path(temporary_directory) / "demo.db"
                storage.initialize_database()

                context = multiprocessing.get_context("spawn")
                channels = IpcChannels(context)
                state = {}
                channels.sensor_events.put(
                    SensorEvent("SLUICE_WATER_LEVEL_M", 3.1, "m", 1_798_000_000)
                )
                channels.sensor_events.put(
                    SensorEvent("MAINS_VOLT", 220.0, "V", 1_798_000_001)
                )
                channels.stop.set()

                # Demo integration: verify the same path used by the live workers.
                run_processor(channels, state)

                with closing(sqlite3.connect(storage.DATABASE_PATH)) as connection:
                    event_count = connection.execute(
                        "SELECT COUNT(*) FROM events"
                    ).fetchone()[0]
                    decision_rows = connection.execute(
                        "SELECT decision_type FROM decisions"
                    ).fetchall()
                    outbox_count = connection.execute(
                        "SELECT COUNT(*) FROM outbox WHERE status = 'pending'"
                    ).fetchone()[0]

                self.assertEqual(event_count, 2)
                self.assertEqual(decision_rows, [("BACKUP_SLUICE_GATE_OPEN",)])
                self.assertEqual(outbox_count, 2)
                self.assertEqual(len(state["recent_readings"]), 2)
                self.assertEqual(
                    state["recent_decisions"][0]["action"],
                    "BACKUP_SLUICE_GATE_OPEN",
                )
                self.assertEqual(state["pending_events"], 2)
            finally:
                storage.DATABASE_PATH = original_database_path


if __name__ == "__main__":
    unittest.main()
