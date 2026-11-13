
-- Database schema for the Songdo Edge Intelligence project

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
    event_id TEXT,
    decision_type TEXT NOT NULL,
    reason TEXT,
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

CREATE INDEX IF NOT EXISTS idx_outbox_status
    ON outbox(status, outbox_id);

CREATE INDEX IF NOT EXISTS idx_events_time
    ON events(event_time);

-- OS1-1: building inventory read from the cached VWorld GeoJSON.
CREATE TABLE IF NOT EXISTS building_inventory (
    building_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    properties TEXT NOT NULL,
    geometry TEXT NOT NULL,
    source TEXT NOT NULL,
    loaded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Handbook table names, as views over the team schema.
CREATE VIEW IF NOT EXISTS sensor_events AS
    SELECT event_id, event_type AS sensor_id, event_time, payload, created_at FROM events;

CREATE VIEW IF NOT EXISTS durable_outbox AS
    SELECT * FROM outbox;
