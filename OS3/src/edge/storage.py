"""SQLite storage for the OS3 node: events, decisions, outbox and sign state."""

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


# Project paths
PROJECT_DIR = Path(__file__).resolve().parents[2]
DATABASE_PATH = Path(
    os.environ.get(
        "EDGE_DATABASE_PATH",
        str(PROJECT_DIR / "data" / "songdo.db"),
    )
)
SCHEMA_PATH = PROJECT_DIR / "sql" / "schema.sql"


def get_connection():
    """Open a database connection with safe defaults."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")

    return connection


@contextmanager
def _managed_connection():
    """Open a connection, commit on success, roll back on error, always close."""
    connection = get_connection()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database():
    """Create the tables and enable SQLite WAL mode."""
    with _managed_connection() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def save_event(event_id, event_type, event_time, payload):
    """Save an event and queue it for upstream delivery, in ONE transaction."""
    payload_json = json.dumps(payload, ensure_ascii=False)

    with _managed_connection() as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO events
                (event_id, event_type, event_time, payload)
            VALUES (?, ?, ?, ?)
            """,
            (event_id, event_type, event_time, payload_json),
        )

        # Queue the event only if it was newly inserted.
        if cursor.rowcount == 0:
            return False

        connection.execute(
            "INSERT INTO outbox (event_id, payload) VALUES (?, ?)",
            (event_id, payload_json),
        )

    return True


def save_decision(event_id, decision_type, reason=None, value=None):
    """
    Save a decision made by the local system.
    `event_id` may be None for a decision that no single event caused
    (for example the sign returning to normal when a command expires).
    """
    with _managed_connection() as connection:
        if event_id is not None:
            cursor = connection.execute(
                "SELECT 1 FROM events WHERE event_id = ?", (event_id,)
            )
            if cursor.fetchone() is None:
                raise ValueError(f"Unknown event_id: {event_id}")

        connection.execute(
            """
            INSERT INTO decisions (event_id, decision_type, reason, value)
            VALUES (?, ?, ?, ?)
            """,
            (event_id, decision_type, reason, value),
        )


def save_process_health(process_name, status, details=None):
    """Record a process health check."""
    with _managed_connection() as connection:
        connection.execute(
            """
            INSERT INTO process_health (process_name, status, details)
            VALUES (?, ?, ?)
            """,
            (process_name, status, details),
        )


def get_pending_events(limit=100):
    """Return events waiting to be sent to the server, oldest first."""
    if limit < 1:
        raise ValueError("limit must be positive")

    with _managed_connection() as connection:
        rows = connection.execute(
            """
            SELECT outbox_id, event_id, payload, attempts
            FROM outbox
            WHERE status = 'pending'
            ORDER BY outbox_id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in rows]


def get_pending_event_count():
    """Return the exact number of events waiting for upstream delivery."""
    with _managed_connection() as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM outbox WHERE status = 'pending'"
        ).fetchone()[0]


def mark_event_sent(event_id):
    """Mark an event as sent. Call it only after the receiver confirmed delivery."""
    with _managed_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE outbox
            SET status = 'sent', sent_at = datetime('now')
            WHERE event_id = ? AND status = 'pending'
            """,
            (event_id,),
        )
        return cursor.rowcount == 1


def mark_event_attempt(event_id):
    """Increment the delivery attempt count of a pending event."""
    with _managed_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE outbox
            SET attempts = attempts + 1
            WHERE event_id = ? AND status = 'pending'
            """,
            (event_id,),
        )
        return cursor.rowcount == 1


# --- Scenario OS3-4: transactional, version-guarded sign state ---------------

def get_sign_state():
    """Return the current sign state: speed_limit_kmh, version, updated_at."""
    with _managed_connection() as connection:
        row = connection.execute(
            "SELECT speed_limit_kmh, version, updated_at FROM sign_state WHERE id = 1"
        ).fetchone()
    return dict(row)


def update_sign_state(speed_limit_kmh, expected_version):
    """
    Change the sign limit only if nobody changed it since we read `expected_version`.

    The check and the write are ONE atomic UPDATE inside a transaction:
    returns True if this writer won, False if another writer got there first
    (the caller re-reads the state and decides again). This prevents lost
    updates and torn reads across processes.
    """
    with _managed_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE sign_state
            SET speed_limit_kmh = ?,
                version = version + 1,
                updated_at = datetime('now')
            WHERE id = 1 AND version = ?
            """,
            (speed_limit_kmh, expected_version),
        )
        return cursor.rowcount == 1
