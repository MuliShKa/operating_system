import tempfile
import unittest
from pathlib import Path

from edge import storage


class OutboxCheckpointTests(unittest.TestCase):
    def test_lists_only_events_created_after_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "os2.db"
            storage.init_db(database)
            storage.record_event(database, "BEFORE", {})
            checkpoint = storage.latest_outbox_sequence(database)
            after_id = storage.record_event(database, "AFTER", {})

            self.assertEqual(
                storage.outbox_event_ids_after(database, checkpoint), [after_id]
            )

    def test_rejects_negative_checkpoint(self) -> None:
        with self.assertRaises(ValueError):
            storage.outbox_event_ids_after(":memory:", -1)


if __name__ == "__main__":
    unittest.main()
