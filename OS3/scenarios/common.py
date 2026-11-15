"""Helpers shared by the OS3 scenario scripts (OS3-1 .. OS3-4).

Every scenario prints one PASS/FAIL line per check and keeps a JSON report in
data/runs/<scenario>-<time>/report.json. Copy the official ones to
document/results/ when you hand the project in.
"""

from __future__ import annotations

import json
import os
import signal
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
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC_DIR)
        env["EDGE_DATABASE_PATH"] = str(self.node_db)   # the receiver DB follows it
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
