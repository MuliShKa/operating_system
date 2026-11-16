#!/usr/bin/env python3
"""OS4-6 (EXTRA): sensor faults must never drive the mist cannon (fail-safe actuation).

Not in the handbook: our own scenario. A pump that sprays water because a broken
sensor says "dust" is worse than no automation. We inject three kinds of fault:

  1. implausible or malformed datagrams  -> rejected at the door, never stored
  2. a HUNG sensor (silent, no error)    -> channel goes STALE, no new commands,
                                            relay falls OFF by itself when the TTL ends
  3. a FROZEN sensor (repeats a value)   -> channel goes STUCK, commands stop, relay OFF
and each time the channel must recover when the fault is cleared.

Usage: python3 scenarios/os4_6_sensor_faults.py
"""

from __future__ import annotations

import time
from datetime import datetime

import common


def epoch(text: str) -> float:
    return datetime.fromisoformat(text).timestamp()


def pm25_status() -> str:
    return common.status()["channels"]["PM25"]["status"]


def relay() -> str:
    return common.status()["relay_state"]["state"]


def main() -> int:
    with common.RunningNode({"EDGE_SIM_LATE_PROB": "0"}) as node:
        db = node.node_db
        sock = node.socket_dir / "songdo-os4-pm25.sock"
        time.sleep(8)

        # ---- 1. bad datagrams ------------------------------------------------------------
        for raw in (b'{"id": "PM25", "value": NaN, "observed_at": %f}' % time.time(),
                    b'{"id": "PM25", "value": -5, "observed_at": %f}' % time.time(),
                    b'{"id": "PM25", "value": 5000, "observed_at": %f}' % time.time(),
                    b"\x00\x01 garbage", b'{"id": "NOISE"}'):
            common.send_raw(raw, sock)
        time.sleep(3)
        ch = common.status()["channels"]["PM25"]
        bad_stored = common.scalar(db, "SELECT COUNT(*) FROM events WHERE event_type='PM25' AND "
                                       "(json_extract(payload,'$.value') < 0 OR json_extract(payload,'$.value') > 1000)")
        relay_after_bad = relay()

        # ---- 2. hung sensor in the middle of a spray -----------------------------------------------
        print(">>> dust episode, relay ON, then the PM2.5 sensor HANGS")
        common.sim("episode", True)
        relay_on = common.wait_for(lambda: relay() == "ON", 15)
        time.sleep(4)
        common.sim("mute_pm25", True)
        muted_at = time.time()
        stale_at = common.wait_for(lambda: pm25_status() == "STALE" and time.time(), 25)
        off_at = common.wait_for(lambda: relay() == "OFF" and time.time(), 45)
        last_high = common.query(db, "SELECT MAX(observed_at) FROM events WHERE event_type='PM25' AND json_extract(payload,'$.value') > 50")[0][0]
        noise_ok = common.status()["channels"]["NOISE"]["status"] == "OK"
        time.sleep(4)
        still_off = relay() == "OFF"
        stale_decisions = common.scalar(db, "SELECT COUNT(*) FROM decisions WHERE decision_type='SENSOR_STALE'")

        # ---- 3. sensor comes back ------------------------------------------------------------------
        print(">>> the sensor comes back (episode still on)")
        common.sim("mute_pm25", False)
        recovered = common.wait_for(lambda: pm25_status() == "OK", 15)
        relay_again = common.wait_for(lambda: relay() == "ON", 15)

        # ---- 4. frozen sensor ------------------------------------------------------------------------------
        print(">>> the PM2.5 sensor FREEZES on a high value")
        common.sim("stuck_pm25", True)
        stuck_seen = common.wait_for(lambda: pm25_status() == "STUCK" and time.time(), 30)
        frozen_off = common.wait_for(lambda: relay() == "OFF" and time.time(), 45)
        before = common.scalar(db, "SELECT COUNT(*) FROM events WHERE event_type='PM25'")
        time.sleep(5)
        after = common.scalar(db, "SELECT COUNT(*) FROM events WHERE event_type='PM25'")
        off_while_frozen = relay() == "OFF"

        # ---- 5. clear everything -------------------------------------------------------------------------------
        common.sim("stuck_pm25", False)
        common.sim("episode", False)
        ok_again = common.wait_for(lambda: pm25_status() == "OK", 20)
        types = dict(common.query(db, "SELECT decision_type, COUNT(*) FROM decisions GROUP BY 1"))
        ttl_after_last = (off_at - epoch(last_high)) if (off_at and last_high) else None
        print(f"  decisions: {types}; relay OFF {ttl_after_last and round(ttl_after_last, 1)} s after the last accepted high reading")

        checks = {
            "NaN, negative and out-of-range values are rejected (3)": ch["rejected"] >= 3,
            "garbage and wrong-device messages are counted as malformed": ch["parse_errors"] >= 2,
            "no implausible value was ever stored": bad_stored == 0,
            "bad datagrams did not move the relay": relay_after_bad == "OFF",
            "relay was ON during the episode": bool(relay_on),
            "hung sensor: channel reported STALE within 25 s": bool(stale_at),
            "hung sensor: relay fell OFF by itself 28-34 s after the last accepted reading": ttl_after_last is not None and 28.0 <= ttl_after_last <= 34.0,
            "hung sensor: relay stays OFF while the channel is silent": still_off,
            "hung sensor: the other channels kept working": noise_ok,
            "hung sensor: SENSOR_STALE decision recorded": stale_decisions >= 1,
            "sensor back: channel OK again": bool(recovered),
            "sensor back: spraying resumes only after it is trusted again": bool(relay_again),
            "frozen sensor: channel reported STUCK": bool(stuck_seen),
            "frozen sensor: relay switched OFF although every reading is above 50": bool(frozen_off) and off_while_frozen,
            "frozen sensor: readings kept arriving (device was talking)": after > before,
            "SENSOR_STUCK and SENSOR_RECOVERED decisions recorded": types.get("SENSOR_STUCK", 0) >= 1 and types.get("SENSOR_RECOVERED", 0) >= 2,
            "channel OK again after the fault is cleared": bool(ok_again),
            "no worker crashed during any fault": all(w["status"] == "running" for w in common.status()["workers"].values()),
        }
        passed = common.print_checks(checks)
        path = common.write_report("os4_6", {"scenario": "OS4-6 (extra)", "decisions": types,
                                             "ttl_after_last_accepted_s": ttl_after_last, "checks": checks})
        print(f"Report: {path}")
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
