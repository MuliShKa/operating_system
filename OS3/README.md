# OS3 - Autonomous Mobility Edge Node (Songdo Edge Intelligence)

Inha University - Operating System (운영체제) - Techno-Park Intersection
Node ID: `EDGE_NODE_OS3_MOBILITY` (lat 37.3820, lon 126.6560)

> **Educational demo only.** Radar speeds and pedestrian counts are simulated.
> The speed-sign command is stored as a decision and shown on the dashboard;
> no physical sign is controlled. The upstream receiver is a local mock.

**Mission:** "Make Songdo compute locally and reliably."
**Signature demo:** "Disconnect Internet -> system continues operating."

## What the node does

1. `SensorGen` simulates `RADAR_SPEED` (km/h) and `PED_CROSSWALK_COUNT` (people),
   with a pedestrian surge every 30 s.
2. Readings travel through a **priority-aware bounded queue** (500 items per lane,
   drop-oldest). Surge alarms use the urgent lane (OS3-2, OS3-3).
3. `Processor` stores every event in SQLite (WAL) together with an outbox row,
   in one transaction, and applies the local rule. It only **issues** commands.
4. **Rule:** `PED_CROSSWALK_COUNT >= 15` -> `VARIABLE_SPEED_SIGN_KMH = 30`.
   The command expires 15 s **after the sensor reading** (monotonic clock), not
   after the decision, so time spent waiting in a queue counts.
5. The `Actuator` worker is the only one that moves the sign. Right before acting
   it compares the command's expiry with its own monotonic clock and **rejects
   stale commands** (`SIGN_COMMAND_EXPIRED`). When no new surge command
   refreshes the deadline, it restores 50 km/h.
6. The sign state lives in the `sign_state` table and changes only through a
   **version-guarded** `UPDATE ... WHERE version = ?` (OS3-4).
7. `SyncWorker` sends pending outbox rows to the mock `Receiver` only while the
   simulated WAN is online. The receiver deduplicates by `event_id` (OS3-5).

Thresholds and the TTL are **team decisions** (the handbook does not define
them). Change them in `config/node.yaml`.

## Processes

| Process | Role |
|---|---|
| `SensorGen` | Simulated radar and crosswalk sensors |
| `Processor` | Queue consumer, local rule, SQLite writes, issues sign commands |
| `Actuator` | Checks command freshness (monotonic clock), moves the sign, restores it on TTL expiry. `EDGE_ACTUATOR_DELAY_S=16` slows it down to demonstrate rejection |
| `HealthMon` | Heartbeat into `process_health` |
| `API` | Local dashboard and JSON status on `127.0.0.1:8000` |
| `Receiver` | Mock upstream endpoint on `127.0.0.1:8001` |
| `SyncWorker` | Outbox delivery with retry |

## Run (Linux / WSL2, Python 3.12+)

```bash
bash scripts/start_demo.sh      # preflight + setup on first run + supervisor
```

Open `http://127.0.0.1:8000`. Use **Simulate WAN Internet Cut** and
**Restore WAN Connection** to see the outbox accumulate and drain. Stop with `Ctrl+C`.

Manual launch:

```bash
PYTHONPATH=src python3 -m edge.supervisor
```

## Tests

```bash
python3 tests/test_os_fundamentals.py -v          # queues, IPC, race, deadlock
python3 tests/test_surge_rule.py -v               # rule, TTL from reading time, version-guarded sign
PYTHONPATH=src python3 tests/test_actuator.py -v  # freshness check, rejection, restore
PYTHONPATH=src python3 tests/test_demo_integration.py -v
```

## Scenario status

| Scenario | Status |
|---|---|
| OS3-1 Bus stop context | Implemented and tested. Uses a **synthetic sample CSV** until the real cached BIS file is placed in `sources/incheon_bis_stops.csv` (column names of the real file not verified) |
| OS3-2 Priority queue | Implemented and tested |
| OS3-3 Overload / drop-oldest | Implemented and tested |
| OS3-4 Transactional sign state | Implemented and tested |
| OS3-5 Offline sign dispatch and replay | Implemented: `scenarios/os3_5_offline_demo.py` |

## Offline demonstration (OS3-5)

```bash
python3 scenarios/os3_5_offline_demo.py                        # full 10-minute demo
python3 scenarios/os3_5_offline_demo.py --offline-seconds 60   # quick check
```

It starts the node with throwaway databases, cuts the simulated WAN, and checks
that all workers keep running, events keep being stored, sign decisions
continue, and nothing is delivered. It then restores the WAN, waits for the
backlog to drain, replays one event to prove the receiver deduplicates, and
verifies conservation: no event lost, nothing marked `sent` that the receiver
does not have. Exit code 0 means every check passed. Use `| tee report.txt`
to keep the report as evidence. Stop any running node first (port 8000).

## Not implemented yet

- Automatic restart of a crashed worker (the supervisor stops everything instead).
- `scenarios/run_all_scenarios.py`, systemd unit, Dockerfile and compose file.
- Backup script with `flock`.
