"""SQLite persistence: durable outbox, process health and robot state.

Every call opens a short-lived connection so the functions are safe to use
from any worker process. WAL mode lets the uplink read while the controller
and safety monitor write.
"""

import json
import sqlite3
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "sql" / "schema.sql"
BUSY_TIMEOUT_MS = 5000


@contextmanager
def connect(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    """Yield a connection inside one transaction, then close it."""
    connection = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_MS / 1000)
    connection.row_factory = sqlite3.Row
    connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init_db(db_path: str | Path) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def record_event(db_path: str | Path, event_type: str, payload: dict) -> str:
    """Append an event to the outbox and return its id."""
    event_id = str(uuid.uuid4())
    with connect(db_path) as connection:
        connection.execute(
            "INSERT INTO outbox (event_id, event_type, payload) VALUES (?, ?, ?)",
            (event_id, event_type, json.dumps(payload, separators=(",", ":"))),
        )
    return event_id


def pending_events(db_path: str | Path, limit: int) -> list[dict]:
    """Oldest unsent events first."""
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT event_id, event_type, payload, created_at FROM outbox"
            " WHERE sent_at IS NULL ORDER BY seq LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {**dict(row), "payload": json.loads(row["payload"])}
        for row in rows
    ]


def mark_sent(db_path: str | Path, event_ids: Iterable[str]) -> int:
    with connect(db_path) as connection:
        cursor = connection.executemany(
            "UPDATE outbox SET sent_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
            " WHERE event_id = ? AND sent_at IS NULL",
            ((event_id,) for event_id in event_ids),
        )
    return cursor.rowcount


def outbox_counts(db_path: str | Path) -> dict[str, int]:
    with connect(db_path) as connection:
        total, pending = connection.execute(
            "SELECT COUNT(*), COUNT(*) FILTER (WHERE sent_at IS NULL) FROM outbox"
        ).fetchone()
    return {"total": total, "pending": pending, "sent": total - pending}


def record_health(
    db_path: str | Path,
    process_name: str,
    pid: int | None,
    status: str,
    details: str | None = None,
) -> None:
    with connect(db_path) as connection:
        connection.execute(
            "INSERT INTO process_health (process_name, pid, status, details)"
            " VALUES (?, ?, ?, ?)",
            (process_name, pid, status, details),
        )


def save_state(db_path: str | Path, key: str, value: str) -> None:
    with connect(db_path) as connection:
        connection.execute(
            "INSERT INTO robot_state (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
            " updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
            (key, value),
        )


def load_state(db_path: str | Path, key: str) -> str | None:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT value FROM robot_state WHERE key = ?", (key,)
        ).fetchone()
    return None if row is None else row["value"]
