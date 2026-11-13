"""Online SQLite backup utility for the OS2 local database."""

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from edge.config import load_config


def create_online_backup(source_path: str | Path, destination_path: str | Path) -> None:
    source = Path(source_path)
    destination = Path(destination_path)
    if source.resolve() == destination.resolve():
        raise ValueError("backup destination must differ from the source database")
    if not source.is_file():
        raise FileNotFoundError(f"source database does not exist: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(source) as source_connection:
        with sqlite3.connect(destination) as destination_connection:
            source_connection.backup(destination_connection)
            result = destination_connection.execute("PRAGMA integrity_check").fetchone()
    if result is None or result[0] != "ok":
        raise sqlite3.DatabaseError(
            f"backup integrity check failed: {None if result is None else result[0]}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an online OS2 database backup")
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()

    config = load_config()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = args.destination or (
        config.database.parent / "backups" / f"os2-{timestamp}.db"
    )
    create_online_backup(config.database, destination)
    print(f"SQLite backup created and verified: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
