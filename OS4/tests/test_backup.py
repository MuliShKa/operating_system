"""Tests for the online SQLite backup (OS4-4)."""

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("EDGE_SOCKET_DIR", f"/tmp/songdo-os4-test-{os.getpid()}")
sys.path.insert(0, str(ROOT / "src"))

from edge import backup  # noqa: E402


def make_db(path: Path, rows: int = 50) -> None:
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("CREATE TABLE t (n INTEGER)")
    db.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(rows)])
    db.commit()
    db.close()


class TestBackup(unittest.TestCase):
    def test_backup_is_consistent_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "node.db"
            make_db(src)
            target = backup.backup_database(src, Path(tmp) / "b", keep=5)
            db = sqlite3.connect(target)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM t").fetchone()[0], 50)
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            db.close()
            self.assertFalse(list((Path(tmp) / "b").glob("*.partial")))

    def test_retention_keeps_only_newest(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "node.db"
            make_db(src)
            for _ in range(6):
                backup.backup_database(src, Path(tmp) / "b", keep=3)
            self.assertEqual(len(list((Path(tmp) / "b").glob("node-*.db"))), 3)

    def test_missing_database_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                backup.backup_database(Path(tmp) / "nope.db", Path(tmp) / "b")

    @unittest.skipUnless(sys.platform.startswith("linux"), "flock needs Linux")
    def test_flock_refuses_overlapping_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "node.db"
            make_db(src)
            env = dict(os.environ, EDGE_DATABASE_PATH=str(src), EDGE_BACKUP_HOLD_S="2")
            first = subprocess.Popen(["bash", str(ROOT / "scripts" / "backup.sh")], env=env,
                                     stdout=subprocess.PIPE, text=True)
            import time
            time.sleep(1)  # the first run now holds the lock
            second = subprocess.run(["bash", str(ROOT / "scripts" / "backup.sh")], env=env,
                                    capture_output=True, text=True)
            first.communicate()
            self.assertEqual(second.returncode, 0)
            self.assertIn("Backup skipped", second.stdout)
            self.assertEqual(first.returncode, 0)
            self.assertEqual(len(list((Path(tmp) / "backups").glob("node-*.db"))), 1)


if __name__ == "__main__":
    unittest.main()
