#!/usr/bin/env python3
"""OS3-4: transactional state update and version guarding.

Handbook: atomic state transitions guarded by SQLite WAL transactions. ACID
and version increments prevent torn reads across processes.

Several writer PROCESSES flip the sign between 50 and 30 km/h with the
version-guarded UPDATE, while reader PROCESSES keep reading the state.
Invariant: every successful write flips the limit AND adds 1 to the version,
so a consistent snapshot always satisfies "limit == 30  <=>  version is odd".
A torn read (new limit with old version, or the reverse) would break it.

Checks: final version == total successful writes (no lost update), 0 invariant
violations seen by readers, rejected stale writers were counted, WAL mode,
all processes exit with code 0.

Usage: python3 scenarios/os3_4_transactional.py [--writers 4] [--readers 2] [--writes 200]
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import common

sys.path.insert(0, str(common.SRC_DIR))


def writer(writes: int, results) -> None:
    from edge import storage  # imported here: reads EDGE_DATABASE_PATH from the environment
    done = rejected = 0
    while done < writes:
        state = storage.get_sign_state()
        target = 30 if state["speed_limit_kmh"] == 50 else 50
        if storage.update_sign_state(target, state["version"]):
            done += 1
        else:
            rejected += 1  # somebody else won this version: re-read and decide again
    results.put(("writer", done, rejected))


def reader(stop, results) -> None:
    from edge import storage
    reads = violations = 0
    while not stop.is_set():
        state = storage.get_sign_state()
        reads += 1
        if (state["speed_limit_kmh"] == 30) != (state["version"] % 2 == 1):
            violations += 1
    results.put(("reader", reads, violations))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--writers", type=int, default=4)
    parser.add_argument("--readers", type=int, default=2)
    parser.add_argument("--writes", type=int, default=200, help="successful writes per writer")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "os3_4.db"
        os.environ["EDGE_DATABASE_PATH"] = str(db_path)   # children inherit it
        from edge import storage
        storage.initialize_database()

        ctx = mp.get_context("spawn")
        results = ctx.Queue()
        stop = ctx.Event()
        writers = [ctx.Process(target=writer, args=(args.writes, results)) for _ in range(args.writers)]
        readers = [ctx.Process(target=reader, args=(stop, results)) for _ in range(args.readers)]
        for process in readers + writers:
            process.start()
        for process in writers:
            process.join()
        stop.set()
        for process in readers:
            process.join()

        rows = [results.get(timeout=10) for _ in range(args.writers + args.readers)]
        final = storage.get_sign_state()
        db = sqlite3.connect(db_path)
        journal_mode = db.execute("PRAGMA journal_mode").fetchone()[0]
        db.close()

    done = sum(r[1] for r in rows if r[0] == "writer")
    rejected = sum(r[2] for r in rows if r[0] == "writer")
    reads = sum(r[1] for r in rows if r[0] == "reader")
    violations = sum(r[2] for r in rows if r[0] == "reader")
    total = args.writers * args.writes
    print(f"  writes ok={done} rejected(stale)={rejected} final={final} reads={reads} torn={violations}")

    checks = {
        "every writer completed its writes": done == total,
        "final version == successful writes (no lost update)": final["version"] == total,
        "final state matches the version parity":
            (final["speed_limit_kmh"] == 30) == (final["version"] % 2 == 1),
        "readers saw 0 torn states": violations == 0 and reads > 0,
        "stale writers were rejected, not applied (contention happened)": rejected > 0,
        "database is in WAL mode": journal_mode.lower() == "wal",
        "all processes exited cleanly": all(p.exitcode == 0 for p in writers + readers),
    }
    passed = common.print_checks(checks)
    path = common.write_report("os3_4", {
        "scenario": "OS3-4", "writers": args.writers, "readers": args.readers,
        "writes_total": total, "rejected": rejected, "reads": reads, "torn_reads": violations,
        "final_state": final, "journal_mode": journal_mode, "checks": checks,
    })
    print(f"Report: {path}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
