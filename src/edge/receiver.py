"""Local mock upstream receiver with event-ID deduplication."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from edge import storage


PROJECT_DIR = Path(__file__).resolve().parents[2]
RECEIVER_DATABASE = PROJECT_DIR / "data" / "upstream_receiver.db"


def initialize_receiver_database() -> None:
    """Create the receiver's event table."""
    RECEIVER_DATABASE.parent.mkdir(parents=True, exist_ok=True)

    # "with connect()" only commits, closing() is what releases the file
    with closing(sqlite3.connect(RECEIVER_DATABASE)) as connection, connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS received_events (
                event_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                received_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)


def accept_event(event: dict[str, Any]) -> bool:
    """Store an event once. Return False if its ID was already received."""
    event_id = event.get("event_id")
    payload = event.get("payload")

    if not isinstance(event_id, str) or not event_id:
        raise ValueError("event_id must be a non-empty string")

    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    with closing(sqlite3.connect(RECEIVER_DATABASE, timeout=10)) as connection, connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO received_events (event_id, payload)
            VALUES (?, ?)
            """,
            (event_id, payload_json),
        )

    return cursor.rowcount == 1


def get_received_count() -> int:
    """How many different events made it upstream."""
    initialize_receiver_database()
    with closing(sqlite3.connect(RECEIVER_DATABASE, timeout=10)) as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM received_events"
        ).fetchone()[0]


def check_conservation() -> dict[str, Any]:
    """No event lost: everything created is either upstream or still queued.

    Only meaningful when the sync worker is idle, otherwise an event can be
    received upstream but not marked sent yet and gets counted twice.
    """
    # need to ask: if someone wipes data/songdo.db but not upstream_receiver.db
    # the numbers won't match anymore, do we reset both at startup?
    created = storage.get_event_count()
    received = get_received_count()
    queued = storage.get_pending_event_count()
    return {
        "created": created,
        "received": received,
        "queued": queued,
        "ok": created == received + queued,
    }


def run_receiver(stop_event: Any, host: str = "127.0.0.1", port: int = 8001) -> None:
    """Run the local HTTP endpoint used by the synchronization worker."""
    initialize_receiver_database()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path != "/api/events":
                self.send_error(404)
                return

            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if content_length <= 0 or content_length > 1_000_000:
                    self.send_error(400, "Invalid content length")
                    return

                raw_body = self.rfile.read(content_length)
                event = json.loads(raw_body.decode("utf-8"))

                if not isinstance(event, dict):
                    self.send_error(400, "Expected a JSON object")
                    return

                inserted = accept_event(event)
                response = {
                    "accepted": True,
                    "duplicate": not inserted,
                    "event_id": event["event_id"],
                }
                body = json.dumps(response).encode("utf-8")

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            except (ValueError, KeyError, UnicodeDecodeError, json.JSONDecodeError):
                self.send_error(400, "Invalid event JSON")
            except (OSError, sqlite3.Error):
                self.send_error(500, "Receiver storage error")

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    server.timeout = 0.5
    print(f"Mock upstream receiver listening at http://{host}:{port}", flush=True)
    try:
        while not stop_event.is_set():
            server.handle_request()
    finally:
        server.server_close()
        print("Mock upstream receiver stopped.", flush=True)


if __name__ == "__main__":
    # run alone for debugging, Ctrl+C to stop
    import threading
    try:
        run_receiver(threading.Event())
    except KeyboardInterrupt:
        pass
