# Songdo Edge Intelligence

A local, multi-process demonstration of an edge node: simulated sensors send
readings through IPC, a processor applies a local water-level rule, SQLite
stores events and decisions, and a browser dashboard shows live status.

> This is an educational demo, not a production system. Sensor values are
> simulated, no physical equipment is controlled, and pending outbox events are
> not synchronized to a remote service.

## What the demo does

- Starts four Linux processes: `SensorGen`, `Processor`, `HealthMon`, and `API`.
- Sends simulated water-level and voltage events through a bounded
  multiprocessing queue.
- Persists events, rule-based decisions, and health heartbeats in SQLite.
- Creates a `BACKUP_SLUICE_GATE_OPEN` decision when the simulated water level
  exceeds 2.8 metres. The decision is recorded; it does not operate a real gate.
- Serves a local dashboard with worker PIDs, recent readings and decisions, and
  the number of pending outbox events.
- Stops workers cleanly when you press Ctrl+C.

## Requirements

The supported environment is **Ubuntu 24.04 with Python 3.12 or Ubuntu 26.04
with Python 3.14**. The startup checks also require Bash and these command-line
tools: `sqlite3`, `ps`, `pkill`, `awk`, `sed`, `flock`, and `curl`.

Windows users should run the project in WSL, not directly from PowerShell.
Ubuntu 24.04 in WSL includes Python 3.12. Running the shell scripts from a
Windows terminal without Linux/WSL will fail the preflight check.

## Quick start on Ubuntu or WSL

### 1. Install system prerequisites

On Windows, install and open Ubuntu 24.04 in WSL if it is not already available:

```powershell
wsl --install -d Ubuntu-24.04
```

Run the following commands **inside the Ubuntu terminal**:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip \
  sqlite3 procps gawk sed util-linux curl
```

### 2. Clone the demo branch

The `demo` branch contains the integrated application:

```bash
cd ~
git clone --branch demo https://github.com/MuliShKa/operating_system.git
cd operating_system
```

If you already have a checkout of this repository, enter its directory and
switch to the branch instead:

```bash
git switch demo
```

### 3. Start the application

```bash
bash scripts/start_demo.sh
```

On the first run, the launcher checks the system, creates `.venv`, installs the
Python packages from `requirements.txt`, initializes `data/songdo.db`, and
starts the four worker processes. Keep this terminal open while using the demo.

### 4. Open the dashboard

Open this address in a browser on the same computer:

```text
http://127.0.0.1:8000
```

The dashboard refreshes automatically and shows worker status/PIDs, recent
sensor values, decisions, and the pending outbox count. The API listens only on
`127.0.0.1`; it is not exposed to other computers on the network.

### 5. Stop the application

Return to the terminal running the app and press **Ctrl+C**. The supervisor
signals the workers, waits for them to exit, and reaps them. The SQLite database
remains in `data/songdo.db` across runs.

## How the data flows

```text
SensorGen
   │ SensorEvent objects
   ▼
Bounded IPC queue (maximum 500 readings)
   │
   ▼
Processor ──► SQLite events + outbox
   │
   ├── water level > 2.8 m ──► local decision ──► SQLite decisions
   │
   └── recent readings and decisions ──► shared status
                                             │
HealthMon ──► SQLite process_health         ▼
                                      API ──► Dashboard
```

The sensor generator produces new random water-level and voltage readings
approximately once per second. The queue drops its oldest item if it reaches
capacity. Every processed reading is stored locally; events awaiting upstream
delivery remain in the outbox with `pending` status.

## Run checks

Run these commands from the repository root in Ubuntu/WSL:

```bash
# Concurrency, IPC, queue, and operating-system tests
.venv/bin/python tests/test_os_fundamentals.py -v

# Sensor queue -> decision -> SQLite integration
PYTHONPATH=src .venv/bin/python tests/test_demo_integration.py -v

# Database schema and storage checks
.venv/bin/python test_schema.py
.venv/bin/python test_storage.py
```

`test_storage.py` inserts a sample event into the local database and marks it
sent. Use a disposable checkout/database if you do not want test data in your
demo database.

## Troubleshooting

### Preflight says Python 3.12 or 3.14 or a utility is missing

Run the prerequisite installation commands above in Ubuntu/WSL. Check the
interpreter version with:

```bash
python3 --version
```

The script accepts Python 3.12 or 3.14. Other Python versions, including
Python 3.13, do not pass preflight.

### Port 8000 is already in use

Stop the other local service using port 8000, then rerun
`bash scripts/start_demo.sh`. The demo API currently uses a fixed local port.

### The browser reports that it cannot connect

Check that the supervisor is still running and that startup printed
`http://127.0.0.1:8000`. Open the address in a browser on the same Windows
machine where WSL is running. Do not close the terminal until you finish.

### The virtual environment is missing or broken

From the repository root, run:

```bash
bash scripts/setup.sh
```

Then retry `bash scripts/start_demo.sh`.

## Current limitations

- Sensor input is random simulation, not a physical device.
- Decisions are recorded but no actuator executes them.
- Automatic restart after a worker crash is not implemented.
- Outbox synchronization, remote delivery, and retry/backoff are not
  implemented; pending items stay in SQLite.
- The dashboard does not yet offer WAN-disconnect controls.
- This demo has not been hardened for public or production use.

## Documentation

See [document/README.md](document/README.md) for the organized guides, including
the [demo integration walkthrough](document/demo-integration.md), database
notes, IPC and concurrency guide, startup guide, process lifecycle notes, and
the original course project brief.

## Repository layout

```text
config/                  Node configuration
data/                    Local SQLite database and backups
document/                Project documentation and handbook
scenarios/               Scenario definitions and runner
scripts/                 Linux preflight, setup, and demo launcher
sql/                     SQLite schema
src/edge/                Sensor, processor, IPC, storage, supervisor, and API
src/ui/static/           Local dashboard
tests/                   Automated tests
```
