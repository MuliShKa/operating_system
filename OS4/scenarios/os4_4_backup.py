#!/usr/bin/env python3
"""OS4-4: scheduled database backup (systemd timer / cron) with flock overlap prevention.

Handbook OS concept: safe execution using the SQLite online backup API; zero
corrupt locks.

While the node keeps writing, we:
  - run two backups at the same moment: one must win, the other must be refused by flock;
  - verify the backup is a consistent, uncorrupted copy (integrity_check) and the node
    never stopped writing nor hit "database is locked";
  - SIGKILL a backup that holds the lock and check the kernel released it (no stale lock);
  - run many backups and verify retention;
  - check the systemd timer / service definitions.

Usage: python3 scenarios/os4_4_backup.py
"""

from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import time
from pathlib import Path

import common

SCRIPT = common.PROJECT_ROOT / "scripts" / "backup.sh"


def run_backup(env_extra: dict[str, str], db: Path, wait: bool = True, new_session: bool = False):
    env = dict(os.environ, EDGE_DATABASE_PATH=str(db), **env_extra)
    process = subprocess.Popen(["bash", str(SCRIPT)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, start_new_session=new_session)
    if not wait:
        return process
    out, _ = process.communicate(timeout=60)
    return process.returncode, out


def backups(folder: Path) -> list[Path]:
    return sorted(folder.glob("node-*.db"))


def main() -> int:
    with common.RunningNode({"EDGE_SIM_LATE_PROB": "0"}) as node:
        db = node.node_db
        folder = db.parent / "backups"
        time.sleep(10)
        events_before = common.scalar(db, "SELECT COUNT(*) FROM events")

        # --- two backups at the same moment ----------------------------------------
        first = run_backup({"EDGE_BACKUP_HOLD_S": "4"}, db, wait=False)
        time.sleep(1.0)
        second_code, second_out = run_backup({}, db)
        events_during = common.scalar(db, "SELECT COUNT(*) FROM events")
        first_out, _ = first.communicate(timeout=60)
        files = backups(folder)
        print("  first :", first_out.strip().splitlines()[-1] if first_out.strip() else "(no output)")
        print("  second:", second_out.strip())

        backup_file = files[0] if files else None
        integrity = copies = None
        if backup_file:
            with sqlite3.connect(backup_file) as copy:
                integrity = copy.execute("PRAGMA integrity_check").fetchone()[0]
                copies = copy.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        time.sleep(2)
        events_after = common.scalar(db, "SELECT COUNT(*) FROM events")
        log = node.log_path.read_text(errors="replace")

        # --- SIGKILL a lock holder, then run again ------------------------------------
        holder = run_backup({"EDGE_BACKUP_HOLD_S": "30"}, db, wait=False, new_session=True)
        time.sleep(1.5)
        os.killpg(holder.pid, signal.SIGKILL)     # bash AND its Python child: nobody can unlock cleanly
        holder.wait()
        after_kill_code, after_kill_out = run_backup({}, db)

        # --- retention: many backups, keep 3 -----------------------------------------------
        for _ in range(8):
            run_backup({"EDGE_BACKUP_KEEP": "3"}, db)
        kept = backups(folder)

        unit_dir = common.PROJECT_ROOT / "systemd"
        timer = (unit_dir / "songdo-backup@.timer").read_text()
        service = (unit_dir / "songdo-backup@.service").read_text()
        script_text = SCRIPT.read_text()
        wal = common.query(db, "PRAGMA journal_mode")

        checks = {
            "exactly one of two simultaneous backups ran": len(files) == 1 and "skipped" in second_out.lower(),
            "the refused backup exited cleanly (exit 0, no pile-up)": second_code == 0,
            "the winning backup finished OK": first.returncode == 0 and "Backup OK" in first_out,
            "backup passes PRAGMA integrity_check": integrity == "ok",
            "backup holds the data written before it started": copies is not None and copies >= events_before,
            "no half-written .partial file left behind": not list(folder.glob("*.partial")),
            "the node kept writing during and after the backup": events_during > events_before and events_after > events_during,
            "no 'database is locked' error in the node log": "locked" not in log.lower(),
            "database is in WAL mode": wal and wal[0][0] == "wal",
            "a SIGKILLed lock holder leaves no stale lock (kernel released it)": after_kill_code == 0 and "Backup OK" in after_kill_out,
            "retention keeps only the newest 3 backups": len(kept) == 3,
            "script takes the lock with flock -n": "flock -n" in script_text,
            "timer is periodic and persistent": "OnCalendar=" in timer and "Persistent=true" in timer,
            "service runs scripts/backup.sh as a oneshot": "Type=oneshot" in service and "scripts/backup.sh" in service,
            "node workers all still running": all(w["status"] == "running" for w in common.status()["workers"].values()),
        }
        passed = common.print_checks(checks)
        path = common.write_report("os4_4", {"scenario": "OS4-4", "events_before": events_before, "backup_events": copies,
                                             "events_after": events_after, "checks": checks})
        print(f"Report: {path}")
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
