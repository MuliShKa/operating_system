"""
OS1-2: 80 concurrent turnstile increments, without then with a mutex.

Handbook check: unprotected counter < 80, mutex counter == 80.
Each mode is repeated (--trials) to show the result is not luck.

Usage: python scenarios/os1_2_race.py [--trials 5]
"""

import argparse
import sys

import node_runner

sys.path.insert(0, str(node_runner.OS1_DIR / "src"))

from edge.occupancy import TURNSTILES, count_entries  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trials", type=int, default=5)
    args = parser.parse_args()

    unprotected = [count_entries(use_lock=False) for _ in range(args.trials)]
    mutex = [count_entries(use_lock=True) for _ in range(args.trials)]
    # Information only: no forced preemption, the race window is tiny.
    natural = [count_entries(use_lock=False, pause_s=0) for _ in range(args.trials)]
    for row in natural:
        row["mode"] = "no-pause"
    for row in unprotected + mutex + natural:
        print(f"  {row['mode']:<12} final={row['final']:>3}/{row['expected']}  lost={row['lost_updates']}")

    checks = {
        f"unprotected counter < {TURNSTILES} in every trial":
            all(row["final"] < TURNSTILES for row in unprotected),
        f"mutex counter == {TURNSTILES} in every trial":
            all(row["final"] == TURNSTILES for row in mutex),
        "every writer exited cleanly (joined, exit code 0)":
            all(row["exit_codes_ok"] for row in unprotected + mutex),
    }
    run_dir = node_runner.new_run_dir("os1_2")
    path = node_runner.write_report(run_dir, {
        "scenario": "OS1-2", "turnstiles": TURNSTILES, "trials": args.trials,
        "unprotected": unprotected, "mutex": mutex,
        "no_pause_information_only": natural, "checks": checks,
    })
    passed = node_runner.print_checks(checks)
    print(f"Report: {path}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
