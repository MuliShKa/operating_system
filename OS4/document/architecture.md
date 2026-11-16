# OS4 technical report — IoT Edge Gateway

Node `EDGE_NODE_OS4_IOT_HUB`, Techno-Strip Tower (37.3812 N, 126.6620 E).
All sensor data is simulated. The mist cannon is a database row plus an event; no pump is controlled.
The upstream "Urban Data Platform" is a local mock receiver.

## 1. Process architecture

One **supervisor** starts eight worker processes with the `spawn` start method (a clean interpreter per
worker, no inherited locks or threads) and one shared `Manager` dictionary for status.

| Process | Role | Talks to |
|---|---|---|
| Receiver | Mock Urban Data Platform, idempotent by `event_id` | HTTP |
| Ingest | The ONLY reader of the three sensor sockets; epoll; validates; stamps receipt time | sockets in, `sensor_events` out |
| Actuator | The ONLY process that moves the relay; checks freshness; TTL switch-off; OFF at start and stop | `commands` in, `relay_state` |
| Processor | Stores each reading (event + outbox, one transaction), orders by event time, channel health, mist rule, baseline check | `sensor_events` in, `commands` out, SQLite |
| SensorGen | Three simulated devices, different rates and formats, delayed delivery, fault switches | sockets out |
| SyncWorker | Sends outbox rows while the WAN flag is up | HTTP, SQLite |
| HealthMon | `process_health` rows: PID, CPU, RSS, voluntary/involuntary context switches | SQLite |
| API | Dashboard, `/api/status`, WAN and simulation switches | shared state |

IPC used: **Unix domain datagram sockets** (devices → Ingest), **bounded queues** (Ingest → Processor →
Actuator), shared **Events** (stop, WAN flag, ingest_done, simulation switches), a **Manager dict**
(dashboard state), **SQLite WAL** (durable shared store), **HTTP** (node → platform).

## 2. Scenario → mechanism map

| Scenario | Mechanism | Where | Evidence |
|---|---|---|---|
| OS4-1 ingestion | Non-blocking sockets + `selectors` (epoll), fairness cap per wakeup, one parser per wire format | `ingest.py`, `sensors.py` | `os4_1_ingestion.py` |
| OS4-2 event vs receipt time | `observed_at` / `received_at` columns; event time converted once to monotonic; per-sensor newest-by-event-time; late readings stored but cannot trigger | `ingest.make_event`, `processor.py`, `schema.sql` | `os4_2_event_time.py` |
| OS4-3 mist relay | Rule > 50 µg/m³, command with 30 s monotonic expiry, Actuator re-checks freshness, TTL = dead-man switch | `decision.py`, `actuator.py` | `os4_3_mist_relay.py` |
| OS4-4 backup | `Connection.backup()` in 256-page steps, integrity check, atomic rename, `flock -n` on fd 9, systemd timer `Persistent=true` | `backup.py`, `scripts/backup.sh`, `systemd/` | `os4_4_backup.py` |
| OS4-5 outage + AirKorea | Outbox (store and forward), WAN flag, ack-before-mark-sent, receiver dedup; cached baseline, median window, grade comparison | `sync_worker.py`, `receiver.py`, `baseline.py` | `os4_5_offline_demo.py` |
| OS4-6 (extra) faults | Range validation at the door, staleness from silence, stuck-at detection, fail-safe: no command from an untrusted channel | `guard.py`, `processor.py` | `os4_6_sensor_faults.py` |
| OS4-7 (extra) night policy | Multi-sensor context (lux + noise) gating the actuator; emergency override; hold reported once | `decision.py`, `processor.py` | `os4_7_night_policy.py` |

## 3. Data flow of one PM2.5 reading

1. SensorGen measures at wall time T (`observed_at`), maybe holds the datagram for a few seconds (simulated network delay), sends it to `songdo-os4-pm25.sock`.
2. Ingest wakes from epoll, reads the datagram, parses the JSON, range-checks it, stamps `received_at`, converts T to a monotonic estimate `observed_mono = received_mono − (received_at − observed_at)`, puts a `SensorEvent` in the bounded queue.
3. Processor writes `events` + `outbox` in ONE transaction (both timestamps), feeds the channel guard, compares with the newest reading by event time.
4. If it is the newest and the channel is healthy, `evaluate_mist` returns NONE / HOLD / DISPATCH. DISPATCH puts an `ActuatorCommand(expires_at = observed_mono + 30)` in the command queue.
5. Actuator takes it, compares `expires_at` with its own monotonic clock, flips the relay with a version-guarded `UPDATE`, stores the decision and an actuation event.
6. SyncWorker posts the outbox rows to the receiver; a row becomes `sent` only after the receiver acknowledged that `event_id`.

## 4. Key design decisions (short form; full reasoning in defense-notes.md)

* **Unix datagram sockets for sensors**, not shared queues: devices and gateway are decoupled by a file name; messages are framed for free; `ss -xlp | grep songdo` shows them; sensors can be restarted independently.
* **One Ingest process with epoll** instead of a thread per sensor or a polling loop: no blocking on a quiet sensor, ~0 % CPU idle, fairness cap.
* **Ingest does I/O, Processor does meaning**: the receipt stamp is taken at the earliest possible moment; ordering and rules are in one place.
* **Event time for logic, monotonic for deadlines**: wall clocks can jump; the conversion happens once.
* **Late readings are stored, never discarded, but cannot start or extend a spray**: history must be complete for the platform; actuation must follow the newest truth.
* **TTL as dead-man switch**: the relay only stays ON while fresh readings renew it.
* **Single writer for the relay (Actuator)** with a version-guarded update, OFF at start and at clean stop.
* **Outbox in the same transaction as the event** and **ack before mark-sent**: at-least-once delivery + idempotent receiver = effectively exactly-once.
* **SQLite WAL + `busy_timeout`** because five processes write one file.
* **Supervisor exits with code 1 when any worker dies**, letting systemd/Docker restart the whole node (same policy as OS3).
