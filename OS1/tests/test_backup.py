"""Scheduled maintenance: online backup, integrity, retention, flock overlap."""

import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

OS1_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OS1_DIR / "src"))

from edge import backup  # noqa: E402


def make_database(path: Path, rows: int) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, value TEXT)")
        connection.executemany("INSERT INTO events (value) VALUES (?)", [(str(i),) for i in range(rows)])
        connection.commit()


class TestBackup(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.database = self.root / "node.db"
        make_database(self.database, 500)

    def tearDown(self):
        self.folder.cleanup()

    def test_copy_has_the_same_rows_and_passes_integrity_check(self):
        target = backup.backup_database(self.database, self.root / "backups")
        with closing(sqlite3.connect(target)) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0], 500)
        self.assertEqual(list((self.root / "backups").glob("*.partial")), [])

    def test_only_the_newest_copies_are_kept(self):
        for _ in range(4):
            backup.backup_database(self.database, self.root / "backups", keep=2)
        self.assertEqual(len(list((self.root / "backups").glob("node-*.db"))), 2)

    def test_missing_database_is_an_error(self):
        with self.assertRaises(FileNotFoundError):
            backup.backup_database(self.root / "missing.db", self.root / "backups")

    def test_second_run_is_refused_while_the_first_holds_the_lock(self):
        env = {**os.environ, "EDGE_DATABASE_PATH": str(self.database)}
        script = str(OS1_DIR / "scripts" / "backup.sh")
        first = subprocess.Popen(
            ["bash", script], env={**env, "EDGE_BACKUP_HOLD_S": "2"},
            stdout=subprocess.PIPE, text=True,
        )
        time.sleep(0.7)
        second = subprocess.run(["bash", script], env=env, capture_output=True, text=True)
        first_out, _ = first.communicate(timeout=30)
        self.assertIn("Backup skipped", second.stdout)
        self.assertIn("Backup OK", first_out)
        self.assertEqual(first.returncode, 0)


if __name__ == "__main__":
    unittest.main()
