# OS1 – Smart Building Edge Gateway (Songdo Convensia)

Node `EDGE_NODE_OS1_CONVENSIA`. This folder is a self-contained copy of the OS5
node base (supervisor, bounded IPC queue, SQLite WAL, outbox, sync worker,
mock receiver, API and dashboard), adapted to OS1.

Scope of this folder today: **OS1-3, OS1-4, OS1-5** (Estève).
OS1-1 (VWorld inventory) and OS1-2 (race condition) belong to Arthur and are not here yet.

## What is different from OS5

| Part | OS1 |
|---|---|
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

| Scenario | Command | What it proves |
|---|---|---|
| OS1-3 | `python scenarios/os1_3_ventilation.py` | Boundary 999.9 / 1000 / 1000.1 ppm, 15 s TTL, live commands applied, a slowed actuator (16 s) rejects every stale command and the damper never moves. |
| OS1-4 | `python scenarios/os1_4_contention.py` | 30 s idle then 30 s with CPU burners; every worker sampled every 2.0 s; per-worker CPU, RSS, voluntary and involuntary context switches. |
| OS1-5 | `python scenarios/os1_5_wan_outage.py` | 10 min WAN cut: events and decisions continue, nothing is sent, then the backlog drains with 0 lost and 0 duplicates. |

Create the environment once with `bash scripts/setup.sh`, then use `.venv/bin/python`.

## Known limits

- The supervisor still stops the node when a worker dies (OS5-2 work, shared base).
- `container/`, `systemd/` and a runner for all scenarios are not done for OS1.
- Table names follow the team schema (`events`, `outbox`); the handbook calls them `sensor_events` and `durable_outbox`.
