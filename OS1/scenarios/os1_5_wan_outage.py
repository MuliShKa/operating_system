"""
OS1-5: cut the simulated WAN for 10 minutes, keep working offline, reconnect,
and prove that every event reached the receiver exactly once.

The WAN is simulated: the node's wan_online flag stops the SyncWorker from
delivering to the local mock receiver (its own database, node_upstream.db).

Usage: python scenarios/os1_5_wan_outage.py [--minutes 10]
"""

import argparse
import sqlite3
import time
from contextlib import closing

import node_runner

POLL_PERIOD_S = 5.0
DRAIN_TIMEOUT_S = 180.0


def node_counts(run_dir) -> dict:
    with closing(sqlite3.connect(run_dir / "node.db")) as connection:
        events, last_id, pending = connection.execute(
            "SELECT COUNT(*), COALESCE(MAX(outbox_id), 0), "
            "COALESCE(SUM(status = 'pending'), 0) FROM outbox"
        ).fetchone()
        decisions = connection.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
    return {"events": events, "last_id": last_id, "pending": pending, "decisions": decisions}


def received_ids(run_dir) -> list[str]:
    with closing(sqlite3.connect(run_dir / "node_upstream.db")) as connection:
        return [row[0] for row in connection.execute("SELECT event_id FROM received_events")]


def outbox_up_to(run_dir, last_id: int) -> tuple[list[str], int]:
    """Return (all event IDs, number still pending) up to an outbox boundary."""
    with closing(sqlite3.connect(run_dir / "node.db")) as connection:
        rows = connection.execute(
            "SELECT event_id, status FROM outbox WHERE outbox_id <= ?", (last_id,)
        ).fetchall()
    return [row[0] for row in rows], sum(1 for row in rows if row[1] == "pending")


def check_conservation(expected_ids: list[str], received: list[str]) -> dict:
    """Compare what the node had to deliver with what the receiver stored."""
    return {
        "expected": len(expected_ids),
        "received": len(received),
        "lost": len(set(expected_ids) - set(received)),
        "duplicates": len(received) - len(set(received)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--minutes", type=float, default=10, help="length of the outage")
    args = parser.parse_args()

    run_dir = node_runner.new_run_dir("os1_5")
    with node_runner.running_node(run_dir):
        workers_before = node_runner.running_workers(node_runner.get_status())

        print(f"Cutting the WAN for {args.minutes:g} min")
        node_runner.set_wan(False)
        cut_at = time.monotonic()
        # Let a delivery already in progress finish before taking the baseline.
        time.sleep(1)
        before = node_counts(run_dir)
        received_before = len(received_ids(run_dir))

        end = cut_at + args.minutes * 60
        while time.monotonic() < end:
            time.sleep(min(POLL_PERIOD_S, max(0.0, end - time.monotonic())))
            counts = node_counts(run_dir)
            print(f"  offline: pending={counts['pending']} decisions={counts['decisions']}", flush=True)

        # Boundary: everything up to this outbox_id must be delivered after reconnect.
        during = node_counts(run_dir)
        received_during = len(received_ids(run_dir))
        status_during = node_runner.get_status()
        node_runner.set_wan(True)
        restored_at = time.monotonic()
        print("WAN restored, draining the backlog")

        while time.monotonic() - restored_at < DRAIN_TIMEOUT_S:
            if outbox_up_to(run_dir, during["last_id"])[1] == 0:
                break
            time.sleep(0.5)
        drain_s = round(time.monotonic() - restored_at, 1)

    expected, still_pending = outbox_up_to(run_dir, during["last_id"])
    conservation = check_conservation(expected, received_ids(run_dir))
    checks = {
        "no worker crashed or changed PID":
            node_runner.running_workers(status_during) == workers_before,
        "API and dashboard answered while offline": status_during["wan_online"] is False,
        "events kept arriving offline": during["events"] > before["events"],
        "decisions kept being made offline": during["decisions"] > before["decisions"],
        "nothing delivered while offline": received_during == received_before,
        "backlog fully drained": still_pending == 0,
        "no event lost": conservation["lost"] == 0,
        "no duplicate": conservation["duplicates"] == 0,
    }
    report = {
        "scenario": "OS1-5",
        "minutes": args.minutes,
        "outage_seconds": round(restored_at - cut_at, 1),
        "backlog_events": during["pending"],
        "events_during_outage": during["events"] - before["events"],
        "decisions_during_outage": during["decisions"] - before["decisions"],
        "drain_seconds": drain_s,
        "conservation": conservation,
        "checks": checks,
    }
    path = node_runner.write_report(run_dir, report)
    for key in ("outage_seconds", "backlog_events", "drain_seconds", "conservation"):
        print(f"{key}: {report[key]}")
    passed = node_runner.print_checks(checks)
    print(f"Report: {path}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
