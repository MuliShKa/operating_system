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
   in one transaction, and applies the local rule.
4. **Rule:** `PED_CROSSWALK_COUNT >= 15` -> `VARIABLE_SPEED_SIGN_KMH = 30`
   with a 15 s monotonic TTL. When no new surge reading refreshes the command,
   the sign returns to 50 km/h.
5. The sign state lives in the `sign_state` table and changes only through a
   **version-guarded** `UPDATE ... WHERE version = ?` (OS3-4).
6. `SyncWorker` sends pending outbox rows to the mock `Receiver` only while the
   simulated WAN is online. The receiver deduplicates by `event_id` (OS3-5).

Thresholds and the TTL are **team decisions** (the handbook does not define
them). Change them in `config/node.yaml`.

## Processes

| Process | Role |
|---|---|
| `SensorGen` | Simulated radar and crosswalk sensors |
| `Processor` | Queue consumer, local rule, sign state, SQLite writes |
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
python3 tests/test_surge_rule.py -v               # rule, TTL, version-guarded sign
PYTHONPATH=src python3 tests/test_demo_integration.py -v
```

## Scenario status

| Scenario | Status |
|---|---|
| OS3-1 Bus stop context | **Not started** - needs cached Incheon BIS data (dataset `15048265`) and a loader |
| OS3-2 Priority queue | Implemented and tested |
| OS3-3 Overload / drop-oldest | Implemented and tested |
| OS3-4 Transactional sign state | Implemented and tested |
| OS3-5 Offline sign dispatch and replay | Mechanism works; the 10-minute conservation test is still to be written |

## Not implemented yet

- Bus stop data loader and correlation with pedestrian counts (OS3-1).
- Automatic restart of a crashed worker (the supervisor stops everything instead).
- `scenarios/run_all_scenarios.py`, systemd unit, Dockerfile and compose file.
- Backup script with `flock`, and the 10-minute offline demonstration script.
