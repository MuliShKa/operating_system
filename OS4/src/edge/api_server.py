"""Small local-only HTTP API and dashboard server (zero external web framework)."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from edge.config import API_HOST, API_PORT, load_config
from edge.health import process_metrics
from edge.ipc import SIM_FLAGS

DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "ui" / "static" / "index.html"


def build_status(state: Any, channels: Any) -> dict:
    """Everything the dashboard shows, from the shared state and the IPC objects."""
    snapshot = dict(state)
    names = sorted(key.split(":", 1)[1] for key in snapshot if key.startswith("worker_status:"))
    workers = {}
    for name in names:
        pid, status = snapshot.get(f"worker_pid:{name}"), snapshot.get(f"worker_status:{name}")
        workers[name] = {"status": status, "pid": pid, **process_metrics(pid, status)}

    ingest = snapshot.get("ingest", {})
    channel_stats = snapshot.get("channels", {})
    merged = {}
    for sid in sorted(set(channel_stats) | set(ingest.get("channels", {}))):
        merged[sid] = {**ingest.get("channels", {}).get(sid, {}), **channel_stats.get(sid, {})}

    config = load_config()
    return {
        "node_id": config["node_id"],
        "workers": workers,
        "channels": merged,
        "sockets": ingest.get("sockets", {}),
        "recent_readings": snapshot.get("recent_readings", []),
        "recent_decisions": snapshot.get("recent_decisions", []),
        "recent_actuations": snapshot.get("recent_actuations", []),
        "actuator": {
            "applied": snapshot.get("actuator_applied", 0),
            "expired": snapshot.get("actuator_expired", 0),
        },
        "relay_state": snapshot.get("relay_state"),
        "baseline": snapshot.get("baseline"),
        "queue": channels.sensor_events.stats(),
        "pending_events": snapshot.get("pending_events", 0),
        "wan_online": channels.wan_online.is_set(),
        "sim": {name: channels.sim[name].is_set() for name in SIM_FLAGS},
        "thresholds": {
            "pm25_bad": config["pm25_bad_threshold"],
            "pm25_very_bad": config["pm25_very_bad_threshold"],
            "mist_ttl_s": config["mist_command_ttl_seconds"],
        },
    }


def run_api_server(state: Any, stop_event: Any, channels: Any) -> None:
    """Expose shared readings, decisions, relay state, queue stats and worker status."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/api/status":
                body = json.dumps(build_status(state, channels)).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            elif self.path in ("/", "/index.html"):
                body = DASHBOARD_PATH.read_bytes()
                content_type = "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self._respond(body, content_type)

        def do_POST(self) -> None:
            parts = self.path.strip("/").split("/")
            if self.path == "/api/wan/offline":
                channels.wan_online.clear()
                message = "WAN connection disabled"
            elif self.path == "/api/wan/online":
                channels.wan_online.set()
                message = "WAN connection restored"
            elif len(parts) == 4 and parts[:2] == ["api", "sim"] and parts[2] in SIM_FLAGS and parts[3] in ("on", "off"):
                # Steers the SIMULATED devices only (dust episode, night, a hung or frozen PM2.5 sensor ...).
                flag = channels.sim[parts[2]]
                flag.set() if parts[3] == "on" else flag.clear()
                message = f"simulation switch '{parts[2]}' is {parts[3]}"
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

    # Loopback only by default: the console is local, not public (EDGE_API_HOST / EDGE_API_PORT).
    server = HTTPServer((API_HOST, API_PORT), Handler)
    server.timeout = 0.5
    try:
        while not stop_event.is_set():
            server.handle_request()
    finally:
        server.server_close()
