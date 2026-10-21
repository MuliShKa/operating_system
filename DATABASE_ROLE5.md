# Role 5 --- Database: Implementation Notes

## Purpose

This part of the Songdo Smart Sluice Gate project provides local SQLite
storage. The system should continue recording events when the internet
is unavailable, then allow the SyncWorker to find events waiting to be
sent.

## Files created or implemented

-   `sql/schema.sql` --- defines the database tables and indexes.
-   `src/edge/storage.py` --- Python functions for initializing the
    database and storing/retrieving records.
-   `test_schema.py` --- checks that the schema can be executed and the
    four application tables are created.
-   `test_storage.py` --- exercises the storage functions with a sample
    high-water-level event.

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

## How to test

From the project root, run:

``` powershell
python test_schema.py
python test_storage.py
```

The schema test should list these four tables: `decisions`, `events`,
`outbox`, and `process_health`.

The storage test uses a sample event with a water level of 2.9 m and a
threshold of 2.8 m. On the first run, `New event created` should be
`True`; on a repeat run with the same event ID, it should be `False`.
Once the test marks the event as sent, the pending queue should be
empty. The event itself remains in the database.

## Reliability notes and current limitations

-   SQLite stores data locally, so event capture does not require an
    active internet connection.
-   `save_event()` inserts the event and its outbox row in one
    transaction, avoiding a state where only one of these two records is
    committed.
-   The unique `event_id` prevents adding the same event twice to the
    outbox. End-to-end duplicate protection also requires the
    receiver/API to support idempotency.
-   WAL mode and the connection timeout help with local database access,
    but they do not by themselves prove crash recovery or loss-free
    delivery. These still need integration tests with `SyncWorker` and
    the receiver.
-   The current `attempts` field is present in the schema, but
    retry-attempt increments and retry/backoff behavior must be
    implemented and tested as part of the sync workflow.
-   The team should confirm the event model, field names, timestamps,
    and function signatures against `models.py`, `sync_worker.py`, and
    the API before merging.

## Suggested integration contract for the team

-   Sensor/Processor code can call `save_event(...)` to persist an event
    and queue it for sending.
-   Decision code can call `save_decision(...)` after the corresponding
    event has been saved.
-   Health monitoring can call `save_process_health(...)`.
-   SyncWorker can call `get_pending_events(...)`, send records to the
    receiver, and call `mark_event_sent(...)` only after successful
    confirmation.

These interfaces are the current database implementation proposal and
may need small adjustments when the other roles are integrated.
