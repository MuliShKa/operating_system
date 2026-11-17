"""
Start an isolated OS1 node for one scenario run, and talk to it.

Each run gets its own folder data/runs/<scenario>-<time>/ with:
  node.db           the node database (events, decisions, outbox, process_health)
  node_upstream.db  the mock receiver database
  node.log          the supervisor output
  report.json       the scenario result
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

OS1_DIR = Path(__file__).resolve().parents[1]
RUNS_DIR = OS1_DIR / "data" / "runs"
API_PORT = int(os.environ.get("EDGE_API_PORT", "8000"))
RECEIVER_PORT = int(os.environ.get("EDGE_RECEIVER_PORT", "8001"))
API_URL = f"http://127.0.0.1:{API_PORT}"
START_TIMEOUT_S = 30.0
STOP_TIMEOUT_S = 15.0
EXPECTED_WORKERS = 8


def new_run_dir(scenario: str) -> Path:
    run_dir = RUNS_DIR / f"{scenario}-{datetime.now():%Y%m%d-%H%M%S}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def get_status() -> dict:
    with urlopen(f"{API_URL}/api/status", timeout=3) as response:
        return json.load(response)


def api_get(path: str) -> str:
    """GET any API path (for example /api/history.csv) and return the body as text."""
    with urlopen(f"{API_URL}{path}", timeout=10) as response:
        return response.read().decode("utf-8")


def set_wan(online: bool) -> None:
    request = Request(f"{API_URL}/api/wan/{'online' if online else 'offline'}", method="POST")
    with urlopen(request, timeout=3):
        pass


def running_workers(status: dict) -> dict[str, int]:
    return {
        name: worker["pid"]
        for name, worker in status["workers"].items()
        if worker["status"] == "running" and worker["pid"]
    }


def _port_in_use(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def start_node(run_dir: Path, extra_env: dict[str, str] | None = None) -> subprocess.Popen:
    """Start the supervisor in the background and wait until its 8 workers are running."""
    for port in (API_PORT, RECEIVER_PORT):
        if _port_in_use(port):
            raise SystemExit(
                f"Port {port} is already used. Stop the other program, or move the node with "
                "EDGE_API_PORT / EDGE_RECEIVER_PORT."
            )

    env = {
        **os.environ,
        "PYTHONPATH": str(OS1_DIR / "src"),
        "EDGE_DATABASE_PATH": str(run_dir / "node.db"),
        "EDGE_API_PORT": str(API_PORT),
        "EDGE_RECEIVER_PORT": str(RECEIVER_PORT),
        **(extra_env or {}),
    }
    with (run_dir / "node.log").open("w", encoding="utf-8") as log:
        # The child gets its own copy of the log file descriptor, so closing ours is fine.
        process = subprocess.Popen(
            [sys.executable, "-m", "edge.supervisor"],
            cwd=OS1_DIR, env=env, stdout=log, stderr=subprocess.STDOUT,
        )

    deadline = time.monotonic() + START_TIMEOUT_S
    while True:
        if process.poll() is not None:
            raise SystemExit(f"Node exited at startup, see {run_dir / 'node.log'}")
        try:
            if len(running_workers(get_status())) == EXPECTED_WORKERS:
                return process
        except OSError:
            pass
        if time.monotonic() > deadline:
            stop_node(process)
            raise SystemExit(f"Node not ready after {START_TIMEOUT_S} s, see node.log")
        time.sleep(0.3)


def stop_node(process: subprocess.Popen) -> None:
    """SIGTERM (like systemd stop), then SIGKILL if it does not stop in time."""
    if process.poll() is None:
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(STOP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def write_report(run_dir: Path, report: dict) -> Path:
    path = run_dir / "report.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def print_checks(checks: dict[str, bool]) -> bool:
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}  {name}")
    return all(checks.values())
