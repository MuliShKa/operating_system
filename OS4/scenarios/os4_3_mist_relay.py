#!/usr/bin/env python3
"""OS4-3: dust suppression mist cannon relay actuation.

Handbook: activate the mist cannon when PM2.5 exceeds the Korea "Bad" threshold
(> 50 ug/m3); dispatch MIST_CANNON_RELAY with a 30-second TTL.

Timeline: normal air -> dust episode starts -> relay ON -> episode ends ->
relay OFF about 30 s after the LAST high reading (the TTL, a dead-man switch).

Usage: python3 scenarios/os4_3_mist_relay.py
"""

from __future__ import annotations

import time
from datetime import datetime

import common


def epoch(iso_text: str) -> float:
    return datetime.fromisoformat(iso_text).timestamp()


def main() -> int:
    with common.RunningNode({"EDGE_SIM_LATE_PROB": "0"}) as node:   # no late readings: exact timing
        db = node.node_db
        print("Warm-up: normal air for 12 s ...")
        time.sleep(12)
        quiet_relay = common.status()["relay_state"]["state"]
        quiet_decisions = common.scalar(db, "SELECT COUNT(*) FROM decisions WHERE decision_type='MIST_CANNON_RELAY'")

        print(">>> dust episode starts")
        common.sim("episode", True)
        relay_on = common.wait_for(lambda: common.status()["relay_state"]["state"] == "ON", 15)
        time.sleep(10)
        still_on = common.status()["relay_state"]["state"] == "ON"
        applied_during = common.status()["actuator"]["applied"]

        print(">>> dust episode ends (readings drop below 50)")
        common.sim("episode", False)
        off_seen_at = None
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if common.status()["relay_state"]["state"] == "OFF":
                off_seen_at = time.time()
                break
            time.sleep(0.25)

        rows = common.query(db, "SELECT MAX(observed_at) FROM events WHERE event_type='PM25' "
                                "AND json_extract(payload,'$.value') > 50")
        last_high = epoch(rows[0][0]) if rows and rows[0][0] else None
        ttl_seen = off_seen_at - last_high if (off_seen_at and last_high) else None
        max_value_low = common.scalar(db, "SELECT MAX(json_extract(payload,'$.value')) FROM events WHERE event_type='PM25' "
                                          "AND observed_at > ?", (rows[0][0],), default=0) if rows and rows[0][0] else None
        types = dict(common.query(db, "SELECT decision_type, COUNT(*) FROM decisions GROUP BY 1"))
        relay_events = common.query(db, "SELECT json_extract(payload,'$.state') FROM events WHERE event_type='MIST_CANNON_RELAY' ORDER BY observed_at")
        outbox_relay = common.scalar(db, "SELECT COUNT(*) FROM outbox o JOIN events e USING(event_id) WHERE e.event_type='MIST_CANNON_RELAY'")
        print(f"  decisions: {types}")
        print(f"  relay OFF {ttl_seen and round(ttl_seen, 1)} s after the last reading above 50")

        checks = {
            "normal air: relay stays OFF and no dispatch": quiet_relay == "OFF" and quiet_decisions == 0,
            "PM2.5 above 50: relay switched ON within 15 s": bool(relay_on),
            "relay stays ON while high readings keep renewing the command": still_on and applied_during >= 3,
            "dispatch decision MIST_CANNON_RELAY recorded once for the episode": types.get("MIST_CANNON_RELAY") == 1,
            "relay ON recorded by the Actuator (MIST_RELAY_ON)": types.get("MIST_RELAY_ON") == 1,
            "relay switched OFF by itself after the episode": off_seen_at is not None,
            "OFF came 30 s (TTL) after the last high reading (28-34 s)": ttl_seen is not None and 28.0 <= ttl_seen <= 34.0,
            "relay OFF recorded (MIST_RELAY_OFF)": types.get("MIST_RELAY_OFF", 0) >= 1,
            "actuation events (ON then OFF) are queued for the platform": relay_events[:2] == [("ON",), ("OFF",)] and outbox_relay >= 2,
            "every worker still running": all(w["status"] == "running" for w in common.status()["workers"].values()),
        }
        passed = common.print_checks(checks)
        path = common.write_report("os4_3", {"scenario": "OS4-3", "decisions": types, "ttl_after_last_high_s": ttl_seen,
                                             "threshold": 50, "ttl_s": 30, "checks": checks})
        print(f"Report: {path}")
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
