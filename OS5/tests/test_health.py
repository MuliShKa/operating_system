import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edge import storage
from edge.health import REQUIRED_WORKERS, build_readiness_report


class TestReadinessReport(unittest.TestCase):
    def setUp(self):
        self.heartbeats = {
            name: {
                "status": "running",
                "checked_at": "1970-01-01 00:16:40",
                "checked_at_epoch": 1000.0,
            }
            for name in REQUIRED_WORKERS
        }

    def test_missing_heartbeats_report_starting(self):
        report = build_readiness_report(
            {},
            database_ready=True,
            now=1000.0,
        )

        self.assertFalse(report["ready"])
        self.assertEqual(
            report["checks"]["workers"]["SensorGen"]["status"],
            "starting",
        )

    def test_fresh_workers_and_database_are_ready(self):
        report = build_readiness_report(
            self.heartbeats,
            database_ready=True,
            now=1000.0,
        )

        self.assertTrue(report["ready"])
        self.assertEqual(report["status"], "ready")

    def test_stale_heartbeat_and_stopped_worker_are_not_ready(self):
        self.heartbeats["Processor"]["status"] = "stopped"
        self.heartbeats["API"]["checked_at_epoch"] = 984.0

        report = build_readiness_report(
            self.heartbeats,
            database_ready=True,
            now=1000.0,
        )

        self.assertFalse(report["ready"])
        self.assertEqual(
            report["checks"]["workers"]["Processor"]["status"],
            "stopped",
        )
        self.assertEqual(
            report["checks"]["workers"]["API"]["status"],
            "stale",
        )

    def test_unavailable_database_is_not_ready(self):
        report = build_readiness_report(
            self.heartbeats,
            database_ready=False,
            database_error="database unavailable",
            now=1000.0,
        )

        self.assertFalse(report["ready"])
        self.assertEqual(
            report["checks"]["database"]["error"],
            "database unavailable",
        )


class TestLatestProcessHealth(unittest.TestCase):
    def test_database_readiness_rejects_missing_schema(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "empty.db"
            with patch.object(storage, "DATABASE_PATH", database_path):
                sqlite3.connect(database_path).close()
                with self.assertRaises(sqlite3.DatabaseError):
                    storage.check_database_ready()

    def test_returns_latest_heartbeat_per_process(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "health.db"
            with patch.object(storage, "DATABASE_PATH", database_path):
                storage.initialize_database()
                storage.save_process_health("Processor", "running", '{"pid":10}')
                storage.save_process_health("Processor", "stopped", '{"pid":10}')
                storage.save_process_health("API", "running", '{"pid":11}')

                latest = storage.get_latest_process_health()

        self.assertEqual(latest["Processor"]["status"], "stopped")
        self.assertEqual(latest["API"]["status"], "running")
        self.assertIsNotNone(latest["Processor"]["checked_at_epoch"])


if __name__ == "__main__":
    unittest.main()
