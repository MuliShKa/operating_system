"""Receiver worker: the mock upstream server. It stores each event ID only once (OS1-5)."""

import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from edge.node_config import RECEIVER_PORT
from edge.core.storage import DATABASE_PATH

# Its own database next to the node's one (node.db -> node_upstream.db).
RECEIVER_DATABASE = DATABASE_PATH.with_name(f"{DATABASE_PATH.stem}_upstream.db")


def initialize_receiver_database() -> None:
    RECEIVER_DATABASE.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(RECEIVER_DATABASE) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS received_events (
                event_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                received_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)


def accept_event(event: dict) -> bool:
    """
    Store the event; return False if this ID was already received.
    event_id is the PRIMARY KEY and INSERT OR IGNORE skips a second copy:
    a batch sent twice is stored once (idempotent delivery).
    """
    event_id = event.get("event_id")
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("event_id must be a non-empty string")
    with sqlite3.connect(RECEIVER_DATABASE, timeout=10) as connection:
        cursor = connection.execute(
            "INSERT OR IGNORE INTO received_events (event_id, payload) VALUES (?, ?)",
            (event_id, json.dumps(event.get("payload"), ensure_ascii=False, sort_keys=True)),
        )
    return cursor.rowcount == 1


def run_receiver(stop_event, host: str = "127.0.0.1", port: int = RECEIVER_PORT) -> None:
    initialize_receiver_database()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path != "/api/events":
                self.send_error(404)
                return
            try:
                event = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                new = accept_event(event)
            except (ValueError, AttributeError):  # bad JSON, not an object, no event_id
                self.send_error(400, "Invalid event JSON")
                return
            except sqlite3.Error:
                self.send_error(500, "Receiver storage error")
                return
            body = json.dumps({"accepted": True, "duplicate": not new, "event_id": event["event_id"]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args) -> None:
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    server.timeout = 0.5  # check the stop flag twice a second
    print(f"Mock upstream receiver listening at http://{host}:{port}", flush=True)
    try:
        while not stop_event.is_set():
            server.handle_request()
    finally:
        server.server_close()


if __name__ == "__main__":
    import threading

    run_receiver(threading.Event())
