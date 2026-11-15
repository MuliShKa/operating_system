"""
Run every OS1 scenario one after the other and print one verdict per scenario.
Before each scenario, a short banner explains what is tested and which OS concept it shows.

Usage: python scenarios/run_os1_scenarios.py           official durations (~13 min, OS1-5 = 10 min)
       python scenarios/run_os1_scenarios.py --quick   short durations (~2 min)
       python scenarios/run_os1_scenarios.py --only OS1-2 OS1-3
       python scenarios/run_os1_scenarios.py --quick --pause   wait for Enter before each scenario (live demo)
"""

import argparse
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

# id: (script, official args, quick args, title, what it tests, OS concept, expected result)
SCENARIOS = {
    "OS1-1": (
        "os1_1_ingestion.py", [], ["--seconds", "5"],
        "Sensor ingestion & cached building inventory",
        "The node reads a cached building map (GeoJSON) from disk, finds the building that "
        "contains its coordinates, then stores CO2 and temperature readings tagged with that building.",
        "File descriptors: open() gives an fd, read() copies bytes from the kernel to user memory, "
        "close() frees it. Offline-first: no online map is called at runtime.",
        "Inventory loaded, node inside FIXTURE-CONVENSIA, every reading tagged, units and ranges right.",
    ),
    "OS1-2": (
        "os1_2_race.py", [], ["--trials", "2"],
        "Race condition on the occupancy counter",
        "80 turnstile processes each add +1 to one counter in shared memory, first without a lock, "
        "then with a mutex.",
        "Preemption between read and write loses updates (race condition). A mutex makes the "
        "read-add-write a critical section that only one process runs at a time.",
        "Without lock: counter < 80. With mutex: exactly 80, every trial.",
    ),
    "OS1-3": (
        "os1_3_ventilation.py", [], ["--seconds", "8"],
        "Ventilation rule & damper command expiry",
        "If CO2 is above 1000 ppm, the damper is set to 100 %. Each command expires 15 s after the "
        "reading. A second run slows the actuator by 16 s so that every command arrives too late.",
        "Monotonic clock: it only goes forward, so the actuator can safely reject stale commands.",
        "999.9 / 1000 ppm: no command, 1000.1: command. Fresh commands applied; slow actuator: "
        "all commands expired, damper never moves.",
    ),
    "OS1-4": (
        "os1_4_contention.py", [], ["--seconds", "8"],
        "Process profiling under CPU load",
        "Every 2.0 s the node reads /proc for each worker: CPU, RSS memory and context switches. "
        "First idle, then with CPU-burner processes competing for the cores.",
        "/proc filesystem, RSS, voluntary (process waits) vs involuntary (scheduler preempts) "
        "context switches.",
        "Every worker sampled every 2.0 s; involuntary switches go up under load.",
    ),
    "OS1-5": (
        "os1_5_wan_outage.py", [], ["--minutes", "0.5"],
        "Signature demo: Internet cut",
        "The WAN is cut (10 min officially, 30 s in quick mode). The node keeps sensing and deciding "
        "while events pile up in the outbox. Then the WAN comes back and the backlog is sent.",
        "Durable outbox written in the same SQLite transaction as the event, store-and-forward, "
        "idempotent receiver (an event sent twice is stored once).",
        "No crash, nothing sent while offline, backlog drained, 0 lost, 0 duplicates.",
    ),
}


def banner(scenario_id: str, title: str, what: str, concept: str, expected: str, quick: bool) -> None:
    width = min(shutil.get_terminal_size((100, 20)).columns, 100)
    wrap = lambda label, text: textwrap.fill(
        text, width=width, initial_indent=f"  {label:<10}", subsequent_indent=" " * 12
    )
    print("=" * width)
    print(f"  {scenario_id}  {title}{'   (quick mode)' if quick else ''}")
    print("-" * width)
    print(wrap("Test", what))
    print(wrap("Concept", concept))
    print(wrap("Expected", expected))
    print("=" * width, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quick", action="store_true", help="short durations (~2 min in total)")
    parser.add_argument("--only", nargs="+", choices=list(SCENARIOS))
    parser.add_argument("--pause", action="store_true", help="wait for Enter before each scenario")
    args = parser.parse_args()

    results = {}
    for scenario_id, (script, official, quick, title, what, concept, expected) in SCENARIOS.items():
        if args.only and scenario_id not in args.only:
            continue
        print()
        banner(scenario_id, title, what, concept, expected, args.quick)
        if args.pause:
            input("Press Enter to run it... ")
        started = time.monotonic()
        code = subprocess.call([sys.executable, str(HERE / script), *(quick if args.quick else official)])
        results[scenario_id] = (code, time.monotonic() - started)

    print("\n=== Summary")
    for scenario_id, (code, seconds) in results.items():
        title = SCENARIOS[scenario_id][3]
        print(f"{'PASS' if code == 0 else 'FAIL'}  {scenario_id}  {title}  ({seconds:.0f} s)")
    return 0 if all(code == 0 for code, _ in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
