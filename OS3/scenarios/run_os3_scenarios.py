#!/usr/bin/env python3
"""Run the OS3 scenarios one after another and print a PASS/FAIL summary.

  python3 scenarios/run_os3_scenarios.py            # official: OS3-5 offline for 600 s
  python3 scenarios/run_os3_scenarios.py --quick    # OS3-5 offline for 60 s (smoke test)
  python3 scenarios/run_os3_scenarios.py --only os3_3 os3_4
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import common

HERE = Path(__file__).resolve().parent


def build_plan(quick: bool) -> dict[str, list[str]]:
    return {
        "os3_1": ["os3_1_bus_context.py", "--seconds", "45"],
        "os3_2": ["os3_2_priority.py"],
        "os3_3": ["os3_3_overload.py"],
        "os3_4": ["os3_4_transactional.py"],
        "os3_5": ["os3_5_offline_demo.py", "--offline-seconds", "60" if quick else "600"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quick", action="store_true", help="OS3-5 offline for 60 s instead of 600 s")
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
