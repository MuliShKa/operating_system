# OS2 architecture and code reference

## 1. Purpose and scope

OS2 is an educational Linux/WSL2 simulation of a robot edge controller. It
demonstrates process isolation, local safety checks, durable telemetry
buffering during network outages, worker restart supervision, and a local
operator dashboard.

LiDAR and IMU readings are generated in software. A LiDAR distance strictly
**below 0.8 m** latches the emergency stop. Actuator commands are valid for
**500 ms**, and the target control period is **50 ms**.

This project is not a real-time operating system, has no physical hardware
interface, and must not be used to control a real robot.

## 2. Process topology

`edge.supervisor` launches five child processes using Python multiprocessing
with the `spawn` context:

| Role | Entry point | Responsibility |
|---|---|---|
| `safety-monitor` | `edge.workers.run_safety_monitor` | Validates actuator commands, maintains the E-stop latch, and exposes safety status over a Unix socket. |
| `sensor-generator` | `edge.sensor.run_sensor_generator` | Generates simulated LiDAR and IMU samples and publishes them to a bounded process-safe queue. |
| `controller` | `edge.workers.run_controller` | Consumes readings, evaluates safety, sends actuator requests, and records periodic telemetry. |
| `sync-worker` | `edge.sync_worker.run_sync_worker` | Retries local outbox batches until an upstream acknowledgement arrives. |
| `api-server` | `edge.api_server.run_api_server` | Serves the dashboard, status/events/map API, and demo controls. |

`edge.upstream_receiver` runs separately from the supervisor. It simulates a
remote receiver and WAN availability. It can be disabled or switched offline
without stopping local sensor processing and safety workers.

```text
simulated sensor generator
          │
          ▼
bounded multiprocessing queue
          │
          ▼
controller ── Unix socket/JSON ──► safety monitor
     │                                    │
     ├── sensor-state persistence         │
     └── telemetry/E-stop events          │
                    │                     │
                    ▼                     ▼
              local SQLite ◄──── dashboard API
                    │
                    ▼
               sync worker ── Unix socket ──► mock receiver ── SQLite
```

By default, the HTTP dashboard listens on `127.0.0.1:8000`. In Compose, the
API binds to `0.0.0.0` inside its container, but Docker publishes the host
port only on `127.0.0.1:8000`.

## 3. Data flow and safety behavior

1. `sensor.py` generates LiDAR distances in the range 0.2–3.0 m and IMU yaw
   rates in the range -1.5–1.5 rad/s. Both readings in a sample cycle share
   a monotonic timestamp.
2. `bounded_queue.py` transports immutable `SensorReading` values between
   processes. Its default capacity is 500. When full, it removes the oldest
   reading and increments a shared drop counter.
3. `control.py` processes queued readings in order. IMU values are recorded
   but do not participate in the LiDAR obstacle rule.
4. If LiDAR reports less than 0.8 m, the controller latches
   `SAFETY_ESTOP_LATCH = True` and requests `MOTOR_VEL = 0`. The latch remains
   set after the obstacle disappears.
5. Without a fresh safe LiDAR reading, the controller requests zero speed.
   With a fresh safe reading, the simulation may request movement up to
   0.5 m/s.
6. The safety monitor checks command type/range, monotonic issue/expiry time,
   expiration, and E-stop state. Expired and future-issued commands are
   rejected. Actuator state is simulated in memory; no motor driver exists.
7. When the safety monitor first latches E-stop, it stores the latch state and
   an `ESTOP_LATCHED` outbox event in one SQLite transaction. The latch
   survives worker restarts. A reset workflow is not implemented.

Command times use a monotonic clock; SQLite audit timestamps use wall time.
General-purpose Linux scheduling does not guarantee hard real-time behavior:
OS2 measures jitter but does not guarantee a maximum.

## 4. Offline outbox and upstream acknowledgement

Local events are stored in `data/os2.db`. `storage.py` uses SQLite WAL mode,
short-lived per-operation connections, a 5-second busy timeout, and
`synchronous=FULL`.

The sync worker sends the oldest unacknowledged events in batches (up to 50
by default). The mock receiver writes events to `data/upstream.db`, where
`event_id` is unique. This makes retries idempotent. Local rows are marked
sent only after the receiver acknowledges them. While WAN is offline or the
receiver is unavailable, events remain in the local outbox.

The mock receiver is a local educational integration. It is not a production
cloud service, an authentication boundary, or a guarantee of remote
persistence.

### SQLite tables

Local schema (`sql/schema.sql`):

- `outbox`: sequence `seq`, unique `event_id`, type, JSON payload, creation
  timestamp, and nullable acknowledgement timestamp.
- `process_health`: process role, PID, status, details, and check timestamp.
- `robot_state`: persistent key/value state, including the E-stop latch and
  latest simulated sensor readings.

Receiver schema (`sql/upstream_schema.sql`):

- `received_events`: unique event ID, event type, JSON payload, and source
  creation timestamp.

`latest_outbox_sequence()` and `outbox_event_ids_after()` let OS2-5 identify
only the events created during its WAN outage.

## 5. Inter-process communication

### Sensor queue

The process-shared queue transports `SensorReading` objects.
`BoundedSensorQueue` implements a bounded FIFO with a drop-oldest policy.

### Unix domain sockets

`unix_socket.py` sends one newline-delimited UTF-8 JSON request and response
per connection. Paths are local to the Linux host and defined in
`config/node.yaml`:

