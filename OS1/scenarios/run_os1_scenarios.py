"""
Run every OS1 scenario one after the other and print one verdict per scenario.

Usage: python scenarios/run_os1_scenarios.py           official durations (~13 min, OS1-5 = 10 min)
       python scenarios/run_os1_scenarios.py --quick   short durations (~2 min)
       python scenarios/run_os1_scenarios.py --only OS1-2 OS1-3
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

SCENARIOS = {
    "OS1-1": ("os1_1_ingestion.py", [], ["--seconds", "5"]),
    "OS1-2": ("os1_2_race.py", [], ["--trials", "2"]),
    "OS1-3": ("os1_3_ventilation.py", [], ["--seconds", "8"]),
    "OS1-4": ("os1_4_contention.py", [], ["--seconds", "8"]),
    "OS1-5": ("os1_5_wan_outage.py", [], ["--minutes", "0.5"]),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--only", nargs="+", choices=list(SCENARIOS))
    args = parser.parse_args()

    results = {}
    for scenario_id, (script, official, quick) in SCENARIOS.items():
        if args.only and scenario_id not in args.only:
            continue
        print(f"=== {scenario_id}: {script}", flush=True)
        started = time.monotonic()
        code = subprocess.call([sys.executable, str(HERE / script), *(quick if args.quick else official)])
        results[scenario_id] = (code, time.monotonic() - started)

    print("\n=== Summary")
    for scenario_id, (code, seconds) in results.items():
        print(f"{'PASS' if code == 0 else 'FAIL'}  {scenario_id}  ({seconds:.0f} s)")
    return 0 if all(code == 0 for code, _ in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
