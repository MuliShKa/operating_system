
from src.edge.storage import (
    initialize_database,
    save_event,
    save_decision,
    save_process_health,
    get_pending_events,
    mark_event_sent,
    get_connection,
)

initialize_database()

event_id = "water_high_test_001"

created = save_event(
    event_id=event_id,
    event_type="WATER_LEVEL_HIGH",
    event_time="2026-10-21T12:00:00",
    payload={
        "water_level": 2.9,
        "threshold": 2.8,
        "command": "BACKUP_SLUICE_GATE_OPEN",
    },
)

print("New event created:", created)

if created:
    save_decision(
        event_id,
        "BACKUP_SLUICE_GATE_OPEN",
        "Water level exceeded 2.8 metres",
    )

    save_process_health(
        "SensorGen",
        "healthy",
        "Test health check",
    )

print("Pending events:", get_pending_events())

print("Marked sent:", mark_event_sent(event_id))
print("Pending after sending:", get_pending_events())

with get_connection() as connection:
    total = connection.execute(
        "SELECT COUNT(*) FROM events"
    ).fetchone()[0]

print("Total events in database:", total)
