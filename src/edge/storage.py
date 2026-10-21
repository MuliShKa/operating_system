
"""SQLite storage for the Songdo Edge Intelligence project."""

import json
import sqlite3
from pathlib import Path


# Project paths
PROJECT_DIR = Path(__file__).resolve().parents[2]
DATABASE_PATH = PROJECT_DIR / "data" / "songdo.db"
SCHEMA_PATH = PROJECT_DIR / "sql" / "schema.sql"


def get_connection():
    """Open a database connection with safe defaults."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        DATABASE_PATH,
        timeout=10
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")

    return connection


def initialize_database():
    """Create the tables and enable SQLite WAL mode."""
    with get_connection() as connection:
        connection.execute("PRAGMA journal_mode = WAL")

        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        connection.executescript(schema)


def save_event(event_id, event_type, event_time, payload):
    """Save an event and queue it for upstream delivery atomically."""
    payload_json = json.dumps(
        payload,
        ensure_ascii=False
    )

    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO events
                (event_id, event_type, event_time, payload)
            VALUES (?, ?, ?, ?)
            """,
            (event_id, event_type, event_time, payload_json)
        )

        # Queue the event only if it was newly inserted.
        if cursor.rowcount == 0:
            return False

        connection.execute(
            """
            INSERT INTO outbox (event_id, payload)
            VALUES (?, ?)
            """,
            (event_id, payload_json)
        )

    return True


def save_decision(event_id, decision_type, reason=None):
    """Save a decision made by the local system."""
    with get_connection() as connection:
        cursor = connection.execute(
            "SELECT 1 FROM events WHERE event_id = ?",
            (event_id,)
        )

        if cursor.fetchone() is None:
            raise ValueError(
                f"Unknown event_id: {event_id}"
            )

        connection.execute(
            """
            INSERT INTO decisions
                (event_id, decision_type, reason)
            VALUES (?, ?, ?)
            """,
            (event_id, decision_type, reason)
        )


def save_process_health(process_name, status, details=None):
    """Record a process health check."""
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO process_health
                (process_name, status, details)
            VALUES (?, ?, ?)
            """,
            (process_name, status, details)
        )


def get_pending_events(limit=100):
    """Return events waiting to be sent to the server."""
    if limit < 1:
        raise ValueError("limit must be positive")

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT outbox_id, event_id, payload, attempts
            FROM outbox
            WHERE status = 'pending'
            ORDER BY outbox_id
            LIMIT ?
            """,
            (limit,)
        ).fetchall()

    return [dict(row) for row in rows]


def mark_event_sent(event_id):
    """Mark an event as sent after server confirmation."""
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE outbox
            SET status = 'sent',
                sent_at = datetime('now')
            WHERE event_id = ?
              AND status = 'pending'
            """,
            (event_id,)
        )

        return cursor.rowcount == 1
