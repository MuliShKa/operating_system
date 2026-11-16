# Songdo Edge Intelligence

A multi-process demonstration of an edge computing node that collects simulated sensor readings, processes them locally, stores events in SQLite, and displays live status through a browser dashboard.

The project also demonstrates **store-and-forward synchronization**: when the simulated WAN connection is offline, events remain in a local SQLite outbox. When connectivity is restored, a synchronization worker attempts to deliver pending events to a local mock receiver.

> **Educational demo only:** Sensor readings are simulated. Decisions are recorded, but no physical equipment is controlled. The receiver is a local mock service, not a real cloud endpoint.

## Features

- Generates simulated water-level and voltage readings.
- Uses Python multiprocessing to run independent workers.
- Passes sensor events through a bounded inter-process communication (IPC) queue.
- Applies a local water-level rule and records decisions.
- Stores events, delivery status, and health information in SQLite.
- Provides an HTTP API and browser dashboard for monitoring activity.
- Simulates WAN disconnection and reconnection.
- Queues events locally while offline and synchronizes them when connectivity returns.
- Uses event IDs to keep the mock receiver idempotent.

## Architecture

The supervisor starts six worker processes:

| Process | Responsibility |
|---|---|
| `SensorGen` | Generates simulated sensor readings. |
| `Processor` | Processes readings, stores events, and evaluates the local rule. |
| `HealthMon` | Monitors worker health and records health information. |
| `API` | Serves the dashboard and status/control endpoints. |
| `Receiver` | Runs a local HTTP service that accepts delivered events. |
| `SyncWorker` | Sends pending outbox events to the receiver when WAN connectivity is enabled. |

### Data flow

```text
SensorGen
    |
    v
Bounded IPC queue
    |
    v
Processor -------> SQLite events and outbox
    |                         |
    v                         v
Local decision             SyncWorker
    |                         |
    v                         v
SQLite decisions       Mock Receiver
                             
HealthMon ----------> SQLite health records

API ----------------> Dashboard and status endpoints
```

The queue has a maximum capacity of 500 items. The processor stores readings and records decisions. When the simulated WAN connection is offline, the sync worker waits and pending events accumulate in the outbox. When connectivity is restored, it attempts to deliver those events to the receiver.

The local rule reads its water-level threshold from `config/node.yaml` (currently 2.8 metres). It rejects malformed, non-finite, or negative water readings; no physical upper sensor limit is specified. It records a `BACKUP_SLUICE_GATE_OPEN` decision only when a valid reading exceeds the threshold and its 10-second monotonic TTL has not expired. This is a software decision only; it does not operate a real gate.

## Requirements

- Linux or Ubuntu (the project was developed and tested in Ubuntu).
- Python 3.12 or 3.14.
- Dependencies from `requirements.txt` (`psutil` and `PyYAML`).

The startup scripts require Linux/WSL and Python 3.12 or 3.14. Setup creates
the virtual environment, installs `requirements.txt`, initializes the SQLite
schema, and verifies WAL mode.

## Run the demo

Run these commands from the repository root.

### 1. Start the application

```bash
PYTHONPATH=src python3 -m edge.supervisor
```

The supervisor starts the worker processes. Keep the terminal open while using the demo.

To use a temporary database for the application's event storage instead of the default `data/songdo.db`, run:

```bash
EDGE_DATABASE_PATH=/tmp/songdo_demo.db PYTHONPATH=src python3 -m edge.supervisor
```

The mock receiver uses its own database at `data/upstream_receiver.db`.

To create and integrity-check a SQLite backup under an exclusive `flock`:

```bash
PYTHONPATH=src python3 -m edge.backup
```

### 2. Open the dashboard

Open the following address in a browser on the same computer:

`http://127.0.0.1:8000`

The dashboard displays worker status, sensor readings, recent decisions, and pending outbox events.

### 3. Demonstrate WAN synchronization

1. Start the application and open the dashboard.
2. Select **Simulate WAN Internet Cut**.
3. Allow the sensor generator to produce readings. Observe the pending outbox count increase.
4. Select **Restore WAN Connection**.
5. Observe the sync worker deliver pending events to the mock receiver and the pending count decrease.
6. Explain that new readings continue to arrive, so the pending count may not remain at zero.

The WAN state is simulated within the application. This demonstration does not disconnect the computer from the actual internet.

### 4. Stop the application

Return to the terminal running the supervisor and press `Ctrl+C`. The supervisor coordinates worker shutdown.

## API endpoints

The API listens locally on port `8000`.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/status` | Returns application and worker status, recent readings and decisions, and pending-event information. |
| `GET` | `/health/live` | Confirms that the local API process is responding. |
| `GET` | `/health/ready` | Returns readiness only when SQLite is available and all required worker heartbeats are fresh. Returns HTTP 503 while starting or unhealthy. |
| `POST` | `/api/wan/offline` | Simulates a WAN outage. |
| `POST` | `/api/wan/online` | Restores simulated WAN connectivity. |

The mock receiver listens on port `8001` and accepts event submissions at `/api/events`.

## Project structure

```text
src/edge/
    SensorGen.py       Simulated sensor generator
    api_server.py     HTTP API and dashboard serving
    backup.py         Flock-guarded online SQLite backup
    bounded_queue.py  Bounded IPC queue
    decision.py       Local decision rules
    ipc.py            Shared multiprocessing channels and events
    models.py         Event and data models
    processor.py      Sensor event processing
    receiver.py       Mock upstream receiver
    shared_counter.py Shared counter support
    storage.py        SQLite storage and outbox operations
    supervisor.py     Worker process lifecycle
    sync_worker.py    Outbox delivery worker

src/ui/static/
    index.html        Browser dashboard

sql/
    schema.sql        Database schema

scripts/
    preflight.sh      Linux, Python, SQLite, and command checks
    setup.sh          Virtual environment and database initialization
    start_demo.sh     Preflight, setup, and supervisor launcher

tests/
    test_*.py         OS5 unit and integration checks

scenarios/
    run_all_scenarios.py  Run the complete OS5 test suite
```

Additional project documentation is available in `document/README.md` and the other files under `document/`.

## Validate OS5

Run all unit and integration scenarios from the OS5 directory:

```bash
python3 scenarios/run_all_scenarios.py
```

## Limitations

- Sensor readings are simulated rather than collected from physical devices.
- Decisions are recorded but do not control real equipment.
- The upstream receiver is a local mock service.
- This is an educational demonstration, not a production-ready system.
