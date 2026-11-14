#!/usr/bin/env python3
"""Scenario OS3-5: offline variable speed sign dispatch and event replay.

Signature demonstration: "Disconnect Internet -> system continues operating."

What this script does (everything runs locally, nothing touches the real internet):
  1. Starts the node with throwaway databases.
  2. Cuts the SIMULATED WAN for --offline-seconds (default 600 = 10 minutes).
  3. Checks that every worker keeps running, events keep being stored, surge
     decisions keep being taken, and nothing reaches the receiver.
  4. Restores the WAN and waits for the outbox backlog to drain.
  5. Re-sends one delivered event to prove the receiver deduplicates.
  6. Stops the node and checks event conservation from the databases:
     no event lost, nothing marked 'sent' that the receiver does not have,
     nothing at the receiver that the node never produced.

Run (from the project root, on Linux):
    python3 scenarios/os3_5_offline_demo.py                    # full 10-minute demo
    python3 scenarios/os3_5_offline_demo.py --offline-seconds 60   # quick check

Exit code 0 = every check passed.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:8000"
RECEIVER = "http://127.0.0.1:8001/api/events"
EXPECTED_WORKERS = 6
SETTLE_SECONDS = 2.0        # let an in-flight delivery finish after the WAN cut
EVENTS_PER_SECOND = 2       # SensorGen produces 2 readings per second


# --------------------------------------------------------------------------- helpers

def api_get(path: str) -> dict:
    with urlopen(API + path, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def api_post(path: str) -> dict:
    request = Request(API + path, data=b"", method="POST")
    with urlopen(request, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def api_is_up() -> bool:
    try:
        api_get("/api/status")
        return True
    except (URLError, OSError, ValueError):
        return False


def scalar(db: Path, sql: str, default: int = 0) -> int:
    """Run a COUNT-style query; return `default` if the database is not ready yet."""
    try:
        with sqlite3.connect(db, timeout=10) as connection:
            row = connection.execute(sql).fetchone()
        return int(row[0]) if row else default
    except sqlite3.Error:
        return default


def id_set(db: Path, sql: str) -> set[str]:
    with sqlite3.connect(db, timeout=10) as connection:
        return {row[0] for row in connection.execute(sql)}


class Snapshot:
    """Counters read at one moment from both databases."""

    def __init__(self, node_db: Path, receiver_db: Path) -> None:
        self.time = time.monotonic()
        self.events = scalar(node_db, "SELECT COUNT(*) FROM events")
        self.pending = scalar(node_db, "SELECT COUNT(*) FROM outbox WHERE status='pending'")
        self.decisions = scalar(node_db, "SELECT COUNT(*) FROM decisions")
        self.received = scalar(receiver_db, "SELECT COUNT(*) FROM received_events")


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []  # (status, name, detail)

    def check(self, name: str, passed: bool, detail: str) -> bool:
        self.rows.append(("PASS" if passed else "FAIL", name, detail))
        return passed

    def skip(self, name: str, detail: str) -> None:
        self.rows.append(("SKIP", name, detail))

    def print(self) -> None:
        print("\n" + "=" * 78)
        print("OS3-5 OFFLINE DEMONSTRATION REPORT")
        print("=" * 78)
        for status, name, detail in self.rows:
            print(f"[{status}] {name}\n        {detail}")
        failed = sum(1 for status, _, _ in self.rows if status == "FAIL")
        print("=" * 78)
        print("RESULT:", "ALL CHECKS PASSED" if failed == 0 else f"{failed} CHECK(S) FAILED")

    @property
    def ok(self) -> bool:
        return all(status != "FAIL" for status, _, _ in self.rows)


def pick_python() -> str:
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    return str(venv_python) if venv_python.exists() else sys.executable


def stop_node(node: subprocess.Popen) -> None:
    """Ask the supervisor to stop (SIGINT, like Ctrl+C); kill it only if it hangs."""
    if node.poll() is not None:
        return
    node.send_signal(signal.SIGINT)
    try:
        node.wait(timeout=20)
    except subprocess.TimeoutExpired:
        node.kill()
        node.wait()


# --------------------------------------------------------------------------- demo

def run(offline_seconds: int, tail: int, drain_timeout: int) -> bool:
    if api_is_up():
        print("A node is already answering on 127.0.0.1:8000. Stop it first (Ctrl+C) and retry.")
        return False

    report = Report()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        node_db = tmp_dir / "node.db"
        receiver_db = tmp_dir / "receiver.db"
        log_path = tmp_dir / "node.log"

        env = dict(os.environ)
        env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
        env["EDGE_DATABASE_PATH"] = str(node_db)
        env["EDGE_RECEIVER_DATABASE_PATH"] = str(receiver_db)

        print(f"Starting node (throwaway databases in {tmp_dir}) ...")
        with open(log_path, "wb") as log:
            node = subprocess.Popen(
                [pick_python(), "-m", "edge.supervisor"],
                cwd=PROJECT_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            )
            try:
                return _scenario(node, node_db, receiver_db, log_path, report,
                                 offline_seconds, tail, drain_timeout)
            finally:
                stop_node(node)


def _scenario(node, node_db, receiver_db, log_path, report,
              offline_seconds, tail, drain_timeout) -> bool:
    # --- 1. startup and warm-up while the WAN is ONLINE -------------------------
    deadline = time.monotonic() + 30
    while not api_is_up():
        if node.poll() is not None or time.monotonic() > deadline:
            print("The node did not start. Log tail:\n" + log_path.read_text(errors="replace")[-1500:])
            return False
        time.sleep(0.5)

    deadline = time.monotonic() + 30
    while scalar(receiver_db, "SELECT COUNT(*) FROM received_events") == 0:
        if time.monotonic() > deadline:
            report.check("online delivery works before the cut", False,
                         "receiver got no event within 30 s")
            report.print()
            return False
        time.sleep(1)
    report.check("online delivery works before the cut", True,
                 "receiver is receiving events while the WAN is online")

    # --- 2. cut the WAN ---------------------------------------------------------
    print(f"\n>>> WAN CUT for {offline_seconds} s")
    api_post("/api/wan/offline")
    time.sleep(SETTLE_SECONDS)
    start = Snapshot(node_db, receiver_db)

    workers_always_running = True
    crashed_at = ""
    offline_started = time.monotonic()
    next_print = 0.0
    while time.monotonic() - offline_started < offline_seconds:
        elapsed = time.monotonic() - offline_started
        try:
            status = api_get("/api/status")
            running = sum(1 for w in status["workers"].values() if w["status"] == "running")
            if running != EXPECTED_WORKERS or node.poll() is not None:
                workers_always_running = False
                crashed_at = crashed_at or f"{elapsed:.0f} s ({running}/{EXPECTED_WORKERS} running)"
            sign = status.get("sign_state") or {}
        except (URLError, OSError, ValueError):
            workers_always_running = False
            crashed_at = crashed_at or f"{elapsed:.0f} s (API unreachable)"
            sign = {}
        if elapsed >= next_print:
            now = Snapshot(node_db, receiver_db)
            print(f"  t={elapsed:5.0f}s  events={now.events:5d}  pending={now.pending:5d}  "
                  f"receiver={now.received:5d}  sign={sign.get('speed_limit_kmh', '?')} km/h")
            next_print += 10
        time.sleep(1)

    end = Snapshot(node_db, receiver_db)
    new_events = end.events - start.events
    expected = EVENTS_PER_SECOND * offline_seconds

    report.check("every worker kept running during the outage", workers_always_running,
                 "6/6 workers running at every sample" if workers_always_running
                 else f"problem first seen at {crashed_at}")
    report.check("local processing continued (sensing + storage)", new_events >= 0.5 * expected,
                 f"{new_events} events stored while offline (about {expected} expected)")
    report.check("nothing was delivered while offline", end.received == start.received,
                 f"receiver count {start.received} -> {end.received}")
    report.check("outbox accumulated every offline event",
                 (end.pending - start.pending) >= 0.9 * new_events,
                 f"pending {start.pending} -> {end.pending} (+{end.pending - start.pending}) "
                 f"for {new_events} new events")
    if offline_seconds >= 45:
        new_decisions = end.decisions - start.decisions
        report.check("local decisions continued (speed sign)", new_decisions >= 1,
                     f"{new_decisions} sign decisions recorded while offline")
    else:
        report.skip("local decisions continued (speed sign)",
                    "offline window shorter than 45 s, so no pedestrian surge is guaranteed")

    # --- 3. restore the WAN and drain -------------------------------------------
    print("\n>>> WAN RESTORED: waiting for the backlog to drain")
    api_post("/api/wan/online")
    drain_started = time.monotonic()
    while True:
        now = Snapshot(node_db, receiver_db)
        if now.pending <= tail:
            break
        if time.monotonic() - drain_started > drain_timeout:
            break
        time.sleep(1)
    drained = now.pending <= tail
    report.check("backlog drained after reconnect", drained,
                 f"pending {end.pending} -> {now.pending} in {time.monotonic() - drain_started:.0f} s "
                 f"(live tail of up to {tail} events is normal: new readings keep arriving)")

    # --- 4. idempotent receiver -------------------------------------------------
    with sqlite3.connect(node_db, timeout=10) as connection:
        row = connection.execute(
            "SELECT event_id, payload FROM outbox WHERE status='sent' LIMIT 1"
        ).fetchone()
    if row:
        before = scalar(receiver_db, "SELECT COUNT(*) FROM received_events")
        request = Request(
            RECEIVER,
            data=json.dumps({"event_id": row[0], "payload": json.loads(row[1])}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urlopen(request, timeout=3) as response:
            answer = json.loads(response.read().decode("utf-8"))
        after = scalar(receiver_db, "SELECT COUNT(*) FROM received_events")
        report.check("receiver ignores a replayed event (idempotent)",
                     answer.get("duplicate") is True and after == before,
                     f"replay answered duplicate={answer.get('duplicate')}, receiver count {before} -> {after}")
    else:
        report.check("receiver ignores a replayed event (idempotent)", False,
                     "no 'sent' event available to replay")

    # --- 5. stop the node, then verify conservation from the databases ------------
    print("\n>>> Stopping the node and verifying event conservation")
    stop_node(node)
    all_events = id_set(node_db, "SELECT event_id FROM events")
    outbox_ids = id_set(node_db, "SELECT event_id FROM outbox")
    sent_ids = id_set(node_db, "SELECT event_id FROM outbox WHERE status='sent'")
    pending_ids = id_set(node_db, "SELECT event_id FROM outbox WHERE status='pending'")
    received_ids = id_set(receiver_db, "SELECT event_id FROM received_events")

    lost = all_events - outbox_ids
    sent_missing = sent_ids - received_ids
    strangers = received_ids - all_events
    report.check("no event lost locally", not lost,
                 f"{len(all_events)} events stored, {len(outbox_ids)} queued in the outbox, {len(lost)} missing")
    report.check("everything marked 'sent' really reached the receiver", not sent_missing,
                 f"{len(sent_ids)} sent, {len(sent_missing)} not found at the receiver")
    report.check("receiver holds nothing the node did not produce", not strangers,
                 f"{len(received_ids)} at the receiver, {len(strangers)} unknown IDs")
    report.check("conservation: events = delivered + still pending",
                 all_events == (received_ids | pending_ids),
                 f"{len(all_events)} events = {len(received_ids)} delivered + {len(pending_ids)} pending "
                 f"(pending ones are the live tail and will be sent on the next run)")

    report.print()
    return report.ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Scenario OS3-5 offline demonstration")
    parser.add_argument("--offline-seconds", type=int, default=600,
                        help="how long the WAN stays cut (default 600 = 10 minutes)")
    parser.add_argument("--tail", type=int, default=6,
                        help="pending events still allowed after the drain (live tail)")
    parser.add_argument("--drain-timeout", type=int, default=180,
                        help="seconds to wait for the backlog to drain")
    args = parser.parse_args()
    return 0 if run(args.offline_seconds, args.tail, args.drain_timeout) else 1


if __name__ == "__main__":
    raise SystemExit(main())
