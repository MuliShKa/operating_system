-- Database schema for the OS4 node (IoT Edge Gateway, Techno-Strip Tower)

PRAGMA foreign_keys = ON;

-- Every stored reading keeps BOTH clocks (scenario OS4-2):
--   observed_at : when the SENSOR measured it (event time, never overwritten)
--   received_at : when THIS node received it (receipt time)
-- Both are UTC ISO-8601 with microseconds, so text order = time order.
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,          -- PM25, NOISE, LUX or MIST_CANNON_RELAY
    observed_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
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
    details TEXT,                  -- JSON: pid, cpu %, rss MB, context switches
    checked_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Store-and-forward queue towards the Urban Data Platform (OS4-5).
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

-- One row: the mist cannon relay. Every change bumps `version`; the writer uses
-- "UPDATE ... WHERE version = ?" so a stale writer is rejected, not applied.
CREATE TABLE IF NOT EXISTS relay_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    state TEXT NOT NULL CHECK (state IN ('ON', 'OFF')),
    version INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO relay_state (id, state, version) VALUES (1, 'OFF', 0);

-- OS4-5: local PM2.5 compared with the AirKorea station baseline.
CREATE TABLE IF NOT EXISTS baseline_checks (
    check_id INTEGER PRIMARY KEY AUTOINCREMENT,
    checked_at TEXT NOT NULL DEFAULT (datetime('now')),
    station TEXT NOT NULL,
    source TEXT NOT NULL,          -- the CSV file used (SAMPLE files are flagged)
    is_sample INTEGER NOT NULL,
    match_kind TEXT NOT NULL,      -- 'exact-hour' or 'hour-of-day'
    baseline_pm25 REAL NOT NULL,
    local_median REAL NOT NULL,
    window_readings INTEGER NOT NULL,
    bias REAL NOT NULL,            -- local - baseline
    local_grade TEXT NOT NULL,
    baseline_grade TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('AGREE', 'DEVIATES'))
);

CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox(status, outbox_id);
CREATE INDEX IF NOT EXISTS idx_events_observed ON events(event_type, observed_at);
