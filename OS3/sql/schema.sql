-- Database schema for the OS3 node (Autonomous Mobility Edge Node)

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    event_time TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT,                 -- NULL when the decision is not caused by one event (e.g. TTL expiry)
    decision_type TEXT NOT NULL,
    reason TEXT,
    value REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (event_id) REFERENCES events(event_id)
);

CREATE TABLE IF NOT EXISTS process_health (
    health_id INTEGER PRIMARY KEY AUTOINCREMENT,
    process_name TEXT NOT NULL,
    status TEXT NOT NULL,
    details TEXT,
    checked_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS outbox (
    outbox_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'sent')),
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    sent_at TEXT,
    FOREIGN KEY (event_id) REFERENCES events(event_id)
);

-- Scenario OS3-4: one row holding the current variable speed sign state.
-- Every change must bump `version`; writers use "UPDATE ... WHERE version = ?"
-- so a stale writer is rejected instead of overwriting a newer state.
CREATE TABLE IF NOT EXISTS sign_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    speed_limit_kmh INTEGER NOT NULL,
    version INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO sign_state (id, speed_limit_kmh, version)
VALUES (1, 50, 0);

CREATE INDEX IF NOT EXISTS idx_outbox_status
    ON outbox(status, outbox_id);

CREATE INDEX IF NOT EXISTS idx_events_time
    ON events(event_time);
