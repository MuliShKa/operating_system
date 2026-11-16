"""Small local-only HTTP API and dashboard server."""

from __future__ import annotations

import json
import logging
import sqlite3
import psutil
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from edge import storage
from edge.health import build_readiness_report


DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "ui" / "static" / "index.html"
PROCESS_CACHE = {}
log = logging.getLogger(__name__)


def health_snapshot() -> dict[str, Any]:
    """Return API liveness and dependency/worker readiness."""
    liveness = {"status": "alive", "alive": True}
    try:
        storage.check_database_ready()
        heartbeats = storage.get_latest_process_health()
        readiness = build_readiness_report(
            heartbeats,
            database_ready=True,
        )
    except sqlite3.Error as error:
        log.exception("readiness check could not access the local database")
        readiness = build_readiness_report(
            {},
            database_ready=False,
            database_error=str(error),
        )
    return {"liveness": liveness, "readiness": readiness}


def run_api_server(state: Any, stop_event: Any, channels: Any) -> None:
    # Demo integration: expose shared readings, decisions, and worker status.
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/health/live":
                payload = {"status": "alive", "alive": True}
                status_code = 200
                body = json.dumps(payload).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            elif self.path == "/health/ready":
                health = health_snapshot()
                payload = health["readiness"]
                status_code = 200 if payload["ready"] else 503
                body = json.dumps(payload).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            elif self.path == "/api/status":
                snapshot = dict(state)
                worker_names = {
                    key.split(":", 1)[1]
                    for key in snapshot
                    if key.startswith("worker_status:")
                }
                workers = {}

                for name in worker_names:
                    pid = snapshot.get(f"worker_pid:{name}")
                    status = snapshot.get(f"worker_status:{name}")

                    cpu_percent = None
                    memory_mb = None

                    if pid and status == "running":
                        try:
                            process = PROCESS_CACHE.get(pid)

                            if process is None:
                                process = psutil.Process(pid)
                                PROCESS_CACHE[pid] = process
                            if (
                                not process.is_running()
                                or process.status() == psutil.STATUS_ZOMBIE
                            ):
                                status = "stopped"
                            else:
                                cpu_percent = process.cpu_percent(interval=None)
                                memory_mb = round(
                                    process.memory_info().rss / (1024 * 1024), 2
                                )
                        except psutil.NoSuchProcess:
                            status = "stopped"
                        except psutil.AccessDenied:
                            status = "unknown"

                    workers[name] = {
                        "status": status,
                        "pid": pid,
                        "cpu_percent": cpu_percent,
                        "memory_mb": memory_mb,
                        "restart_count": snapshot.get(
                            f"worker_restart_count:{name}", 0
                        ),
                        "last_exit_code": snapshot.get(
                            f"worker_last_exit_code:{name}"
                        ),
                    }

                payload = {
                    "workers": workers,
                    "recent_readings": snapshot.get("recent_readings", []),
                    "recent_decisions": snapshot.get("recent_decisions", []),
                    "pending_events": snapshot.get("pending_events", 0),
                    "wan_online": channels.wan_online.is_set(),
                    "health": health_snapshot(),
                }
                status_code = 200
                body = json.dumps(payload).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            elif self.path in ("/", "/index.html"):
                status_code = 200
                body = DASHBOARD_PATH.read_bytes()
                content_type = "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return

            self.send_response(status_code)
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

            body = json.dumps({
                "success": True,
                "message": message,
                "wan_online": channels.wan_online.is_set(),
            }).encode("utf-8")

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
