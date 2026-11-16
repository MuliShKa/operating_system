#!/usr/bin/env python3
"""OS4-5: WAN outage backlog drain and AirKorea baseline benchmark.

Signature demonstration: "Disconnect Internet -> system continues operating."

  1. Start the node (throwaway databases), let it deliver online for a while.
  2. Cut the SIMULATED WAN for --offline-seconds (default 600 = 10 minutes).
     Every worker must keep running, readings keep being stored, the mist rule keeps
     deciding, the AirKorea benchmark keeps running from the LOCAL cached file, and
     nothing reaches the receiver.
  3. Restore the WAN; the outbox backlog must drain.
  4. Re-send one delivered event: the receiver must ignore the duplicate (idempotent).
  5. Pause the sensors and wait for an EMPTY outbox: then every event the node ever
     produced must be acknowledged by the receiver (the Urban Data Platform): 100 %.

Usage: python3 scenarios/os4_5_offline_demo.py                      # 10 minutes offline
       python3 scenarios/os4_5_offline_demo.py --offline-seconds 60  # quick check
"""

from __future__ import annotations

import argparse
import json
import time
from urllib.request import Request, urlopen

import common

RECEIVER_URL = f"http://127.0.0.1:{common.os.environ.get('EDGE_RECEIVER_PORT', '8001')}/api/events"
EXPECTED_EVENTS_PER_SECOND = 1.7      # NOISE 1/s + PM25 0.5/s + LUX 0.2/s


