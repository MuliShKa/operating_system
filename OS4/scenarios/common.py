"""Helpers shared by the OS4 scenario scripts (OS4-1 .. OS4-7).

Every scenario prints one PASS/FAIL line per check and keeps a JSON report in
data/runs/<scenario>-<time>/report.json. Copy the official ones to
document/results/ when you hand the project in.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

API_PORT = int(os.environ.get("EDGE_API_PORT", "8000"))
API = f"http://127.0.0.1:{API_PORT}"


def print_checks(checks: dict[str, bool]) -> bool:
    """Print every check as PASS/FAIL. Return True if all passed."""
    for name, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    ok = all(checks.values())
    print("RESULT:", "ALL CHECKS PASSED" if ok else f"{sum(not v for v in checks.values())} CHECK(S) FAILED")
    return ok


def write_report(scenario: str, payload: dict) -> Path:
    """Save the payload as data/runs/<scenario>-<time>/report.json and return its path."""
    folder = PROJECT_ROOT / "data" / "runs" / f"{scenario}-{time.strftime('%Y%m%d-%H%M%S')}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "report.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def pick_python() -> str:
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    return str(venv_python) if venv_python.exists() else sys.executable


def api_get(path: str) -> dict:
    with urlopen(API + path, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def api_post(path: str) -> dict:
    with urlopen(Request(API + path, data=b"", method="POST"), timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def sim(flag: str, on: bool) -> None:
    """Flip one simulation switch of the running node."""
    api_post(f"/api/sim/{flag}/{'on' if on else 'off'}")


def status() -> dict:
    return api_get("/api/status")


def query(db: Path, sql: str, params: tuple = ()) -> list[tuple]:
    """Read-only query; returns [] if the database is not ready yet."""
    try:
        with sqlite3.connect(db, timeout=10) as connection:
            return connection.execute(sql, params).fetchall()
    except sqlite3.Error:
        return []


def scalar(db: Path, sql: str, params: tuple = (), default: int = 0):
    rows = query(db, sql, params)
    return rows[0][0] if rows and rows[0][0] is not None else default


def wait_for(predicate, timeout: float, interval: float = 0.25):
    """Poll until predicate() is truthy; return its value, or None on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return None


def inject(sensor_id: str, value: float, observed_at: float, socket_dir: Path) -> None:
    """Send ONE datagram to the node's sensor socket, as a (possibly delayed) device would."""
    sys.path.insert(0, str(SRC_DIR))
    from edge import sensors  # the encoders do not depend on SOCKET_DIR

    encode = sensors._CODECS[sensor_id][0]
    send_raw(encode(value, observed_at), socket_dir / f"songdo-os4-{sensor_id.lower()}.sock")


def send_raw(data: bytes, path: Path) -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
        client.sendto(data, str(path))


def api_is_up() -> bool:
    try:
        api_get("/api/status")
        return True
    except (URLError, OSError, ValueError):
        return False


class RunningNode:
    """The whole node started as a child process with throwaway databases."""

    def __init__(self, extra_env: dict[str, str] | None = None) -> None:
        # Check BEFORE starting anything: a second supervisor would fight for the ports.
        if api_is_up():
            raise RuntimeError(
                f"a node is already answering on port {API_PORT}. Stop it first, or move "
                "this run with EDGE_API_PORT / EDGE_RECEIVER_PORT."
            )
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.node_db = tmp / "node.db"
        self.log_path = tmp / "node.log"
        self.receiver_db = tmp / "node_upstream.db"     # default: follows node.db (node_upstream.db)
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC_DIR)
        env["EDGE_DATABASE_PATH"] = str(self.node_db)   # the receiver DB follows it
        self.socket_dir = tmp / "sock"                  # own sockets: never collides with a node you run by hand
        env["EDGE_SOCKET_DIR"] = str(self.socket_dir)
        env["EDGE_SIM_AUTO_EPISODES"] = "0"             # scenarios start episodes themselves
        env.update(extra_env or {})
        self._log = open(self.log_path, "wb")
        self.process = subprocess.Popen(
            [pick_python(), "-m", "edge.supervisor"],
            cwd=PROJECT_ROOT, env=env, stdout=self._log, stderr=subprocess.STDOUT,
        )

    def wait_until_up(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while not api_is_up():
            if self.process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError(
                    "the node did not start. Log tail:\n"
                    + self.log_path.read_text(errors="replace")[-1500:]
                )
            time.sleep(0.5)

    def stop(self) -> None:
        """Stop like Ctrl+C: SIGINT, then kill only if the supervisor hangs."""
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGINT)
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self._log.close()
        self._tmp.cleanup()

    def __enter__(self) -> "RunningNode":
        try:
            self.wait_until_up()
        except RuntimeError:
            self.stop()
            raise
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()
