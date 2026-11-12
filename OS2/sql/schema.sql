-- OS2 robot edge controller: local durable storage.

CREATE TABLE IF NOT EXISTS outbox (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    sent_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_outbox_pending
    ON outbox(seq) WHERE sent_at IS NULL;

CREATE TABLE IF NOT EXISTS process_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    process_name TEXT NOT NULL,
    pid INTEGER,
    status TEXT NOT NULL,
    details TEXT,
    checked_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Survives worker restarts, e.g. the E-stop latch.
CREATE TABLE IF NOT EXISTS robot_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
