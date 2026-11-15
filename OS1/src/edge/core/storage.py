"""SQLite storage of the node (WAL mode)."""

import json
import os
import sqlite3
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[3]
DATABASE_PATH = Path(os.environ.get("EDGE_DATABASE_PATH", PROJECT_DIR / "data" / "songdo.db"))
SCHEMA_PATH = PROJECT_DIR / "sql" / "schema.sql"


def connect():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    # Wait up to 10 s for another process's write lock instead of failing at once.
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def execute_in_one_transaction(statements):
    """
    Run several (sql, params) statements in ONE transaction:
    either all of them are saved, or none (rollback on error).
    """
    connection = connect()
    try:
        with connection:  # commit at the end, or roll back on error
            for sql, params in statements:
                connection.execute(sql, params)
    finally:
        connection.close()


def execute(sql, params=()):
    """Run one SQL statement and return the rows."""
    connection = connect()
    try:
        with connection:
            return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def initialize_database():
    """Create the tables and switch to WAL mode (readers don't block the writer)."""
    connection = connect()
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    finally:
        connection.close()


def save_event(event_id, event_type, event_time, payload):
    """
    Save the event AND its outbox row in ONE transaction:
    no event can be stored without being queued for upload.
    """
    payload_json = json.dumps(payload, ensure_ascii=False)
    execute_in_one_transaction([
        ("INSERT INTO events (event_id, event_type, event_time, payload) VALUES (?, ?, ?, ?)",
         (event_id, event_type, event_time, payload_json)),
        ("INSERT INTO outbox (event_id, payload) VALUES (?, ?)",
         (event_id, payload_json)),
    ])


def save_decision(event_id, decision_type, reason=None):
    execute("INSERT INTO decisions (event_id, decision_type, reason) VALUES (?, ?, ?)",
            (event_id, decision_type, reason))


def save_process_health(process_name, status, details=None):
    execute("INSERT INTO process_health (process_name, status, details) VALUES (?, ?, ?)",
            (process_name, status, details))


def get_pending_events(limit):
    """The oldest events not yet delivered upstream."""
    rows = execute("SELECT event_id, payload FROM outbox WHERE status = 'pending' ORDER BY outbox_id LIMIT ?",
                   (limit,))
    return [dict(row) for row in rows]


def count_pending_events():
    return execute("SELECT COUNT(*) FROM outbox WHERE status = 'pending'")[0][0]


def mark_sent(event_id):
    execute("UPDATE outbox SET status = 'sent', sent_at = datetime('now') WHERE event_id = ?", (event_id,))


def mark_failed_attempt(event_id):
    execute("UPDATE outbox SET attempts = attempts + 1 WHERE event_id = ?", (event_id,))
