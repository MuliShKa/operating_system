#!/usr/bin/env python3
"""OS4-7 (EXTRA): multi-sensor context policy, "quiet night" for the mist cannon.

Not in the handbook: our own scenario. The pump is loud. If it is dark AND the
street is quiet (illumination + noise sensors), an ordinary "Bad" PM2.5 reading does
not start it; only a "Very Bad" one does (emergency override). This is what gives
the noise and illumination streams a real job in the node (multi-sensor aggregation).

  night + Bad (58-72)        -> HOLD  (decision MIST_HELD_QUIET_HOURS, relay stays OFF)
  night + Very Bad (80-100)  -> DISPATCH with override
  day   + Bad                -> DISPATCH as usual

Usage: python3 scenarios/os4_7_night_policy.py
"""

from __future__ import annotations

import time

import common


def ch(name: str) -> dict:
    return common.status()["channels"][name]


def relay() -> str:
    return common.status()["relay_state"]["state"]


def main() -> int:
    with common.RunningNode({"EDGE_SIM_LATE_PROB": "0"}) as node:
        db = node.node_db
        time.sleep(5)

        print(">>> night falls: dark and quiet street")
        common.sim("night", True)
        dark = common.wait_for(lambda: ch("LUX")["value"] is not None and ch("LUX")["value"] < 10 and ch("NOISE")["value"] < 45, 15)

        print(">>> Bad dust (58-72) at night")
        common.sim("episode", True)
        held = common.wait_for(lambda: common.scalar(db, "SELECT COUNT(*) FROM decisions WHERE decision_type='MIST_HELD_QUIET_HOURS'") >= 1, 15)
        time.sleep(15)
        held_off = relay() == "OFF"
        hold_rows = common.scalar(db, "SELECT COUNT(*) FROM decisions WHERE decision_type='MIST_HELD_QUIET_HOURS'")
        dispatched_while_held = common.scalar(db, "SELECT COUNT(*) FROM decisions WHERE decision_type='MIST_CANNON_RELAY'")

        print(">>> Very Bad dust (80-100) at night: emergency override")
        common.sim("extreme", True)
        override_on = common.wait_for(lambda: relay() == "ON", 15)
        override_reason = common.query(db, "SELECT reason FROM decisions WHERE decision_type='MIST_CANNON_RELAY'")
        common.sim("extreme", False)
        common.sim("episode", False)
        wait_off = common.wait_for(lambda: relay() == "OFF", 50)

        print(">>> morning: bright and noisy street, Bad dust again")
        common.sim("night", False)
        bright = common.wait_for(lambda: ch("LUX")["value"] > 10 and ch("NOISE")["value"] > 45, 15)
        common.sim("episode", True)
        day_on = common.wait_for(lambda: relay() == "ON", 15)
        day_reason = common.query(db, "SELECT reason FROM decisions WHERE decision_type='MIST_CANNON_RELAY' ORDER BY decision_id DESC LIMIT 1")

        checks = {
            "illumination and noise sensors report a dark, quiet street": bool(dark),
            "night + Bad: the hold is reported (MIST_HELD_QUIET_HOURS)": bool(held),
            "night + Bad: the pump stays OFF for 15+ s": held_off,
            "the hold is reported once per episode, not at every reading": hold_rows == 1,
            "no dispatch decision while held": dispatched_while_held == 0,
            "night + Very Bad: the pump starts (override)": bool(override_on),
            "the override is named in the decision reason": any("override" in r[0] for r in override_reason),
            "the relay goes OFF after the dust ends": bool(wait_off),
            "day returns: sensors report a bright, noisy street": bool(bright),
            "day + Bad: the pump starts as usual": bool(day_on),
            "the daytime decision does not mention an override": bool(day_reason) and "override" not in day_reason[0][0],
            "every worker still running": all(w["status"] == "running" for w in common.status()["workers"].values()),
        }
        passed = common.print_checks(checks)
        path = common.write_report("os4_7", {"scenario": "OS4-7 (extra)", "hold_decisions": hold_rows, "checks": checks})
        print(f"Report: {path}")
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
