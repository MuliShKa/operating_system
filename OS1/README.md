# OS1 – Smart Building Edge Gateway (Songdo Convensia)

Node `EDGE_NODE_OS1_CONVENSIA`. This folder is a self-contained copy of the OS5
node base (supervisor, bounded IPC queue, SQLite WAL, outbox, sync worker,
mock receiver, API and dashboard), adapted to OS1.

Scope: all five OS1 scenarios (OS1-1 … OS1-5) and the deployment (systemd,
scheduled backup, container). On the Contribution Board, OS1-1/OS1-2 are assigned to
Arthur Warin and OS1-3 to OS1-5 to Estève; OS1-1 and OS1-2 were written here by Estève.

## What is different from OS5

| Part | OS1 |
|---|---|
| `inventory.py` (new) | OS1-1: reads the cached building GeoJSON through a raw file descriptor, finds the building that contains the node (ray casting), stores it in `building_inventory`; every reading is tagged with `building_id`. |
| `occupancy.py` (new) | OS1-2: 80 turnstile processes increment one shared occupancy counter, without and with a `multiprocessing.Lock`. |
| `sql/schema.sql` | Adds `building_inventory` and the handbook names as views: `sensor_events`, `durable_outbox`. |
| `config/node.yaml` | OS1 node: CO2 and temperature sensors, rule, TTL, sampling period. Read by `src/edge/node_config.py`. |
| `SensorGen` | Simulated indoor CO2 (600–1400 ppm) and room temperature (19–28 °C), one reading per second. Each reading carries its `time.monotonic()`. |
| `decision.py` | OS1-3 rule: CO2 > 1000 ppm → `HVAC_DAMPER_PCT = 100`, expiry 15.0 s **after the reading**. |
| `Actuator` (new worker) | Simulated damper. Gets commands from a second bounded queue and checks the expiry against its own monotonic clock right before acting: `DAMPER_APPLIED` or `COMMAND_EXPIRED`. |
| `ProcSampler` (new worker) | OS1-4: reads `/proc/[pid]/stat` and `/proc/[pid]/status` of every worker every 2.0 s and writes one `process_health` row per worker (JSON in `details`). |
| `receiver.py` | Its database follows `EDGE_DATABASE_PATH` (`<name>_upstream.db`), so every run is isolated. |
| `ipc.py` | WAN flag starts **online** (OS5 clears it at startup although its comment says it starts set). |

## Run the node

```bash
bash scripts/start_demo.sh          # from OS1/, dashboard on http://127.0.0.1:8000
```

## Tests

```bash
cd OS1
python -m unittest discover -s tests -v
```

## Scenarios

Each scenario starts its own node with a fresh database in `data/runs/<scenario>-<time>/`
(node.db, node_upstream.db, node.log, report.json) and stops it at the end.
Ports 8000 (API) and 8001 (receiver) must be free, or move them with
`EDGE_API_PORT` / `EDGE_RECEIVER_PORT` (example: `EDGE_RECEIVER_PORT=8011 python scenarios/os1_5_wan_outage.py`).
Official reports are kept in `document/results/`.
All five in a row: `python scenarios/run_os1_scenarios.py` (official durations, ~13 min) or `--quick` (~2 min).

## VWorld building data (OS1-1)

The node reads `sources/vworld/os1_convensia_buildings.geojson` if it exists, otherwise
the **fixture** `os1_convensia_buildings.fixture.geojson`: hand-made boxes around the node
coordinates, labelled in the file as *not* VWorld data. To use real data:

1. Get a key on https://www.vworld.kr (인증키 발급).
2. Find the building layer ID in the VWorld 2D data catalog (category 건물·시설) and set
   `inventory.vworld_layer` in `config/node.yaml`.
3. `VWORLD_API_KEY=... PYTHONPATH=src .venv/bin/python -m edge.vworld_fetch` (never commit the key).
4. Fill `retrieved_at` and `status` in `sources/source_registry.csv`.

The fetch script has not been run against the live API yet (no key).

| Scenario | Command | What it proves |
|---|---|---|
| OS1-1 | `python scenarios/os1_1_ingestion.py` | Inventory loaded from the cache, node located in its building, CO2 and temperature stored and tagged with the building, units and ranges right. |
| OS1-2 | `python scenarios/os1_2_race.py` | 80 concurrent increments: unprotected counter < 80 in every trial, mutex counter = 80 in every trial, all writers reaped. |
| OS1-3 | `python scenarios/os1_3_ventilation.py` | Boundary 999.9 / 1000 / 1000.1 ppm, 15 s TTL, live commands applied, a slowed actuator (16 s) rejects every stale command and the damper never moves. |
| OS1-4 | `python scenarios/os1_4_contention.py` | 30 s idle then 30 s with CPU burners; every worker sampled every 2.0 s; per-worker CPU, RSS, voluntary and involuntary context switches. |
| OS1-5 | `python scenarios/os1_5_wan_outage.py` | 10 min WAN cut: events and decisions continue, nothing is sent, then the backlog drains with 0 lost and 0 duplicates. |

Create the environment once with `bash scripts/setup.sh`, then use `.venv/bin/python`.

## Deployment

| What | How |
|---|---|
| systemd user service | `bash scripts/install_service.sh --start` → `systemctl --user status songdo-edge@OS1.service`, `journalctl --user-unit songdo-edge@OS1.service -f -o short-iso` |
| Scheduled backup | `songdo-backup@OS1.timer` (every 15 min), or by hand `bash scripts/backup.sh` (flock: never two at once) |
| Container | `docker compose -f container/compose.yaml up --build` → http://127.0.0.1:8000 |

Details and test evidence: `document/journal/06-deployment.md`.

## Known limits

- The supervisor stops the node when a worker dies (worker-level restart is OS5-2);
  systemd and Docker restart the whole node instead.
- OS1-1 uses the fixture until real VWorld data is fetched.
- No browser runner for all 25 scenarios yet (team-wide UI requirement); OS1 has a CLI runner.
- Table names follow the team schema (`events`, `outbox`); the handbook calls them `sensor_events` and `durable_outbox`.
