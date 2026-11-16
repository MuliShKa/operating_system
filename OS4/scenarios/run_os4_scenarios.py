#!/usr/bin/env python3
"""Run the OS4 scenarios one after another and print a PASS/FAIL summary.

  python3 scenarios/run_os4_scenarios.py            # official: OS4-5 offline for 600 s
  python3 scenarios/run_os4_scenarios.py --quick    # OS4-5 offline for 60 s (smoke test)
  python3 scenarios/run_os4_scenarios.py --only os4_3 os4_6
"""

from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path

import common

HERE = Path(__file__).resolve().parent


def build_plan(quick: bool) -> dict[str, list[str]]:
    return {
        "os4_1": ["os4_1_ingestion.py", "--seconds", "30"],
        "os4_2": ["os4_2_event_time.py"],
        "os4_3": ["os4_3_mist_relay.py"],
        "os4_4": ["os4_4_backup.py"],
        "os4_5": ["os4_5_offline_demo.py", "--offline-seconds", "60" if quick else "600"],
        "os4_6": ["os4_6_sensor_faults.py"],      # extra scenario
        "os4_7": ["os4_7_night_policy.py"],       # extra scenario
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quick", action="store_true", help="OS4-5 offline for 60 s instead of 600 s")
    parser.add_argument("--only", nargs="+", choices=list(build_plan(False)), help="run only these")
    args = parser.parse_args()

    plan = build_plan(args.quick)
    selected = args.only or list(plan)
    python = common.pick_python()
    results: dict[str, tuple[bool, float]] = {}
    for name in selected:
        print(f"\n===== {name} =====", flush=True)
        started = time.monotonic()
        code = subprocess.run([python, str(HERE / plan[name][0]), *plan[name][1:]], cwd=common.PROJECT_ROOT).returncode
        results[name] = (code == 0, time.monotonic() - started)

    print("\n===== SUMMARY =====")
    for name, (ok, seconds) in results.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}  ({seconds:.0f} s)")
    ok_all = all(ok for ok, _ in results.values())
    print("OVERALL:", "ALL SCENARIOS PASSED" if ok_all else "SOME SCENARIOS FAILED")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
