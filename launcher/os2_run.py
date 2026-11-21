"""Run ONE OS2 acceptance scenario against a fresh OS2 node.

OS2's own runner expects a node already running and runs all five scenarios.
This wrapper starts the node, waits for its API, runs the chosen scenario, and
always stops the node (SIGINT, like Ctrl+C) so port 8000 is freed.

Run with the OS2 virtualenv, from the OS2 folder, PYTHONPATH=src:
    python ../launcher/os2_run.py 3 --offline-seconds 30
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

OS2_DIR = Path(__file__).resolve().parents[1] / "OS2"
sys.path.insert(0, str(OS2_DIR / "scenarios"))
sys.path.insert(0, str(OS2_DIR / "src"))

import run_os2_scenarios as os2  # noqa: E402  (needs the paths above)

SCENARIOS = {
    "1": lambda _: os2.scenario_1_process_topology(),
    "2": lambda _: os2.scenario_2_monotonic_jitter(),
    "3": lambda _: os2.scenario_3_obstacle_stop(),
    "4": lambda _: os2.scenario_4_worker_restart(),
    "5": lambda seconds: os2.scenario_5_offline_conservation(seconds),
}


def api_up() -> bool:
    try:
        with urlopen(os2.BASE_URL + "/api/status", timeout=1):
            return True
    except (URLError, OSError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=list(SCENARIOS))
    parser.add_argument("--offline-seconds", type=int, default=600)
    args = parser.parse_args()

    if api_up():
        print(f"A node already answers on {os2.BASE_URL}. Stop it first (it would be tested instead).")
        return 1

    print(f"Starting the OS2 node ({os2.BASE_URL})...", flush=True)
    # Same as OS2's start_demo.sh: the mock upstream receiver is its own process,
    # started first. Without it the outbox never drains (OS2-5 needs it).
    env = {**os.environ, "PYTHONPATH": str(OS2_DIR / "src")}
    start = lambda module: subprocess.Popen([sys.executable, "-m", module], cwd=OS2_DIR, env=env,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    receiver = start("edge.upstream_receiver")
    node = start("edge.supervisor")
    try:
        deadline = time.monotonic() + 60
        while not api_up():
            if node.poll() is not None or time.monotonic() > deadline:
                print("The OS2 node did not start.")
                return 1
            time.sleep(0.5)
        time.sleep(2)  # let the workers publish a few readings first
        print(f"Node up (supervisor PID {node.pid}). Running OS2-{args.scenario}.\n", flush=True)
        try:
            SCENARIOS[args.scenario](args.offline_seconds)
        except (OSError, URLError, RuntimeError, StopIteration, KeyError) as error:
            print(f"OS2-{args.scenario} FAIL: {error}")
            return 1
        return 0
    finally:
        for process in (node, receiver):   # supervisor first, then the receiver (like start_demo.sh)
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        print("\nOS2 node stopped.", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
