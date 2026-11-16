"""Create a consistent SQLite backup while holding a process-wide lock."""

from __future__ import annotations

import fcntl
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from edge import storage

PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_BACKUP_DIR = PROJECT_DIR / "data" / "backups"


def create_backup(
    source_path: Path | None = None,
    backup_dir: Path = DEFAULT_BACKUP_DIR,
    destination_path: Path | None = None,
) -> Path:
    """Create and verify an online backup; fail if another backup holds the lock."""
    source = Path(source_path or storage.DATABASE_PATH)
    directory = Path(backup_dir)
    directory.mkdir(parents=True, exist_ok=True)

    if not source.is_file():
        raise FileNotFoundError(f"database does not exist: {source}")

    destination = Path(destination_path) if destination_path else directory / (
        "songdo-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".db"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.resolve() == source.resolve():
        raise ValueError("backup destination must differ from the source database")

    lock_path = directory / ".backup.lock"
    with lock_path.open("a+b") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise BlockingIOError(
                f"another database backup is running (lock: {lock_path})"
            ) from error

        try:
            if destination.exists():
                raise FileExistsError(f"backup already exists: {destination}")

            try:
                with closing(sqlite3.connect(source)) as source_connection:
                    with closing(sqlite3.connect(destination)) as backup_connection:
                        source_connection.backup(backup_connection)
                        integrity = backup_connection.execute(
                            "PRAGMA integrity_check"
                        ).fetchone()[0]

                if integrity != "ok":
                    raise sqlite3.DatabaseError(
                        f"backup integrity check failed: {integrity}"
                    )
            except Exception:
                if destination.exists():
                    destination.unlink()
                raise
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    return destination


if __name__ == "__main__":
    print(f"Database backup created: {create_backup()}")
