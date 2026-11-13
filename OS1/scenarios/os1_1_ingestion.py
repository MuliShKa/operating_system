"""
OS1-1: local room sensor ingestion with the cached building inventory.

Starts an isolated node, lets it ingest CO2 and temperature readings, then
checks the database: inventory loaded from the cache file, the node located
in a building, every reading stored and tagged with that building, units
right, values in range, and the handbook view sensor_events readable.

Usage: python scenarios/os1_1_ingestion.py [--seconds 10]
"""

import argparse
import json
import sqlite3
import sys
import time
from contextlib import closing

import node_runner

sys.path.insert(0, str(node_runner.OS1_DIR / "src"))

from edge.node_config import SENSORS  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seconds", type=float, default=10)
    args = parser.parse_args()

    run_dir = node_runner.new_run_dir("os1_1")
    with node_runner.running_node(run_dir):
        time.sleep(args.seconds)
        status = node_runner.get_status()

    building = status.get("building") or {}
    node_building = (building.get("node_building") or {}).get("building_id")
    with closing(sqlite3.connect(run_dir / "node.db")) as connection:
        inventory_rows = connection.execute(
            "SELECT COUNT(*), GROUP_CONCAT(DISTINCT source) FROM building_inventory"
        ).fetchone()
        readings = [
            (sensor_id, json.loads(payload))
            for sensor_id, payload in connection.execute("SELECT sensor_id, payload FROM sensor_events")
        ]

    spec = {sensor["id"]: sensor for sensor in SENSORS}
    by_sensor = {sensor_id: [p for s, p in readings if s == sensor_id] for sensor_id in spec}
    checks = {
        "inventory loaded from the cached GeoJSON": building.get("ok") is True and inventory_rows[0] > 0,
        "node located inside a building": node_building is not None,
        "CO2 and temperature both ingested": all(by_sensor[s] for s in spec),
        "every reading tagged with the node's building":
            bool(readings) and all(p.get("building_id") == node_building for _, p in readings),
        "units match the config (ppm, °C)":
            all(p["unit"] == spec[s]["unit"] for s in spec for p in by_sensor[s]),
        "values inside the configured ranges":
            all(spec[s]["min"] <= p["value"] <= spec[s]["max"] for s in spec for p in by_sensor[s]),
    }
    report = {
        "scenario": "OS1-1",
        "seconds": args.seconds,
        "inventory": {"rows": inventory_rows[0], "source": inventory_rows[1],
                      "fixture_note": building.get("fixture_note"), "node_building": building.get("node_building")},
        "readings": {s: len(v) for s, v in by_sensor.items()},
        "checks": checks,
    }
    path = node_runner.write_report(run_dir, report)
    print(json.dumps({k: report[k] for k in ("inventory", "readings")}, indent=2, ensure_ascii=False))
    passed = node_runner.print_checks(checks)
    print(f"Report: {path}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
