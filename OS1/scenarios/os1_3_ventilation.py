"""
OS1-3: CO2 > 1000 ppm opens the HVAC damper to 100 %, the command expires after 15.0 s.

1. Rule boundary: below, at and above 1000 ppm (no node needed).
2. Live node, normal actuator: every high-CO2 reading issues a command and
   the Actuator applies it before it expires.
3. Live node, actuator slowed down past the TTL (EDGE_ACTUATOR_DELAY_S):
   the Actuator compares the expiry with its own monotonic clock and rejects
   every command. The damper never moves.

Usage: python scenarios/os1_3_ventilation.py [--seconds 15]
"""

import argparse
import sqlite3
import sys
import time
from contextlib import closing

import node_runner

sys.path.insert(0, str(node_runner.OS1_DIR / "src"))

from edge import actuator, decision  # noqa: E402


def boundary_checks() -> dict[str, bool]:
    now = time.monotonic()
    below, _ = decision.make_decision(999.9, now)
    at, _ = decision.make_decision(1000.0, now)
    above, expires_at = decision.make_decision(1000.1, now)
    return {
        "999.9 ppm: no command": below is None,
        "1000 ppm: no command (rule is strictly above)": at is None,
        "1000.1 ppm: HVAC_DAMPER_PCT = 100": above is not None
        and above.action == "HVAC_DAMPER_PCT" and above.value == 100,
        "expiry is 15.0 s after the reading": expires_at is not None
        and abs(expires_at - now - 15.0) < 1e-9,
        "fresh command is not expired at 14.9 s": not decision.is_command_expired(expires_at, now + 14.9),
        "command is expired at 15.1 s": decision.is_command_expired(expires_at, now + 15.1),
    }


def node_counts(run_dir) -> dict:
    with closing(sqlite3.connect(run_dir / "node.db")) as connection:
        rows = connection.execute(
            """
            SELECT json_extract(e.payload, '$.value') AS co2,
                   SUM(d.decision_type = 'HVAC_DAMPER_PCT'),
                   SUM(d.decision_type = ?),
                   SUM(d.decision_type = ?)
            FROM events e LEFT JOIN decisions d ON d.event_id = e.event_id
            WHERE e.event_type = 'INDOOR_CO2_PPM'
            GROUP BY e.event_id
            """,
            (actuator.APPLIED, actuator.EXPIRED),
        ).fetchall()
    high = [row for row in rows if row[0] > decision.CO2_THRESHOLD_PPM]
    low = [row for row in rows if row[0] <= decision.CO2_THRESHOLD_PPM]
    return {
        "co2_readings": len(rows),
        "high_readings": len(high),
        "high_with_command": sum(1 for row in high if row[1] == 1),
        "low_with_command": sum(1 for row in low if row[1]),
        "applied": sum(row[2] or 0 for row in rows),
        "expired": sum(row[3] or 0 for row in rows),
    }


def run_live(seconds: float, delay_s: float) -> tuple[dict, int]:
    run_dir = node_runner.new_run_dir(f"os1_3-delay{delay_s:g}")
    extra_env = {"EDGE_ACTUATOR_DELAY_S": str(delay_s)}
    with node_runner.running_node(run_dir, extra_env):
        time.sleep(seconds)
        damper = node_runner.get_status()["damper_pct"]
    counts = node_counts(run_dir)
    counts["damper_pct_at_end"] = damper
    counts["run_dir"] = str(run_dir)
    return counts, damper


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seconds", type=float, default=15, help="length of each live run")
    args = parser.parse_args()

    print("1. Rule boundary")
    checks = boundary_checks()

    print(f"2. Live node, normal actuator ({args.seconds:g} s)")
    normal, _ = run_live(args.seconds, 0)
    print(f"   {normal}")

    slow_delay = decision.COMMAND_TTL_S + 1
    # The first command is checked after one delay: run long enough to see it.
    print(f"3. Live node, actuator {slow_delay:g} s late ({slow_delay + 5:g} s)")
    slow, slow_damper = run_live(slow_delay + 5, slow_delay)
    print(f"   {slow}")

    checks.update({
        "live: every reading above 1000 ppm issued one command":
            normal["high_readings"] > 0 and normal["high_with_command"] == normal["high_readings"],
        "live: no command for readings at or below 1000 ppm": normal["low_with_command"] == 0,
        "live: fresh commands applied, none expired":
            normal["applied"] > 0 and normal["expired"] == 0,
        "slow actuator: stale commands rejected (COMMAND_EXPIRED)":
            slow["expired"] > 0 and slow["applied"] == 0,
        "slow actuator: damper never moved": slow_damper == 0,
    })

    report = {"scenario": "OS1-3", "normal": normal, "slow_actuator": slow, "checks": checks}
    path = node_runner.write_report(node_runner.new_run_dir("os1_3-report"), report)
    passed = node_runner.print_checks(checks)
    print(f"Report: {path}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
