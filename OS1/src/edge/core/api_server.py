"""API worker: the local dashboard and its JSON status, on 127.0.0.1 only."""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from edge.core.ipc import list_workers
from edge.os1_bonus_trends import history
from edge.node_config import API_HOST, API_PORT, NODE_NAME, RULE

DASHBOARD_PATH = Path(__file__).resolve().parents[2] / "ui" / "static" / "index.html"


def build_status(channels, state) -> dict:
    snapshot = dict(state)
    samples = snapshot.get("proc_samples", {})  # CPU and memory, measured by ProcSampler (OS1-4)
    workers = {}
    for name, worker in list_workers(state).items():
        sample = samples.get(name, {}) if worker["status"] == "running" else {}
        workers[name] = {
            **worker,
            "cpu_percent": sample.get("cpu_pct"),
            "memory_mb": round(sample["rss_kb"] / 1024, 2) if "rss_kb" in sample else None,
        }
    return {
        "node": {"name": NODE_NAME, "rule": RULE},
        "building": snapshot.get("building"),
        "workers": workers,
        "recent_readings": snapshot.get("recent_readings", []),
        "recent_decisions": snapshot.get("recent_decisions", []),
        "pending_events": snapshot.get("pending_events", 0),
        "wan_online": channels.wan_online.is_set(),
        "damper_pct": snapshot.get("damper_pct", 0),
        "actuator": {"applied": snapshot.get("actuator_applied", 0), "expired": snapshot.get("actuator_expired", 0)},
        "proc_samples": samples,
    }


def history_from_query(query: str) -> dict:
    """/api/history?minutes=5 or ?since=..&until=..&split=.. (wall-clock seconds)."""
    params = {key: float(values[0]) for key, values in parse_qs(query).items()}
    minutes = min(max(params.get("minutes", 5), 1), 60)
    return history.build_history(minutes, params.get("since"), params.get("until"), params.get("split"))


def run_api_server(channels, state) -> None:
    class Handler(BaseHTTPRequestHandler):
        def reply(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path, _, query = self.path.partition("?")
            if path.startswith("/api/history"):
                try:
                    found = history_from_query(query)
                except ValueError:
                    self.send_error(400, "since, until, split and minutes must be numbers")
                    return
            if path == "/api/status":
                self.reply(json.dumps(build_status(channels, state)).encode(), "application/json")
            elif path == "/api/history":  # Bonus: trends + comparison
                self.reply(json.dumps(found).encode(), "application/json")
            elif path == "/api/history.csv":  # Bonus: the same points, as a file
                self.reply(history.to_csv(found).encode(), "text/csv; charset=utf-8")
            elif path in ("/", "/index.html"):
                self.reply(DASHBOARD_PATH.read_bytes(), "text/html; charset=utf-8")
            else:
                self.send_error(404)

        def do_POST(self) -> None:
            # The two dashboard buttons that simulate the Internet cut (OS1-5).
            if self.path == "/api/wan/offline":
                channels.wan_online.clear()
                message = "WAN connection disabled"
            elif self.path == "/api/wan/online":
                channels.wan_online.set()
                message = "WAN connection restored"
            else:
                self.send_error(404)
                return
            body = {"success": True, "message": message, "wan_online": channels.wan_online.is_set()}
            self.reply(json.dumps(body).encode(), "application/json")

        def log_message(self, *_args) -> None:
            pass  # keep the terminal quiet

    server = HTTPServer((API_HOST, API_PORT), Handler)
    server.timeout = 0.5  # check the stop flag twice a second
    try:
        while not channels.stop.is_set():
            server.handle_request()
    finally:
        server.server_close()
