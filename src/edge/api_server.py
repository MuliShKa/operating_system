from __future__ import annotations

import json
import psutil
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any


DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "ui" / "static" / "index.html"
PROCESS_CACHE = {}


def run_api_server(state: Any, stop_event: Any, channels: Any) -> None:
    # Expose shared readings, decisions, worker health, and WAN controls.
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/api/status":
                snapshot = dict(state)

                worker_names = {
                    key.removeprefix("worker_status:"): snapshot[key]
                    for key in snapshot
                    if key.startswith("worker_status:")
                }

                workers = {}

                for name, status in worker_names.items():
                    pid = snapshot.get(f"worker_pid:{name}")

                    cpu_percent = None
                    memory_mb = None

                    if pid and status == "running":
                        try:
                            process = PROCESS_CACHE.get(pid)

                            if process is None:
                                process = psutil.Process(pid)
                                PROCESS_CACHE[pid] = process

                            cpu_percent = process.cpu_percent(interval=None)
                            memory_mb = round(
                                process.memory_info().rss / (1024 * 1024), 2
                            )
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            PROCESS_CACHE.pop(pid, None)

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
                    "pending_events": snapshot.get("pending_events", 0),
                    "wan_online": channels.wan_online.is_set(),
                }

                body = json.dumps(payload).encode("utf-8")
                content_type = "application/json; charset=utf-8"

            elif self.path == "/":
                try:
                    body = DASHBOARD_PATH.read_bytes()
                except OSError:
                    self.send_error(404, "Dashboard not found")
                    return

                content_type = "text/html; charset=utf-8"

            else:
                self.send_error(404)
                return

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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

            body = json.dumps(
                {
                    "success": True,
                    "message": message,
                    "wan_online": channels.wan_online.is_set(),
                }
            ).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 8000), Handler)
    server.timeout = 0.5

    try:
        while not stop_event.is_set():
            server.handle_request()
    finally:
        server.server_close()