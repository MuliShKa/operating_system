# How I Integrated the Local Demo

## Why I made this change

I connected the project's existing components into one local demonstration
pipeline. The application no longer only starts placeholder processes: it
generates sensor readings, passes them between processes, stores them in
SQLite, evaluates a water-level rule, and displays live data in a browser.

One important boundary: this is an educational simulation running on one
computer. The sensors generate random values, and the gate-opening command is
only recorded as a decision. The demo does not control a real gate or other
physical equipment.

## What happens when I start it

I run the project on Linux or in WSL from the repository root:

```bash
bash scripts/start_demo.sh
```

The script first checks the environment with `scripts/preflight.sh`. It
requires Linux, Bash, Python 3.12, and the system utilities listed in the
preflight script. If the `.venv` virtual environment does not exist, the
launcher calls `scripts/setup.sh`. Setup installs the project dependencies and
creates `data/songdo.db` from the schema in `sql/schema.sql`.

The launcher then starts `edge.supervisor` using Python's multiprocessing
`spawn` method. The supervisor creates shared IPC channels and starts four
processes:

| Process | What it does |
|---|---|
| `SensorGen` | Generates random water-level and voltage readings once per second and puts them in the queue. |
| `Processor` | Reads the queue, stores each reading, evaluates the water-level rule, and stores any resulting decision. |
| `HealthMon` | Writes process health heartbeats to SQLite. |
| `API` | Serves the demo page and JSON status for workers and recent data. |

The processes share one `IpcChannels` object. It contains a bounded queue for
sensor readings and a shared stop flag. The IPC objects use the same `spawn`
context as the supervisor.

## How a reading becomes a decision

1. `SensorGen` creates `SensorEvent` objects for `SLUICE_WATER_LEVEL_M` and
   `MAINS_VOLT`. The values are simulated: water level is randomly generated
   between approximately 2.0 and 3.5 metres, and voltage between 210 and 230
   volts.
2. The events go into the bounded queue. Its maximum size is 500 items; if it
   fills up, the queue drops the oldest reading.
3. `Processor` reads each event and stores it in the `events` table. Each event
   gets a unique ID, and a corresponding `outbox` row is created atomically
   with the event.
4. For a water-level reading, `Processor` calls the rule in `edge.decision`.
   When the value is **above 2.8 metres**, the rule creates a
   `BACKUP_SLUICE_GATE_OPEN` decision. The decision is stored in the `decisions`
   table.
5. The decision gets a 10-second TTL based on a monotonic clock. The current
   pipeline checks it immediately after creating it and stores the decision;
   there is not yet a separate command queue or hardware actuator.
6. The most recent readings, decisions, and pending outbox count are published
   to shared state for the API.

Voltage readings are stored and displayed, but there is no rule for voltage
yet. All events in the `outbox` remain `pending`: sending them to a remote
service and running a synchronizer are not implemented yet.

## What I see in the browser

After the startup message appears, I open:

```text
http://127.0.0.1:8000
```

The page in `src/ui/static/index.html` requests `GET /api/status` once per
second. It displays:

- worker status and process IDs (PIDs);
- recent sensor readings;
- recent decisions;
- the number of events waiting in the outbox.

The HTTP server listens only on `127.0.0.1`. This demo page is intended for the
local computer, not for access from the network.

## How I stop the demo

I press `Ctrl+C` in the terminal. The supervisor also handles `SIGTERM`. Either
signal sets the shared stop flag. SensorGen stops creating new readings,
Processor drains the readings already in the queue, and HealthMon and API exit
their loops. The supervisor waits for the child processes to finish. If a
process does not stop within the timeout, the supervisor terminates and reaps
it.

## Checks I ran

From the project root in Linux/WSL:

```bash
python3 tests/test_os_fundamentals.py -v
PYTHONPATH=src python3 tests/test_demo_integration.py -v
python3 test_schema.py
python3 test_storage.py
```

I also started the full supervisor, checked the page and `GET /api/status`,
confirmed all four processes were running, confirmed readings and decisions
appeared, and checked that events, decisions, and health heartbeats were stored
in SQLite.

## What is not included yet

- Automatic restart of a crashed worker.
- Real sensor input and control of physical equipment.
- Sending pending outbox events to a server, including retry and backoff.
- Browser controls for WAN status or a simulated network outage.
- Protected public web access; the API is currently local-only.

For these reasons, I describe this as a minimal end-to-end local demo of the
components, not a production-ready system.

## Where the code lives

- `scripts/start_demo.sh` — environment check and application launcher.
- `scripts/setup.sh` — virtual environment and SQLite database setup.
- `src/edge/supervisor.py` — process startup and graceful shutdown.
- `src/edge/ipc.py` and `src/edge/bounded_queue.py` — inter-process queue and
  shared flags.
- `src/edge/SensorGen.py` — sensor reading generation.
- `src/edge/processor.py` — connects the queue, rules, and storage.
- `src/edge/decision.py` — water-level rule and command TTL.
- `src/edge/storage.py` and `sql/schema.sql` — SQLite functions and tables for
  events, decisions, process health, and the outbox.
- `src/edge/api_server.py` and `src/ui/static/index.html` — local API and
  dashboard page.
- `tests/test_demo_integration.py` — test for the path from the queue through
  the rule into SQLite and dashboard state.
