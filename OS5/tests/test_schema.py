from contextlib import closing
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edge import storage


class TestDatabaseSchema(unittest.TestCase):
    def test_initialization_creates_required_tables_and_wal(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "schema.db"
            with patch.object(storage, "DATABASE_PATH", database_path):
                storage.initialize_database()

                with closing(storage.get_connection()) as connection:
                    tables = {
                        row["name"]
                        for row in connection.execute(
                            """
                            SELECT name
                            FROM sqlite_master
                            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                            """
                        )
                    }
                    journal_mode = connection.execute(
                        "PRAGMA journal_mode"
                    ).fetchone()[0]

        self.assertEqual(
            tables,
            {"decisions", "events", "outbox", "process_health"},
        )
        self.assertEqual(journal_mode.lower(), "wal")


if __name__ == "__main__":
    unittest.main()
