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
UPSTREAM_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "sql" / "upstream_schema.sql"
)
BUSY_TIMEOUT_MS = 5000


@contextmanager
def connect(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    """Yield a connection inside one transaction, then close it."""
    connection = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_MS / 1000)
    connection.row_factory = sqlite3.Row
    connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA synchronous = FULL")
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


def init_upstream_db(db_path: str | Path) -> None:
    """Create the receiver database used by the local upstream integration."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(UPSTREAM_SCHEMA_PATH.read_text(encoding="utf-8"))


def record_event(db_path: str | Path, event_type: str, payload: dict) -> str:
    """Append an event to the outbox and return its id."""
    event_id = str(uuid.uuid4())
    with connect(db_path) as connection:
        connection.execute(
            "INSERT INTO outbox (event_id, event_type, payload) VALUES (?, ?, ?)",
            (event_id, event_type, json.dumps(payload, separators=(",", ":"))),
        )
    return event_id


def latch_estop(db_path: str | Path, node_name: str) -> str:
    """Persist the E-stop state and its outbox event in one transaction."""
    event_id = str(uuid.uuid4())
    with connect(db_path) as connection:
        connection.execute(
            "INSERT INTO robot_state (key, value) VALUES ('estop_latched', '1')"
            " ON CONFLICT(key) DO UPDATE SET value = '1',"
            " updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
        )
        connection.execute(
            "INSERT INTO outbox (event_id, event_type, payload) VALUES (?, ?, ?)",
            (
                event_id,
                "ESTOP_LATCHED",
                json.dumps({"node": node_name}, separators=(",", ":")),
            ),
        )
    return event_id


def pending_events(db_path: str | Path, limit: int) -> list[dict]:
    """Oldest unsent events first."""
    if limit < 1:
        raise ValueError("limit must be positive")
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


def latest_outbox_sequence(db_path: str | Path) -> int:
    """Return the last allocated outbox sequence as a checkpoint."""
    with connect(db_path) as connection:
        return connection.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM outbox"
        ).fetchone()[0]


def outbox_event_ids_after(db_path: str | Path, sequence: int) -> list[str]:
    """Return event IDs created after an outbox sequence checkpoint."""
    if sequence < 0:
        raise ValueError("sequence must be non-negative")
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT event_id FROM outbox WHERE seq > ? ORDER BY seq",
            (sequence,),
        ).fetchall()
    return [row["event_id"] for row in rows]


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


def accept_upstream_events(db_path: str | Path, events: list[dict]) -> list[str]:
    """Durably accept a batch and return IDs safe for the sender to acknowledge."""
    rows = []
    event_ids = []
    for event in events:
        try:
            event_id = event["event_id"]
            event_type = event["event_type"]
            payload = event["payload"]
            created_at = event["created_at"]
        except (KeyError, TypeError) as error:
            raise ValueError(f"malformed event: {error}") from error
        if (
            not isinstance(event_id, str)
            or not event_id
            or not isinstance(event_type, str)
            or not event_type
            or not isinstance(payload, dict)
            or not isinstance(created_at, str)
        ):
            raise ValueError("event fields have invalid types or empty identifiers")
        event_ids.append(event_id)
        rows.append(
            (
                event_id,
                event_type,
                json.dumps(payload, separators=(",", ":")),
                created_at,
            )
        )

    with connect(db_path) as connection:
        connection.executemany(
            "INSERT OR IGNORE INTO received_events "
            "(event_id, event_type, payload, source_created_at) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )
    return event_ids


def upstream_event_count(db_path: str | Path) -> int:
    with connect(db_path) as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM received_events"
        ).fetchone()[0]


def upstream_contains_events(db_path: str | Path, event_ids: list[str]) -> list[str]:
    if not event_ids:
        return []
    placeholders = ",".join("?" for _ in event_ids)
    with connect(db_path) as connection:
        rows = connection.execute(
            f"SELECT event_id FROM received_events WHERE event_id IN ({placeholders})",
            event_ids,
        ).fetchall()
    return [row["event_id"] for row in rows]


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


def save_states(db_path: str | Path, values: dict[str, str]) -> None:
    if not values:
        return
    with connect(db_path) as connection:
        connection.executemany(
            "INSERT INTO robot_state (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
            " updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
            values.items(),
        )


def load_states(db_path: str | Path, keys: list[str]) -> dict[str, str]:
    if not keys:
        return {}
    placeholders = ",".join("?" for _ in keys)
    with connect(db_path) as connection:
        rows = connection.execute(
            f"SELECT key, value FROM robot_state WHERE key IN ({placeholders})",
            keys,
        ).fetchall()
    return {row["key"]: row["value"] for row in rows}


def latest_process_health(db_path: str | Path) -> list[dict]:
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT h.process_name, h.pid, h.status, h.details, h.checked_at "
            "FROM process_health AS h "
            "WHERE h.id = (SELECT MAX(latest.id) FROM process_health AS latest "
            "WHERE latest.process_name = h.process_name) "
            "ORDER BY h.process_name"
        ).fetchall()
    return [dict(row) for row in rows]


def recent_events(db_path: str | Path, limit: int = 50) -> list[dict]:
    if limit < 1:
        raise ValueError("limit must be positive")
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT event_id, event_type, payload, created_at, sent_at "
            "FROM outbox ORDER BY seq DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {**dict(row), "payload": json.loads(row["payload"])}
        for row in rows
    ]
