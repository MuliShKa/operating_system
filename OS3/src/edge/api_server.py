"""Small local-only HTTP API and dashboard server (zero external web framework)."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import psutil


DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "ui" / "static" / "index.html"

# Keep psutil.Process objects: cpu_percent(interval=None) needs a previous call
# on the same object to return a meaningful value.
PROCESS_CACHE: dict[int, psutil.Process] = {}


def _worker_metrics(pid: int | None, status: str | None) -> tuple[float | None, float | None]:
    """Return (cpu_percent, memory_mb) of a running worker, or (None, None)."""
    if not pid or status != "running":
        return None, None
    try:
        process = PROCESS_CACHE.get(pid)
        if process is None:
            process = psutil.Process(pid)
            PROCESS_CACHE[pid] = process
        cpu_percent = process.cpu_percent(interval=None)
        memory_mb = round(process.memory_info().rss / (1024 * 1024), 2)
        return cpu_percent, memory_mb
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        PROCESS_CACHE.pop(pid, None)
        return None, None


def run_api_server(state: Any, stop_event: Any, channels: Any) -> None:
    """Expose shared readings, decisions, sign state, queue stats and worker status."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/api/status":
                snapshot = dict(state)
                worker_names = sorted(
                    key.split(":", 1)[1]
                    for key in snapshot
                    if key.startswith("worker_status:")
                )
                workers = {}
                for name in worker_names:
                    pid = snapshot.get(f"worker_pid:{name}")
                    status = snapshot.get(f"worker_status:{name}")
                    cpu_percent, memory_mb = _worker_metrics(pid, status)
                    workers[name] = {
                        "status": status,
                        "pid": pid,
                        "cpu_percent": cpu_percent,
                        "memory_mb": memory_mb,
                    }

                payload = {
                    "workers": workers,
                    "recent_readings": snapshot.get("recent_readings", []),
                    "recent_decisions": snapshot.get("recent_decisions", []),
                    "recent_actuations": snapshot.get("recent_actuations", []),
                    "actuator": {
                        "applied": snapshot.get("actuator_applied", 0),
                        "expired": snapshot.get("actuator_expired", 0),
                    },
                    "sign_state": snapshot.get("sign_state"),
                    "bus_context": snapshot.get("bus_context"),
                    "queue": channels.sensor_events.stats(),
                    "pending_events": snapshot.get("pending_events", 0),
                    "wan_online": channels.wan_online.is_set(),
                }
                body = json.dumps(payload).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            elif self.path in ("/", "/index.html"):
                body = DASHBOARD_PATH.read_bytes()
                content_type = "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return

            self._respond(body, content_type)

        def do_POST(self) -> None:
            if self.path == "/api/wan/offline":
                channels.wan_online.clear()
                message = "WAN connection disabled"
            elif self.path == "/api/wan/online":
                channels.wan_online.set()
                message = "WAN connection restored"
            else:
                self.send_error(404)
                return

            body = json.dumps({
                "success": True,
                "message": message,
                "wan_online": channels.wan_online.is_set(),
            }).encode("utf-8")
            self._respond(body, "application/json; charset=utf-8")

        def _respond(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    # Listen on the loopback interface only: the console is local, not public.
    server = HTTPServer(("127.0.0.1", 8000), Handler)
    server.timeout = 0.5
    try:
        while not stop_event.is_set():
            server.handle_request()
    finally:
        server.server_close()
