# OS2 operations and deployment

## 1. Supported environment

Run OS2 on Ubuntu/Linux or WSL2. `scripts/preflight.sh` checks:

- Linux environment;
- Python 3.12 or newer;
- Unix domain socket support;
- SQLite 3.35 or newer;
- `bash` and `flock`.

Python dependencies are `PyYAML` and `psutil`, listed in `requirements.txt`.
Native Windows Python is not suitable for the complete runtime because
Unix domain sockets are required.

## 2. Install and launch locally

From an Ubuntu/WSL terminal opened in the OS2 directory:

```bash
scripts/preflight.sh
scripts/setup.sh
scripts/start_demo.sh
```

`setup.sh` creates `.venv/`, upgrades pip, installs dependencies, validates
the YAML configuration, initializes `data/os2.db`, and creates the backup
directory. It does not populate application tables with demo or seed data
beyond creating the schema.

`start_demo.sh` launches `edge.upstream_receiver` and `edge.supervisor`, sets
`PYTHONPATH=src`, and sends SIGTERM to both on shutdown. The supervisor starts
the five worker processes. Open `http://127.0.0.1:8000`; press Ctrl+C to stop.

Select a Python executable for the scripts with `OS2_PYTHON`:

```bash
OS2_PYTHON=/path/to/python scripts/start_demo.sh
```

Override the API bind address/port when needed:

```bash
OS2_API_HOST=0.0.0.0 OS2_API_PORT=8001 \
  .venv/bin/python -m edge.supervisor
```

Use only a local or appropriately secured bind address. `0.0.0.0` can expose
unauthenticated demo controls to other machines.

## 3. Unit and process tests

Run from the OS2 directory after setup:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

The suite covers model validation, the queue, sensor generation, scheduler
and safety logic, Unix sockets, restart-budget logic, the map endpoint,
outbox checkpoint queries, and a multiprocessing pipeline. Socket tests
require Linux/WSL2.

## 4. Acceptance scenarios

Start the demo, then open a second terminal in the OS2 directory:

```bash
PYTHONPATH=src .venv/bin/python scenarios/run_os2_scenarios.py
```

The scenarios are:

1. **OS2-1 — topology:** checks five live worker processes with distinct PIDs.
2. **OS2-2 — telemetry:** checks for 50 ms control-loop telemetry and a
   non-negative jitter value.
3. **OS2-3 — obstacle stop:** checks rejection of an expired command and
   confirms E-stop/zero velocity for a 0.5 m obstacle.
4. **OS2-4 — restart:** kills the controller and checks that the supervisor
   restarts it within two seconds.
5. **OS2-5 — offline conservation:** drains the outbox, disables mock WAN,
   verifies that WAN stays disabled during the requested interval, identifies
   events created during that outage, restores WAN, and checks that upstream
   received every event ID.

OS2-5 runs for ten minutes by default. For development, shorten the interval:

```bash
PYTHONPATH=src .venv/bin/python scenarios/run_os2_scenarios.py --offline-seconds 30
```

Run only against a disposable OS2 instance: OS2-4 deliberately sends SIGKILL
to the controller process. Do not manually toggle WAN during OS2-5; doing so
invalidates the run. The runner must use the same API port, database, and
socket paths as the runtime.

## 5. Dashboard API quick reference

```bash
curl http://127.0.0.1:8000/api/status
curl http://127.0.0.1:8000/api/events
curl http://127.0.0.1:8000/api/map
curl -X POST -H 'Content-Type: application/json' \
  -d '{"sensor_id":"LIDAR_PROXIMITY_M","value":0.5}' \
  http://127.0.0.1:8000/api/sensor
curl -X POST -H 'Content-Type: application/json' \
  -d '{"online":false}' http://127.0.0.1:8000/api/network
```

Restore mock WAN by sending `{"online":true}`. The API validates sensor IDs
and value ranges. These are simulation controls only.

## 6. Docker Compose

From the OS2 directory:

```bash
docker compose -f container/compose.yaml config
docker compose -f container/compose.yaml up --build
```

Compose starts:

- `robot` — supervisor, API, and application workers;
- `upstream` — mock receiver.

Both services share a volume for Unix sockets and a volume for SQLite data.
Containers run as non-root with a read-only root filesystem, writable data
volumes, and CPU/memory/PID limits. The host port is bound to loopback. Stop
with Ctrl+C. `docker compose down -v` deletes named volumes and persisted demo
databases, so use it only when that data is no longer needed.

## 7. systemd user services

The provided unit files assume the checkout is located at
`$HOME/operating_system/OS2`. If it is elsewhere, update `WorkingDirectory`,
`ExecStart`, and `ReadWritePaths`. Create the virtual environment before
enabling the units.

```bash
mkdir -p ~/.config/systemd/user
cp systemd/songdo-edge@.service systemd/songdo-edge-upstream@.service \
  systemd/songdo-edge-backup.service systemd/songdo-edge-backup.timer \
  ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now songdo-edge@OS2.service \
  songdo-edge-upstream@OS2.service songdo-edge-backup.timer
```

Inspect status and logs:

```bash
systemctl --user status songdo-edge@OS2.service
systemctl --user status songdo-edge-upstream@OS2.service
systemctl --user list-timers songdo-edge-backup.timer
journalctl --user -u songdo-edge@OS2.service -f
```

The timer runs backups hourly and is persistent. Use
`systemctl --user disable --now` for the relevant units to stop them.

## 8. SQLite backups

Create and verify an online backup:

```bash
scripts/backup.sh
```

The script obtains a non-blocking `flock` on `data/backup.lock`, then invokes
`edge.maintenance`. SQLite's online backup API writes a timestamped file
under `data/backups/` and runs `PRAGMA integrity_check`. Choose a custom path:

```bash
PYTHONPATH=src .venv/bin/python -m edge.maintenance \
  --destination /path/to/os2-backup.db
```

Database files, WAL sidecars, locks, virtual environments, and backups are
ignored by Git. Store backups outside the checkout if they must survive loss
of the workspace or disk.

## 9. Troubleshooting

### Preflight fails on Windows

Run it from Ubuntu/WSL2, not PowerShell or native Windows Python. The runtime
requires Unix sockets.

### The dashboard cannot reach safety monitor or upstream

Check `/api/status`, worker logs, and permissions on the socket directory.
The normal launcher starts the receiver and supervisor together. Do not
remove a socket file while its server is running.

### Port 8000 is already in use

Stop the other OS2 runtime or select an unused `OS2_API_PORT`. Do not expose
the unauthenticated dashboard publicly.

### The outbox remains pending

This is expected while mock WAN is offline. Check that the mock receiver is
running and WAN is online. The sync worker retries automatically after
recovery; local rows are marked sent only after acknowledgement.

### A worker repeatedly restarts

Inspect supervisor logs and `process_health` in the local database. If a
worker exceeds the configured budget (five restarts in ten seconds by
default), the supervisor stops rather than restarting indefinitely.

### Backup reports a lock or integrity error

Only one backup runs at a time by design. Retry after the active backup
finishes. Treat an integrity-check failure as a database issue and preserve
the database and backup for investigation.
