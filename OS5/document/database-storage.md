# Database Storage: Implementation Notes

## Purpose

This part of the Songdo Smart Sluice Gate project provides local SQLite
storage. The system should continue recording events when the internet
is unavailable, then allow the SyncWorker to find events waiting to be
sent.

## Files created or implemented

-   `sql/schema.sql` --- defines the database tables and indexes.
-   `src/edge/storage.py` --- Python functions for initializing the
    database and storing/retrieving records.
-   `src/edge/backup.py` --- creates an online SQLite backup while holding an
    exclusive `flock`, then verifies the backup with `PRAGMA integrity_check`.
-   `tests/` --- covers schema, storage, backup locking, worker recovery, and
    the compound WAN/Processor failure scenario.

## Database tables

### `events`

Stores the original event, identified by `event_id`. Fields include
event type, event time, JSON payload, and creation time.

### `decisions`

Stores decisions made by the local system, optionally linked to the
event that caused the decision. For example, a high water level can
result in `BACKUP_SLUICE_GATE_OPEN`.

### `process_health`

Stores process health checks, including the process name, status,
optional details, and check time.

### `outbox`

Stores events waiting to be sent upstream. Each `event_id` is unique in
this table. `status` is `pending` or `sent`; the row also tracks
attempts, creation time, and send time. Indexes help find pending
records and query events by time.

## Main functions in `src/edge/storage.py`

-   `get_connection()` --- opens a connection to the SQLite database,
    enables foreign-key checks, and sets a busy timeout.
-   `initialize_database()` --- enables SQLite WAL mode and executes
    `sql/schema.sql`.
-   `save_event(event_id, event_type, event_time, payload)` ---
    serializes the payload as JSON and inserts the event. If it is a new
    event, it also inserts the matching outbox row. Both inserts happen
    in the same SQLite transaction. It returns `True` for a newly
    inserted event and `False` if that event ID already exists.
-   `save_decision(event_id, decision_type, reason=None)` --- verifies
    that the event exists and stores the related decision.
-   `save_process_health(process_name, status, details=None)` --- stores
    a process health record.
-   `get_pending_events(limit=100)` --- returns pending outbox rows in
    insertion order, up to the requested limit.
-   `mark_event_sent(event_id)` --- marks a pending outbox row as sent
    and records the send time. It should only be called after the
    receiver confirms successful delivery.

## How to validate

From the OS5 project root, run:

```bash
python3 scenarios/run_all_scenarios.py
```

The runner discovers and executes every OS5 `test_*.py` module, including the
backup integrity/lock check and the offline outbox delivery test.

## Reliability notes and current limitations

-   SQLite stores data locally, so event capture does not require an
    active internet connection.
-   `save_event()` inserts the event and its outbox row in one
    transaction, avoiding a state where only one of these two records is
    committed.
-   The unique `event_id` prevents adding the same event twice to the
    outbox. The receiver also has a primary key on `event_id`, so retries
    do not create duplicate stored records.
-   `SyncWorker` leaves events pending while WAN is offline, increments
    attempts after delivery failures, and marks them sent only after the
    receiver confirms acceptance.
-   `create_backup()` uses SQLite's online backup API, a nonblocking lock
    file, and an integrity check. A competing backup fails explicitly rather
    than overwriting another backup.

## Integrated data flow

-   Sensor/Processor code can call `save_event(...)` to persist an event
    and queue it for sending.
-   Decision code can call `save_decision(...)` after the corresponding
    event has been saved.
-   Health monitoring can call `save_process_health(...)`.
-   SyncWorker can call `get_pending_events(...)`, send records to the
    receiver, and call `mark_event_sent(...)` only after successful
    confirmation.

These interfaces are integrated with the sensor processor, supervisor,
receiver, and synchronization worker. The receiver remains a local mock
service; backups and outbox delivery are for the educational demo, not a
production disaster-recovery strategy.