def ids(db, sql) -> set[str]:
    return {row[0] for row in common.query(db, sql)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline-seconds", type=int, default=600)
    parser.add_argument("--drain-timeout", type=int, default=240)
    args = parser.parse_args()

    # Auto episodes ON: the mist rule has real work to do while offline.
    env = {"EDGE_SIM_AUTO_EPISODES": "1"}
    rows: list[tuple[str, str, str]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        rows.append(("PASS" if passed else "FAIL", name, detail))

    with common.RunningNode(env) as node:
        db, rdb = node.node_db, node.receiver_db

        def received() -> int:
            return common.scalar(rdb, "SELECT COUNT(*) FROM received_events")

        # --- 1. online warm-up ------------------------------------------------------
        got_events = common.wait_for(lambda: received() > 0, 30)
        check("online delivery works before the cut", bool(got_events), f"receiver holds {received()} events")
        expected_workers = len(common.status()["workers"])

        # --- 2. WAN cut ---------------------------------------------------------------
        print(f"\n>>> WAN CUT for {args.offline_seconds} s")
        common.api_post("/api/wan/offline")
        time.sleep(2)
        ev0 = common.scalar(db, "SELECT COUNT(*) FROM events")
        pend0 = common.scalar(db, "SELECT COUNT(*) FROM outbox WHERE status='pending'")
        dec0 = common.scalar(db, "SELECT COUNT(*) FROM decisions")
        base0 = common.scalar(db, "SELECT COUNT(*) FROM baseline_checks")
        rec0 = received()
        always_running, first_problem, wan_stayed_cut = True, "", True
        began = time.monotonic()
        next_print = 0.0
        while time.monotonic() - began < args.offline_seconds:
            elapsed = time.monotonic() - began
            try:
                st = common.status()
                running = sum(1 for w in st["workers"].values() if w["status"] == "running")
                if running != expected_workers:
                    always_running, first_problem = False, first_problem or f"{elapsed:.0f} s ({running}/{expected_workers})"
                if st["wan_online"]:
                    wan_stayed_cut = False
            except Exception as error:   # API unreachable
                always_running, first_problem = False, first_problem or f"{elapsed:.0f} s ({error})"
            if elapsed >= next_print:
                print(f"  t={elapsed:5.0f}s events={common.scalar(db, 'SELECT COUNT(*) FROM events'):5d} "
                      f"pending={common.scalar(db, 'SELECT COUNT(*) FROM outbox WHERE status=' + chr(39) + 'pending' + chr(39)):5d} "
                      f"receiver={received():5d}", flush=True)
                next_print += 15
            time.sleep(1)

        ev1 = common.scalar(db, "SELECT COUNT(*) FROM events")
        pend1 = common.scalar(db, "SELECT COUNT(*) FROM outbox WHERE status='pending'")
        new_events = ev1 - ev0
        expected = EXPECTED_EVENTS_PER_SECOND * args.offline_seconds
        check("the WAN stayed cut for the whole window", wan_stayed_cut, "nobody pressed Restore during the run")
        check("every worker kept running during the outage", always_running,
              f"{expected_workers}/{expected_workers} running at every sample" if always_running else f"first problem at {first_problem}")
        check("local sensing and storage continued", new_events >= 0.7 * expected, f"{new_events} events stored offline (about {expected:.0f} expected)")
        check("nothing was delivered while offline", received() == rec0, f"receiver {rec0} -> {received()}")
        check("outbox accumulated every offline event", pend1 - pend0 >= 0.95 * new_events, f"pending {pend0} -> {pend1} for {new_events} new events")
        if args.offline_seconds >= 60:
            new_dec = common.scalar(db, "SELECT COUNT(*) FROM decisions") - dec0
            check("local decisions continued (mist rule)", new_dec >= 1, f"{new_dec} decisions recorded while offline")
        new_base = common.scalar(db, "SELECT COUNT(*) FROM baseline_checks") - base0
        check("AirKorea benchmark kept running offline from the local cache", new_base >= 1, f"{new_base} baseline checks while offline")

        # --- 3. reconnect and drain ----------------------------------------------------
        print("\n>>> WAN RESTORED: draining the backlog")
        common.api_post("/api/wan/online")
        drain_started = time.monotonic()
        common.wait_for(lambda: common.scalar(db, "SELECT COUNT(*) FROM outbox WHERE status='pending'") <= 6, args.drain_timeout, 1)
        left = common.scalar(db, "SELECT COUNT(*) FROM outbox WHERE status='pending'")
        check("backlog drained after reconnect", left <= 6,
              f"pending {pend1} -> {left} in {time.monotonic() - drain_started:.0f} s (a few live events may still be arriving)")

        # --- 4. idempotent receiver -------------------------------------------------------
        sent = common.query(db, "SELECT event_id, payload FROM outbox WHERE status='sent' LIMIT 1")
        if sent:
            before = received()
            request = Request(RECEIVER_URL, data=json.dumps({"event_id": sent[0][0], "payload": json.loads(sent[0][1])}).encode(),
                              headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(request, timeout=3) as response:
                answer = json.loads(response.read())
            check("receiver ignores a replayed event (idempotent)", answer.get("duplicate") is True and received() == before,
                  f"replay answered duplicate={answer.get('duplicate')}, receiver count {before} -> {received()}")
        else:
            check("receiver ignores a replayed event (idempotent)", False, "no sent event to replay")

        # --- 5. 100 % acknowledgement: silence the sensors, wait for an empty outbox ---------------
        common.sim("pause", True)
        common.sim("episode", False)

        def settled() -> bool:
            a = common.scalar(db, "SELECT COUNT(*) FROM events")
            time.sleep(4)
            return common.scalar(db, "SELECT COUNT(*) FROM outbox WHERE status='pending'") == 0 and \
                common.scalar(db, "SELECT COUNT(*) FROM events") == a

        empty = common.wait_for(settled, 90, 0.5)
        all_events = ids(db, "SELECT event_id FROM events")
        outbox_ids = ids(db, "SELECT event_id FROM outbox")
        sent_ids = ids(db, "SELECT event_id FROM outbox WHERE status='sent'")
        received_ids = ids(rdb, "SELECT event_id FROM received_events")
        check("outbox is empty once the sensors are paused", bool(empty), f"{len(all_events)} events, {len(outbox_ids - sent_ids)} still pending")
        check("no event lost locally (every event has an outbox row)", all_events == outbox_ids, f"{len(all_events)} events, {len(outbox_ids)} outbox rows")
        check("100 % delivery acknowledgement: every event is at the receiver", all_events == received_ids,
              f"{len(received_ids & all_events)} of {len(all_events)} events acknowledged ({100 * len(received_ids & all_events) / max(1, len(all_events)):.1f} %)")
        check("nothing at the receiver that the node did not produce", not (received_ids - all_events), f"{len(received_ids - all_events)} unknown IDs")

        # --- 6. AirKorea benchmark ------------------------------------------------------------
        baseline = common.query(db, "SELECT station, source, is_sample, match_kind, baseline_pm25, local_median, bias, local_grade, baseline_grade, status "
                                    "FROM baseline_checks ORDER BY check_id")
        agree = sum(1 for b in baseline if b[9] == "AGREE")
        if baseline:
            last = baseline[-1]
            print(f"\nBenchmark vs station {last[0]} ({last[1]}, {'SAMPLE DATA' if last[2] else 'real data'}): "
                  f"{len(baseline)} checks, {agree} AGREE; last local {last[5]} vs station {last[4]} (bias {last[6]:+}, {last[7]}/{last[8]})")
        check("benchmark compared local PM2.5 with station 131233", len(baseline) >= 2 and all(b[0] == "131233" for b in baseline),
              f"{len(baseline)} comparisons stored; source={baseline[-1][1] if baseline else 'none'}; "
              + ("SAMPLE DATA: synthetic, not the real station" if baseline and baseline[-1][2] else "real cached station data"))
        # The simulator tracks the station's typical level, so quiet periods should agree with it.
        check("most benchmark checks agree within tolerance", bool(baseline) and agree >= 0.5 * len(baseline), f"{agree}/{len(baseline)} AGREE")

    ok = all(status != "FAIL" for status, _, _ in rows)
    print("\n" + "=" * 78 + "\nOS4-5 OFFLINE DEMONSTRATION REPORT\n" + "=" * 78)
    for status, name, detail in rows:
        print(f"[{status}] {name}\n        {detail}")
    print("=" * 78)
    print("RESULT:", "ALL CHECKS PASSED" if ok else f"{sum(s == 'FAIL' for s, _, _ in rows)} CHECK(S) FAILED")
    path = common.write_report("os4_5", {"scenario": "OS4-5", "offline_seconds": args.offline_seconds, "passed": ok,
                                         "checks": [{"status": s, "name": n, "detail": d} for s, n, d in rows]})
    print(f"Report: {path}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
