#!/usr/bin/env python3
"""OS4-2: event time vs receipt time (out-of-order delivery from delayed sensor nodes).

Handbook OS concept: preserve `observed_at` event timestamps independently of the
system's `received_at`.

Phase A (deterministic): we play the part of a delayed sensor node and send PM2.5
datagrams whose observed_at we choose, in a deliberately scrambled ARRIVAL order,
including an old, very high reading that arrives late.
Phase B: we send a fresh high reading that is 4 s old and watch the 30 s TTL being
counted from its EVENT time (about 26 s of life left, not 30).
Phase C (statistical): the built-in simulator delays half of all readings.

Usage: python3 scenarios/os4_2_event_time.py
"""

from __future__ import annotations

import sys
import time

import common

sys.path.insert(0, str(common.SRC_DIR))
from edge.processor import iso  # noqa: E402


def main() -> int:
    env = {"EDGE_SIM_LATE_PROB": "0.5", "EDGE_SIM_MAX_LATE_S": "6"}
    with common.RunningNode(env) as node:
        common.sim("mute_pm25", True)       # phases A and B: only our injected PM2.5 exists
        time.sleep(1)
        db = node.node_db

        # ---------------- Phase A: scrambled arrival order ---------------------------
        t = time.time()
        arrival = [(t - 6, 20.0), (t - 1, 22.0), (t - 5, 95.0), (t - 3, 21.0)]   # (observed_at, value)
        for observed_at, value in arrival:
            common.inject("PM25", value, observed_at, node.socket_dir)
            time.sleep(0.15)
        time.sleep(2)

        rows = common.query(db, "SELECT observed_at, received_at, json_extract(payload,'$.value') "
                                "FROM events WHERE event_type='PM25'")
        by_receipt = [r[2] for r in sorted(rows, key=lambda r: r[1])]
        by_event = [r[2] for r in sorted(rows, key=lambda r: r[0])]
        stored_observed = {r[0] for r in rows}
        sent_observed = {iso(o) for o, _ in arrival}
        st = common.status()
        print(f"  arrival order values : {by_receipt}")
        print(f"  event-time order     : {by_event}")

        # ---------------- Phase B: TTL counted from event time ---------------------------
        time.sleep(3)   # so that 'now - 4 s' is NEWER than every Phase A reading
        sent_at = time.monotonic()
        common.inject("PM25", 80.0, time.time() - 4, node.socket_dir)
        relay_on = common.wait_for(lambda: common.status()["relay_state"]["state"] == "ON", 5)
        decisions = common.status()["recent_decisions"]
        mist = [d for d in decisions if d["action"] == "MIST_CANNON_RELAY"]
        expires_in = mist[-1]["expires_in_seconds"] if mist else None

        # Keep the channel healthy with LOW readings; they must NOT switch the relay off.
        relay_off_at = None
        while time.monotonic() - sent_at < 40:
            common.inject("PM25", 20.0, time.time(), node.socket_dir)
            if common.status()["relay_state"]["state"] == "OFF":
                relay_off_at = time.monotonic() - sent_at
                break
            time.sleep(1.5)
        print(f"  relay ON; command had {expires_in} s left; relay went OFF after {relay_off_at and round(relay_off_at, 1)} s")

        # ---------------- Phase C: simulator with 50 % delayed readings ---------------------
        marker = iso(time.time())
        common.sim("mute_pm25", False)
        time.sleep(30)
        sim_rows, inversions = [], 0
        for sensor in ("PM25", "NOISE"):   # NOISE ticks every second: many more chances to see reordering
            rows_s = common.query(db, "SELECT observed_at, received_at FROM events WHERE event_type=? AND received_at >= ? "
                                      "ORDER BY received_at", (sensor, marker))
            inversions += sum(1 for a, b in zip(rows_s, rows_s[1:]) if b[0] < a[0])
            sim_rows += rows_s
        st3 = common.status()

        checks = {
            "arrival order differs from event-time order (really out of order)": by_receipt != by_event,
            "event-time order is the order the sensor measured": by_event == [20.0, 95.0, 21.0, 22.0],
            "observed_at stored exactly as the sensor sent it": stored_observed == sent_observed,
            "received_at kept separately and never earlier than observed_at":
                all(r[1] >= r[0] for r in rows) and all(r[0] != r[1] for r in rows),
            "late readings counted as out of order (2 of 4)": st["channels"]["PM25"]["out_of_order"] == 2,
            "an old high reading that arrives late does NOT start the mist cannon":
                not any(d["action"] == "MIST_CANNON_RELAY" for d in decisions[:0] + st["recent_decisions"])
                and not any(a["action"] == "MIST_RELAY_ON" for a in st["recent_actuations"]),
            "a fresh high reading (newest by event time) DOES start it": bool(relay_on),
            "its TTL is counted from event time (about 26 s left, not 30)": expires_in is not None and 24.0 <= expires_in <= 27.5,
            "low readings do not switch the relay off; only the TTL does":
                relay_off_at is not None and 22.0 <= relay_off_at <= 30.0,
            "simulator: readings really arrived out of order": inversions > 0,
            "simulator: lateness was measured": st3["channels"]["PM25"]["max_lateness_s"] > 0.5,
            "simulator: no reading has observed_at after received_at": all(o <= r for o, r in sim_rows),
        }
        print(f"  simulator phase: {len(sim_rows)} PM2.5+noise readings, {inversions} arrival inversions")
        passed = common.print_checks(checks)
        path = common.write_report("os4_2", {
            "scenario": "OS4-2", "arrival_order_values": by_receipt, "event_order_values": by_event,
            "command_expires_in_s": expires_in, "relay_off_after_s": relay_off_at,
            "sim_readings": len(sim_rows), "sim_inversions": inversions, "checks": checks})
        print(f"Report: {path}")
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
