"""Small local-only HTTP API and dashboard server."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any


DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "ui" / "static" / "index.html"


def run_api_server(state: Any, stop_event: Any) -> None:
    # Demo integration: expose shared readings, decisions, and worker status.
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/api/status":
                snapshot = dict(state)
                worker_names = {
                    key.split(":", 1)[1]
                    for key in snapshot
                    if key.startswith("worker_status:")
                }
                payload = {
                    "workers": {
                        name: {
                            "status": snapshot[f"worker_status:{name}"],
                            "pid": snapshot.get(f"worker_pid:{name}"),
                        }
                        for name in worker_names
                    },
                    "recent_readings": snapshot.get("recent_readings", []),
                    "recent_decisions": snapshot.get("recent_decisions", []),
                    "pending_events": snapshot.get("pending_events", 0),
                }
                body = json.dumps(payload).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            elif self.path in ("/", "/index.html"):
                body = DASHBOARD_PATH.read_bytes()
                content_type = "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return

            self.send_response(200)
            self.send_header("Content-Type", content_type)
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