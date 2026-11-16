# OS3 technical report - Autonomous Mobility Edge Node

Node `EDGE_NODE_OS3_MOBILITY`, Techno-Park intersection (37.3820 N, 126.6560 E).
Mission: "Make Songdo compute locally and reliably." Signature demo:
"Disconnect Internet -> system continues operating."

All sensor data is simulated. The speed-sign command is stored and shown on the
dashboard; no physical sign is controlled. The upstream receiver is a local mock.

## 1. Process architecture

One **supervisor** starts seven worker processes with the `spawn` start method
(a clean interpreter per worker, no inherited locks or threads) and one shared
`Manager` dictionary for status.

| Process | Role | Talks to |
|---|---|---|
| SensorGen | Simulated radar speed and crosswalk pedestrian count; a surge every 30 s | `sensor_events` queue |
| Processor | Consumes events; one SQLite transaction writes event + outbox row; applies the surge rule; issues `ActuatorCommand` | `sensor_events` in, `commands` out, SQLite |
| Actuator | Only process that moves the sign; checks freshness; restores 50 km/h | `commands` in, `sign_state` |
| HealthMon | Heartbeat rows in `process_health` | SQLite |
| API | Dashboard and `/api/status`, WAN simulation switch | shared state |
| Receiver | Mock cloud endpoint, idempotent by `event_id` | HTTP |
| SyncWorker | Sends outbox rows while the WAN flag is up, with retry | HTTP, SQLite |

IPC mechanisms used: bounded queues between processes, a shared `Event` for stop
and for the WAN flag, a `Manager` dict for dashboard state, SQLite (WAL) as the
durable shared store, HTTP between the node and the mock cloud, and a Unix
domain socket demo.

## 2. Scenario to mechanism map

| Scenario | Mechanism | Where | Evidence |
|---|---|---|---|
| OS3-1 bus context | Cached BIS CSV loaded from disk, haversine distance, nearest stop named in the decision reason | `bis_loader.py`, `processor.py` | `scenarios/os3_1_bus_context.py` |
| OS3-2 priority | `PriorityQueue`: urgent lane drained before normal lane | `priority_queue.py` | `scenarios/os3_2_priority.py` |
| OS3-3 overload | `BoundedQueue`: capacity 500, drop-oldest, counters | `bounded_queue.py` | `scenarios/os3_3_overload.py` |
| OS3-4 transactional | `UPDATE sign_state ... WHERE version = ?` in a WAL transaction | `storage.py`, `actuator.py` | `scenarios/os3_4_transactional.py` |
| OS3-5 offline + replay | Outbox (store and forward), simulated WAN flag, idempotent receiver | `sync_worker.py`, `receiver.py` | `scenarios/os3_5_offline_demo.py` |

## 3. Key design decisions

- **Bounded queues with drop-oldest.** An unbounded queue turns an overload into
  memory growth and growing latency (buffer bloat). A bound of 500 per lane caps
  both. Dropping the oldest keeps the freshest readings, which is what a
  real-time control loop wants. Every drop is counted, so nothing disappears
  silently: `put = received + dropped + remaining`.
- **Two lanes.** Pedestrian surge alarms use the urgent lane and skip the backlog
  of background logs. The known cost is starvation of the normal lane under a
  constant stream of alarms (a fix would be aging).
- **Producer and consumer of commands are separate.** The Processor decides; the
  Actuator acts. The Actuator rechecks freshness right before moving the sign,
  because a command can wait in a queue.
- **TTL on the monotonic clock, counted from the sensor reading.** Wall-clock
  jumps (NTP, manual changes) cannot make a stale command look fresh, and time
  spent queued counts against the TTL. `CLOCK_MONOTONIC` is system-wide on Linux,
  so different processes can compare values.
- **Version-guarded state.** The check and the write are one atomic `UPDATE`.
  A stale writer matches zero rows, re-reads and decides again (optimistic
  concurrency). Every change adds 1 to `version`, so readers see consistent
  snapshots: speed 30 exactly when the version is odd, in the OS3-4 test.
- **Outbox in the same transaction as the event.** Either both rows exist or
  neither does, so no event can be stored without being queued for delivery.
- **Idempotent receiver.** Keyed by `event_id`, so a replay after reconnect does
  not duplicate data. Conservation check: stored events = delivered + pending.
- **No cloud call in the decision path.** The rule needs only local data, so
  disconnecting the WAN changes nothing for sensing, deciding or actuating.

## 4. Team decisions (`config/node.yaml`)

| Value | Setting | Reason |
|---|---|---|
| Surge threshold | 15 pedestrians | Round number above the simulated normal range; configurable |
| Normal limit | 50 km/h | Typical urban limit |
| Surge limit | 30 km/h | Given by the handbook |
| Command TTL | 15 s | Longer than a processing delay, shorter than a surge |
| Bus stop radius | 200 m | Walking distance to the crosswalk |
| Queue size | 500 | Given by the handbook |

## 5. Supervision, durability and deployment

- The supervisor exits with code 1 when a worker dies and stops and joins every
  worker on SIGTERM/SIGINT (no zombies). systemd or Docker restarts the node.
- systemd user unit: restart on failure, start burst limit, cgroup limits
  (512 MB, 150% CPU, 128 tasks), clean SIGTERM stop.
- Backup: SQLite online backup API (the node keeps writing), `integrity_check`,
  atomic rename, retention of 10 copies, `flock -n` so runs never overlap,
  15-minute timer.
- Container: unprivileged user, data volume, healthcheck that requires the API
  and all workers to be running, restart policy, resource limits.

## 6. Known limits

- Radar and pedestrian data are simulated; the bus stop file is a synthetic
  sample until the real cached Incheon BIS file is supplied.
- No restart of a single worker inside the supervisor: the whole node restarts.
- Unix socket demo and the shell scripts need Linux.
- The upstream receiver is a mock; there is no authentication or TLS.
- The priority lane can starve the normal lane (no aging).

## 7. How to reproduce

```bash
python3 -m unittest discover -s tests
python3 scenarios/run_os3_scenarios.py --quick     # smoke test, about 2 min
python3 scenarios/run_os3_scenarios.py             # official, OS3-5 offline 600 s
```

Reports are saved in `data/runs/<scenario>-<time>/report.json`; copy the
official ones to `document/results/`.
