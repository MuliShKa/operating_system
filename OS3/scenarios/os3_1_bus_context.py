#!/usr/bin/env python3
"""OS3-1: Incheon bus stop context and vehicle speed telemetry.

Handbook: ingest public transport context and vehicle speed telemetry, load
CACHED Incheon BIS route data, and correlate it with crosswalk pedestrian counts.

Checks:
  - the cached bus stop file is read from LOCAL disk and nearby stops are found;
  - vehicle speed telemetry (RADAR_SPEED) and pedestrian counts are stored;
  - the bus context still works while the WAN is cut (it never needs the internet);
  - a pedestrian surge decision carries the nearest bus stop (the correlation).

The sample file is synthetic and the report says so. Real data: put the cached
CSV at sources/incheon_bis_stops.csv.

Usage: python3 scenarios/os3_1_bus_context.py [--seconds 45]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time

import common

sys.path.insert(0, str(common.SRC_DIR))



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seconds", type=int, default=45,
                        help="how long to observe the node (a surge starts after ~30 s)")
    args = parser.parse_args()

    with common.RunningNode() as node:
        time.sleep(5)
        status = common.api_get("/api/status")
        context = status.get("bus_context") or {}

        # Cut the WAN: the bus context must keep working (it is read from disk).
        common.api_post("/api/wan/offline")
        remaining = max(0, args.seconds - 5)
        print(f"Observing the node for {remaining} s with the WAN cut ...")
        time.sleep(remaining)
        offline_status = common.api_get("/api/status")
        offline_context = offline_status.get("bus_context") or {}

        readings = offline_status.get("recent_readings", [])
        decisions = offline_status.get("recent_decisions", [])

        db = sqlite3.connect(node.node_db, timeout=10)
        try:
            stored = {sensor: count for sensor, count in db.execute(
                "SELECT event_type, COUNT(*) FROM events GROUP BY event_type")}
            surge_reasons = [row[0] for row in db.execute(
                "SELECT reason FROM decisions WHERE decision_type = 'VARIABLE_SPEED_SIGN_KMH'")]
        finally:
            db.close()

    checks = {
        "bus stops were loaded from a local cached file":
            context.get("source", "none") != "none" and context.get("total_stops", 0) > 0,
        "at least one stop is near the intersection":
            context.get("nearby_count", 0) >= 1,
        "unusable rows of the file are counted, not hidden":
            isinstance(context.get("skipped_rows"), int),
        "vehicle speed telemetry (RADAR_SPEED) is stored":
            stored.get("RADAR_SPEED", 0) >= 1,
        "pedestrian counts (PED_CROSSWALK_COUNT) are stored":
            stored.get("PED_CROSSWALK_COUNT", 0) >= 1,
        "bus context still served while the WAN is cut":
            offline_context.get("nearby_count", 0) >= 1 and offline_status.get("wan_online") is False,
        "readings kept arriving while the WAN was cut":
            len(readings) >= 2,
    }
    if args.seconds >= 45:
        checks["a pedestrian surge decision names the nearest bus stop (correlation)"] = any(
            "nearest bus stop" in (reason or "") for reason in surge_reasons)

    print(f"Bus context: {context.get('nearby_count')} stop(s) within {context.get('radius_m')} m "
          f"of the node, source={context.get('source')} "
          f"({'SYNTHETIC SAMPLE' if context.get('is_sample') else 'cached BIS data'}), "
          f"skipped rows={context.get('skipped_rows')}, swapped lat/lon rows={context.get('swapped_rows')}, routes file={context.get('routes_source')}")
    print(f"Stored events: {stored}")
    for reason in surge_reasons[:2]:
        print(f"  decision reason: {reason}")

    passed = common.print_checks(checks)
    path = common.write_report("os3_1", {
        "scenario": "OS3-1", "seconds": args.seconds, "bus_context": context,
        "is_sample_data": context.get("is_sample"), "stored_events": stored,
        "surge_reasons": surge_reasons, "checks": checks,
    })
    print(f"Report: {path}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