- `/tmp/songdo-os2/safety.sock` — controller/API to safety monitor.
- `/tmp/songdo-os2/upstream.sock` — API/sync/scenarios to mock receiver.

The safety socket supports `status` and `apply`; the upstream socket supports
`status`, `network`, `deliver`, and `contains`. The server refuses to replace
a live socket or a non-socket path. It removes a stale socket only after
checking it. Connections have timeouts.

Both Compose services must share the Unix-socket directory. These sockets
are local IPC, not network services; do not expose them over a network.

## 6. HTTP API and dashboard

`api_server.py` uses Python's built-in `ThreadingHTTPServer`; there is no
external web framework.

| Method and path | Purpose |
|---|---|
| `GET /` or `/index.html` | Serves `src/ui/static/index.html`. |
| `GET /api/status` | Returns node, process metrics, outbox counts, latest sensor readings, safety state, and mock WAN status. |
| `GET /api/events` | Returns recent local outbox events, newest first. |
| `GET /api/map` | Serves the GeoJSON as `application/geo+json`. |
| `POST /api/network` | Sets mock receiver WAN state; JSON `{"online":false}` or `{"online":true}`. |
| `POST /api/sensor` | Enqueues a sample: LiDAR 0.2–3.0 m or IMU -1.5–1.5 rad/s. |

POST bodies are limited to 4096 bytes and validated. The dashboard renders
pathway geometry locally as SVG, displays OSM attribution, and refreshes
status/events every second.

This is a local demo API, not a hardened public service. Keep it on loopback.
External access requires authentication, authorization, TLS, and additional
request protections.

## 7. Configuration

`edge.config.load_config()` reads `config/node.yaml`. Relative database paths
are resolved from the OS2 project directory.

| Setting | Default | Meaning |
|---|---:|---|
| `control.period_ms` | 50 | Target controller and sensor period. |
| `control.obstacle_threshold_m` | 0.8 | A closer reading latches E-stop. |
| `control.command_ttl_ms` | 500 | Command lifetime. |
| `ipc.bounded_queue_size` | 500 | Sensor queue capacity. |
| `offline.database_path` | `data/os2.db` | Local state and outbox database. |
| `offline.upstream_database_path` | `data/upstream.db` | Mock receiver database. |
| `offline.sync_batch_size` | 50 | Maximum events per delivery batch. |
| `supervisor.restart_burst` | 5 | Restart attempts per worker role. |
| `supervisor.restart_window_s` | 10 | Rolling restart window. |
| `api.host` / `api.port` | `127.0.0.1` / `8000` | API bind address and port. |

`OS2_API_HOST` and `OS2_API_PORT` override the dashboard bind address/port.
`OS2_PYTHON` selects the interpreter used by shell scripts. `project`,
`location`, `sensors`, and `actuators` in YAML are descriptive; worker code
uses fixed sensor and actuator names.

`load_config()` validates positive finite timing values, positive queue/batch
and restart settings, API port range, absolute distinct socket paths, and
different local/upstream database paths.

## 8. Source file reference

| Path | Purpose |
|---|---|
| `src/edge/models.py` | Immutable validated sensor-reading and actuator-command contracts. |
| `src/edge/config.py` | YAML parsing, environment overrides, and runtime validation. |
| `src/edge/bounded_queue.py` | Process-safe bounded FIFO, drop-oldest policy, and drop counter. |
| `src/edge/sensor.py` | Simulated sensor generation and worker loop. |
| `src/edge/control.py` | Monotonic scheduler, jitter measurement, batch evaluation, and safety decisions. |
| `src/edge/workers.py` | Controller and safety-monitor processes, command checks, state persistence, and telemetry. |
| `src/edge/unix_socket.py` | Local JSON IPC, timeouts, and socket-path protections. |
| `src/edge/storage.py` | SQLite schema, outbox, state, process health, and event queries. |
| `src/edge/supervisor.py` | Five workers, restart budget, signal handling, and child cleanup. |
| `src/edge/sync_worker.py` | Outbox retry and acknowledgement handling. |
| `src/edge/upstream_receiver.py` | Idempotent mock receiver, WAN switch, and event lookup. |
| `src/edge/api_server.py` | Local HTTP API, process metrics, input validation, and static files. |
| `src/edge/maintenance.py` | Online SQLite backup and integrity check. |
| `src/ui/static/index.html` | Self-contained dashboard, refresh logic, and SVG map renderer. |
| `scenarios/run_os2_scenarios.py` | Five demonstrations for topology, timing, safety, restart, and offline delivery. |
| `tests/` | Unit and process tests using `unittest`. |
| `scripts/` | Preflight, environment setup, launch, and locked backup. |
| `container/` | Dockerfile and two-service Compose deployment. |
| `systemd/` | User services and hourly backup timer. |
| `sources/` | OSM pathway GeoJSON and source registry. |

## 9. Songdo Central Park pathway data

`sources/songdo_central_park_pathways.geojson` is an OpenStreetMap extract
within the bounding box recorded in its metadata. It contains 390 pathway
ways selected from `footway`, `path`, `pedestrian`, `steps`, and `cycleway`.
The metadata records the source URL, query, retrieval time, attribution,
Open Database License (ODbL) 1.0, and limitations.

The map is for reference only. Robot localization, a validated navigation
graph, route planning, geofencing, and route-level obstacle avoidance are not
implemented. OSM completeness and accuracy are not guaranteed.
