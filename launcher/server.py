"""Scenario launcher: a local web UI to run the OS1..OS5 scenarios and watch their logs.

    python3 launcher/server.py            # opens http://127.0.0.1:9000
    python3 launcher/server.py --port 9100 --no-browser

Standard library only. Jobs run ONE AT A TIME from a queue: the scenarios share
ports 8000/8001 and several of them measure the scheduler, so running two at once
would make them fail or lie. Each job is its own process group, so cancelling it
also stops the nodes it started.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalog import REPO_ROOT, TASKS, TEAMS, team_of  # noqa: E402

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
LOGS = HERE / "logs"
HISTORY = LOGS / "history.json"
WATCHED_PORTS = (8000, 8001)
MAX_LOG_CHUNK = 256 * 1024


class Job:
    _ids = itertools.count(1)

    def __init__(self, task_id: str, quick: bool, batch: str | None) -> None:
        self.id = next(Job._ids)
        self.task = TASKS[task_id]
        self.quick = quick
        self.batch = batch
        self.status = "queued"          # queued | running | passed | failed | cancelled
        self.created = time.time()
        self.started: float | None = None
        self.ended: float | None = None
        self.exit_code: int | None = None
        self.process: subprocess.Popen | None = None
        self.cancel_requested = False
        self.log_path = LOGS / f"{time.strftime('%Y%m%d-%H%M%S')}-{self.id:03d}-{task_id}.log"

    def to_dict(self) -> dict:
        end = self.ended or (time.time() if self.started else None)
        return {
            "id": self.id, "task": self.task.id, "team": self.task.team, "title": self.task.title,
            "mode": "quick" if self.quick else "official", "batch": self.batch, "status": self.status,
            "created": self.created, "started": self.started, "ended": self.ended,
            "duration": round(end - self.started, 1) if self.started and end else None,
            "exit_code": self.exit_code, "log": self.log_path.name,
        }


class Runner:
    """Owns the queue and the single worker thread that executes it."""

    def __init__(self) -> None:
        self.jobs: list[Job] = []
        self.lock = threading.Condition()
        self.history = self._load_history()
        self.stopping = False
        threading.Thread(target=self._loop, name="job-runner", daemon=True).start()

    # ---------- queue ----------
    def submit(self, task_ids: list[str], quick: bool, batch: str | None) -> list[int]:
        with self.lock:
            jobs = [Job(task_id, quick, batch) for task_id in task_ids]
            self.jobs.extend(jobs)
            self.lock.notify_all()
            return [job.id for job in jobs]

    def cancel(self, job_id: int | None = None) -> int:
        """Cancel one job, or every queued/running job when job_id is None."""
        count = 0
        with self.lock:
            for job in self.jobs:
                if job_id is not None and job.id != job_id:
                    continue
                if job.status == "queued":
                    job.status, job.ended = "cancelled", time.time()
                    count += 1
                elif job.status == "running" and not job.cancel_requested:
                    job.cancel_requested = True
                    threading.Thread(target=self._stop_group, args=(job,), daemon=True).start()
                    count += 1
        return count

    def clear_finished(self) -> None:
        with self.lock:
            self.jobs = [job for job in self.jobs if job.status in ("queued", "running")]

    def get(self, job_id: int) -> Job | None:
        with self.lock:
            return next((job for job in self.jobs if job.id == job_id), None)

    def running(self) -> Job | None:
        return next((job for job in self.jobs if job.status == "running"), None)

    # ---------- execution ----------
    def _loop(self) -> None:
        while True:
            with self.lock:
                while not self.stopping and not any(job.status == "queued" for job in self.jobs):
                    self.lock.wait()
                if self.stopping:
                    return
                job = next(job for job in self.jobs if job.status == "queued")
                job.status, job.started = "running", time.time()
            self._execute(job)

    def _execute(self, job: Job) -> None:
        team = team_of(job.task)
        args = job.task.args(job.quick)
        LOGS.mkdir(exist_ok=True)
        with open(job.log_path, "wb") as log:
            def note(line: str) -> None:
                log.write(f"[launcher] {line}\n".encode())
                log.flush()

            note(f"{job.task.id} · {job.task.title} · {'quick' if job.quick else 'official'} mode")
            note(f"cd {team.id} && {team.python.relative_to(team.folder)} {' '.join(args)}")
            if not team.python.exists():
                note(f"virtualenv missing: run  bash {team.id}/scripts/setup.sh  first")
                self._finish(job, 127)
                return
            busy = [port for port in WATCHED_PORTS if port_in_use(port)]
            if busy:
                note(f"warning: port(s) {busy} already in use, the scenario may refuse to start")
            note("-" * 60)
            env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONPATH": str(team.folder / "src"),
                   "FORCE_COLOR": "0", "TERM": "dumb", "COLUMNS": "78"}  # banners fit the log panel
            try:
                job.process = subprocess.Popen(
                    [str(team.python), *args], cwd=team.folder, env=env, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            except OSError as error:
                note(f"could not start: {error}")
                self._finish(job, 126)
                return
            if job.cancel_requested:  # cancelled between "running" and Popen
                self._stop_group(job)
            code = job.process.wait()
            log.flush()
            note("-" * 60)
            note(f"exit code {code} after {time.time() - job.started:.1f} s")
        self._finish(job, code)

    def _finish(self, job: Job, code: int) -> None:
        with self.lock:
            job.exit_code, job.ended = code, time.time()
            # A job that finished cleanly before the stop arrived still counts as passed.
            if code == 0:
                job.status = "passed"
            else:
                job.status = "cancelled" if job.cancel_requested else "failed"
            if job.status != "cancelled":
                self.history[job.task.id] = {
                    "status": job.status, "duration": round(job.ended - job.started, 1),
                    "mode": "quick" if job.quick else "official", "ended": job.ended, "log": job.log_path.name}
                self._save_history()
            self.lock.notify_all()

    @staticmethod
    def _stop_group(job: Job) -> None:
        """Like Ctrl+C on the whole job (scenario + the nodes it started), then escalate."""
        process = job.process
        if process is None or process.poll() is not None:
            return
        for sig, grace in ((signal.SIGINT, 15), (signal.SIGTERM, 5), (signal.SIGKILL, 5)):
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                return
            try:
                process.wait(timeout=grace)
                return
            except subprocess.TimeoutExpired:
                continue

    def shutdown(self) -> None:
        with self.lock:
            self.stopping = True
            running = self.running()
            for job in self.jobs:
                if job.status == "queued":
                    job.status = "cancelled"
            self.lock.notify_all()
        if running:
            running.cancel_requested = True
            self._stop_group(running)

    # ---------- history ----------
    @staticmethod
    def _load_history() -> dict:
        try:
            return json.loads(HISTORY.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_history(self) -> None:
        LOGS.mkdir(exist_ok=True)
        HISTORY.write_text(json.dumps(self.history, indent=1), encoding="utf-8")

    def snapshot(self) -> dict:
        with self.lock:
            return {"jobs": [job.to_dict() for job in self.jobs], "history": dict(self.history)}


# ---------- ports ----------
def port_in_use(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def port_owners() -> list[dict]:
    """Who listens on 8000/8001: pid and command line when `ss` can tell us."""
    owners = {port: {"port": port, "busy": port_in_use(port), "pid": None, "command": None}
              for port in WATCHED_PORTS}
    try:
        out = subprocess.run(["ss", "-ltnpH"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    for line in out.splitlines():
        match = re.search(r":(\d+)\s.*pid=(\d+)", line)
        if match and int(match.group(1)) in owners:
            entry = owners[int(match.group(1))]
            entry["busy"], entry["pid"] = True, int(match.group(2))
            try:
                cmd = Path(f"/proc/{entry['pid']}/cmdline").read_bytes().replace(b"\0", b" ").decode().strip()
                entry["command"] = cmd[:200]
                entry["ours"] = str(REPO_ROOT) in cmd
            except OSError:
                pass
    return list(owners.values())


def stop_port_owner(port: int) -> str:
    entry = next((o for o in port_owners() if o["port"] == port), None)
    if not entry or not entry["busy"]:
        return "port already free"
    if not entry["pid"] or not entry.get("ours"):
        return "not a process from this repository: stop it yourself"
    # The listener is usually a worker: stop its supervisor (parent) when it is ours too.
    pid = entry["pid"]
    try:
        parent = int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[1])
        parent_cmd = Path(f"/proc/{parent}/cmdline").read_bytes().decode(errors="replace")
        if str(REPO_ROOT) in parent_cmd and "supervisor" in parent_cmd:
            pid = parent
    except (OSError, IndexError, ValueError):
        pass
    os.kill(pid, signal.SIGINT)
    return f"sent SIGINT to PID {pid}"


# ---------- HTTP ----------
RUNNER: Runner


def catalog_payload() -> list[dict]:
    return [{
        "id": team.id, "name": team.name, "summary": team.summary, "ready": team.python.exists(),
        "tasks": [{"id": t.id, "title": t.title, "concept": t.concept, "expected": t.expected,
                   "kind": t.kind, "note": t.note, "has_quick": t.quick is not None} for t in team.tasks],
    } for team in TEAMS]


class Handler(BaseHTTPRequestHandler):
    server_version = "OSLauncher/1.0"

    def log_message(self, *_args) -> None:  # keep the terminal quiet
        pass

    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: object, status: int = 200) -> None:
        self._send(json.dumps(payload).encode(), "application/json", status)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return {}

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            return self._static("index.html")
        if url.path.startswith("/static/"):
            return self._static(url.path.removeprefix("/static/"))
        if url.path == "/api/catalog":
            return self._json(catalog_payload())
        if url.path == "/api/state":
            return self._json({**RUNNER.snapshot(), "ports": port_owners()})
        if match := re.fullmatch(r"/api/log/(\d+)", url.path):
            return self._log(int(match.group(1)), parse_qs(url.query))
        if match := re.fullmatch(r"/api/logfile/([\w.\-]+\.log)", url.path):
            path = LOGS / match.group(1)
            if path.is_file():
                return self._send(path.read_bytes(), "text/plain; charset=utf-8")
        self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/run":
            body = self._body()
            tasks = [t for t in body.get("tasks", []) if t in TASKS]
            if not tasks:
                return self._json({"error": "no valid task"}, HTTPStatus.BAD_REQUEST)
            ids = RUNNER.submit(tasks, bool(body.get("quick", True)), body.get("batch") or None)
            return self._json({"queued": ids})
        if match := re.fullmatch(r"/api/cancel/(\d+)", path):
            return self._json({"cancelled": RUNNER.cancel(int(match.group(1)))})
        if path == "/api/cancel-all":
            return self._json({"cancelled": RUNNER.cancel(None)})
        if path == "/api/clear":
            RUNNER.clear_finished()
            return self._json({"ok": True})
        if match := re.fullmatch(r"/api/port-stop/(\d+)", path):
            if RUNNER.running():
                return self._json({"message": "a job is running: cancel it instead"}, HTTPStatus.CONFLICT)
            return self._json({"message": stop_port_owner(int(match.group(1)))})
        self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def _static(self, name: str) -> None:
        path = (STATIC / name).resolve()
        if STATIC not in path.parents or not path.is_file():
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        types = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"}
        self._send(path.read_bytes(), types.get(path.suffix, "application/octet-stream") + "; charset=utf-8")

    def _log(self, job_id: int, query: dict) -> None:
        job = RUNNER.get(job_id)
        if job is None:
            return self._json({"error": "unknown job"}, HTTPStatus.NOT_FOUND)
        offset = int(query.get("offset", ["0"])[0])
        try:
            with open(job.log_path, "rb") as log:
                log.seek(offset)
                chunk = log.read(MAX_LOG_CHUNK)
        except FileNotFoundError:
            chunk = b""
        self._json({"text": chunk.decode("utf-8", errors="replace"), "offset": offset + len(chunk),
                    "status": job.status})


def main() -> int:
    global RUNNER
    parser = argparse.ArgumentParser(description="OS1..OS5 scenario launcher")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    # If we were started in the background, SIGINT is ignored and every child would inherit
    # that, so "Stop" (SIGINT) would do nothing. A real handler is reset to default in children.
    signal.signal(signal.SIGINT, signal.default_int_handler)
    RUNNER = Runner()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as error:
        print(f"Cannot listen on 127.0.0.1:{args.port}: {error}. Try --port 9100.")
        return 1
    server.daemon_threads = True
    url = f"http://127.0.0.1:{args.port}"
    print(f"Scenario launcher on {url}  (Ctrl+C to stop, running jobs are stopped too)")
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    def on_sigterm(*_args) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, on_sigterm)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping: cancelling the running job...")
    finally:
        RUNNER.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
