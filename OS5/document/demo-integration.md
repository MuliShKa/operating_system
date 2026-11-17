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
requires Linux, Bash, Python 3.12 or 3.14, and the system utilities listed in the
preflight script. If the `.venv` virtual environment does not exist, the
launcher calls `scripts/setup.sh`. Setup installs the project dependencies and
creates `data/songdo.db` from the schema in `sql/schema.sql`.

The launcher then starts `edge.supervisor` using Python's multiprocessing
`spawn` method. The supervisor creates shared IPC channels and starts six
processes:

| Process | What it does |
|---|---|
| `SensorGen` | Generates random water-level and voltage readings once per second and puts them in the queue. |
| `Processor` | Reads the queue, stores each reading, evaluates the water-level rule, and stores any resulting decision. |
| `HealthMon` | Writes process health heartbeats to SQLite. |
| `API` | Serves the demo page and JSON status for workers and recent data. |
| `Receiver` | Accepts events at a local mock upstream endpoint and deduplicates by event ID. |
| `SyncWorker` | Sends pending outbox events when the simulated WAN is online. |

The processes share one `IpcChannels` object. It contains a bounded queue for
sensor readings, a shared stop flag, and a WAN-online event that starts set.
Worker restarts reuse these same IPC channels. The IPC objects use the same
`spawn` context as the supervisor.

## How a reading becomes a decision

1. `SensorGen` creates `SensorEvent` objects for `SLUICE_WATER_LEVEL_M` and
   `MAINS_VOLT`. The values are simulated: water level is randomly generated
   between approximately 2.0 and 3.5 metres, and voltage between 210 and 230
   volts.
2. The events go into the bounded queue. Its maximum size is 500 items; if it
   fills up, the queue drops the oldest reading.
3. For a water-level reading, `Processor` rejects values that are not finite
   numbers or are below zero. Rejected readings are logged and do not produce
   an event or gate decision.
4. `Processor` stores each accepted event in the `events` table with a unique
   ID and creates a corresponding `outbox` row atomically.
5. `Processor` reads the threshold from `config/node.yaml` (currently 2.8 m).
   When a valid value is **above the configured threshold**, the rule creates a
   `BACKUP_SLUICE_GATE_OPEN` decision. The decision is stored in the `decisions`
   table.
6. The decision gets a 10-second TTL based on a monotonic clock. The processor
   rejects an expired command before storing it. There is not yet a separate
   command queue or hardware actuator.
7. The most recent readings, decisions, and pending outbox count are published
   to shared state for the API.

Voltage readings are stored and displayed, but there is no rule for voltage
yet. The `SyncWorker` sends pending events to the local mock receiver while
WAN is online. During a simulated outage, they remain pending in SQLite and
are sent after connectivity is restored.

## WAN outage and worker recovery

The dashboard's WAN controls clear or set the shared `wan_online` event; they
do not disconnect the computer from the internet. If a worker exits
unexpectedly, the supervisor restarts only that worker and gives it the
existing IPC channels. The compound-failure test holds the WAN offline,
restarts `Processor`, verifies that the outbox remains pending, then restores
WAN and checks that every event reaches the deduplicating receiver once.

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
- the number of events waiting in the outbox;
- WAN state and controls for simulating an outage and restoring connectivity.

The HTTP server listens only on `127.0.0.1`. This demo page is intended for the
local computer, not for access from the network.

## How I stop the demo

I press `Ctrl+C` in the terminal. The supervisor also handles `SIGTERM`. Either
signal sets the shared stop flag. SensorGen stops creating new readings,
Processor drains the readings already in the queue, and HealthMon and API exit
their loops. The supervisor waits for the child processes to finish. If a
process does not stop within the timeout, the supervisor terminates and reaps
it.

## Validation status

The full OS5 runner completed with **43 tests passing** on WSL Debian with
Python 3.13.5. The repository preflight supports Python 3.12 or 3.14, neither
of which is installed in that environment, so repeat the runner on a supported
version before treating that runtime matrix as verified.

The compound-failure test is in `tests/test_compound_failure.py`; run the suite
from the project root with `python3 scenarios/run_all_scenarios.py`.

## What is not included yet

- Real sensor input and control of physical equipment.
- Protected public web access; the API is currently local-only.

The receiver is a local mock service, not a remote cloud endpoint. For these
reasons, I describe this as an educational local demo, not a production-ready
control system.

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
- `src/edge/backup.py` — locked, integrity-checked online database backup.
- `src/edge/receiver.py` and `src/edge/sync_worker.py` — local outbox delivery.
- `src/edge/api_server.py` and `src/ui/static/index.html` — local API and
  dashboard page.
- `tests/test_demo_integration.py` — test for the path from the queue through
  the rule into SQLite and dashboard state.
- `tests/test_compound_failure.py` — WAN outage plus Processor restart scenario.
- `scenarios/run_all_scenarios.py` — discover and run the complete OS5 test suite.
