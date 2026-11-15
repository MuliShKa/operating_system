"""
Online SQLite backup of the node database (scheduled maintenance).

Uses the SQLite online backup API (Connection.backup): it copies the pages
while the node keeps writing, so the node does not need to stop and the copy
is consistent. Run it through scripts/backup.sh, which takes a flock first so
two backups never overlap.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path

from edge import storage

BACKUP_DIR = Path(os.environ.get("EDGE_BACKUP_DIR", str(storage.DATABASE_PATH.parent / "backups")))
KEEP = int(os.environ.get("EDGE_BACKUP_KEEP", "10"))


def backup_database(source: Path, backup_dir: Path, keep: int = KEEP) -> Path:
    """Copy `source` into a new timestamped file and keep only the newest `keep` copies."""
    if not source.exists():
        raise FileNotFoundError(f"No database to back up: {source}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"{source.stem}-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
    partial = target.with_suffix(".db.partial")

    with closing(sqlite3.connect(source, timeout=10)) as src, closing(sqlite3.connect(partial)) as dst:
        src.execute("PRAGMA busy_timeout = 10000")
        # pages=256: copy in steps so the node's writers are not blocked for long.
        src.backup(dst, pages=256, sleep=0.005)
        result = dst.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"Backup failed integrity_check: {result}")

    # Rename is atomic: a reader never sees a half-written backup file.
    partial.rename(target)

    backups = sorted(backup_dir.glob(f"{source.stem}-*.db"))
    for old in backups[:-keep] if keep > 0 else []:
        old.unlink()
    return target


def main() -> int:
    hold_s = float(os.environ.get("EDGE_BACKUP_HOLD_S", "0"))
    started = time.monotonic()
    target = backup_database(storage.DATABASE_PATH, BACKUP_DIR)
    # Test hook: keep the lock a little longer to show that a second run is refused.
    if hold_s:
        time.sleep(hold_s)
    print(f"Backup OK: {target} ({target.stat().st_size} bytes, {time.monotonic() - started:.2f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
