from contextlib import closing
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edge import storage


class TestOutboxStorage(unittest.TestCase):
    def test_event_outbox_is_atomic_idempotent_and_marked_sent(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "storage.db"
            with patch.object(storage, "DATABASE_PATH", database_path):
                storage.initialize_database()
                event = {
                    "water_level": 2.9,
                    "threshold": 2.8,
                    "command": "BACKUP_SLUICE_GATE_OPEN",
                }

                self.assertTrue(
                    storage.save_event(
                        "event-1",
                        "SLUICE_WATER_LEVEL_M",
                        "2026-10-21T12:00:00+00:00",
                        event,
                    )
                )
                self.assertFalse(
                    storage.save_event(
                        "event-1",
                        "SLUICE_WATER_LEVEL_M",
                        "2026-10-21T12:00:00+00:00",
                        event,
                    )
                )
                storage.save_decision(
                    "event-1",
                    "BACKUP_SLUICE_GATE_OPEN",
                    "Water level exceeded 2.8 metres",
                )
                storage.save_process_health("Processor", "running", '{"pid": 1}')

                pending = storage.get_pending_events()
                self.assertEqual(len(pending), 1)
                self.assertEqual(pending[0]["event_id"], "event-1")
                self.assertTrue(storage.mark_event_sent("event-1"))
                self.assertFalse(storage.mark_event_sent("event-1"))
                self.assertEqual(storage.get_pending_event_count(), 0)

                with closing(storage.get_connection()) as connection:
                    event_count = connection.execute(
                        "SELECT COUNT(*) FROM events"
                    ).fetchone()[0]
                    outbox_status = connection.execute(
                        "SELECT status FROM outbox WHERE event_id = 'event-1'"
                    ).fetchone()["status"]
                    decision_count = connection.execute(
                        "SELECT COUNT(*) FROM decisions"
                    ).fetchone()[0]

        self.assertEqual(event_count, 1)
        self.assertEqual(outbox_status, "sent")
        self.assertEqual(decision_count, 1)


if __name__ == "__main__":
    unittest.main()
