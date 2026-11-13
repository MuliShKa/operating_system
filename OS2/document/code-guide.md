# OS2 Robot Edge Controller: Code Guide

## 1. Project Goal

OS2 is the Robot Edge Controller project for the Songdo Central Park pathways. Its main goal is to keep the robot's local safety behavior available even when the Internet connection is lost.

The controller reads two sensor types:

- `LIDAR_PROXIMITY_M`: distance from an obstacle, measured in metres.
- `IMU_YAW_RATE`: robot turning speed, measured as an angular rate.

The simulated outputs are:

- `SAFETY_ESTOP_LATCH`: an on/off emergency stop signal.
- `MOTOR_VEL`: requested motor velocity.

The safety rule follows the assignment: when LiDAR distance is **less than 0.8 m**, latch the emergency stop and request zero motor velocity. A distance equal to `0.8 m` does not trigger the rule. Commands are valid for `500 ms`. The intended control period is `50 ms`.

## 2. Current Implementation Status

The current implementation includes simulated sensors, a controller, a safety
monitor, a durable outbox sync worker, a loopback HTTP dashboard, an optional
mock upstream receiver, Linux service/container files, and five OS2 acceptance
scenarios. The supervisor records process lifecycle in SQLite, restarts failed
workers within the configured budget, and stops its child processes on SIGINT
or SIGTERM. The dashboard can inject a simulated obstacle and toggle the mock
WAN. The sync worker retains events until the upstream receiver acknowledges
them; receiver writes are idempotent by event ID.

The node is still a software simulation. Physical LiDAR/IMU hardware, robot
localization, route planning, and real motor control are not implemented. An
OpenStreetMap pathway extract is bundled for reference, but it is not surveyed
or validated for robot navigation. OSM attribution, license, retrieval
timestamp, and extract scope are recorded in the dataset and
`sources/source_registry.csv`.

## 3. Folder Layout

```text
OS2/
├── config/node.yaml                  # Node, safety, IPC, sync, and API settings
├── container/                        # Ubuntu image and robot/upstream Compose services
├── sources/songdo_central_park_pathways.geojson # OSM pathways (ODbL 1.0)
├── document/code-guide.md            # Architecture and operator guide
├── scenarios/run_os2_scenarios.py   # Five OS2 acceptance demonstrations
├── scripts/                          # Preflight, setup, launch, and locked backup
├── sources/source_registry.csv      # OS2 route-data source search and status
├── src/edge/
│   ├── api_server.py                 # HTTP API and local dashboard server
│   ├── bounded_queue.py              # Process-safe bounded sensor queue
│   ├── config.py                     # YAML configuration loader
│   ├── control.py                    # Safety decisions and periodic scheduler
│   ├── maintenance.py                # Online SQLite backup utility
│   ├── models.py                     # Validated sensor and actuator data
│   ├── sensor.py                     # Simulated LiDAR/IMU worker
│   ├── storage.py                    # WAL outbox, health, and persistent state
│   ├── supervisor.py                 # Worker restart and shutdown handling
│   ├── sync_worker.py                # Durable outbox delivery and retry
│   ├── upstream_receiver.py          # Optional idempotent mock receiver
│   ├── unix_socket.py                # Local JSON request/response IPC
│   └── workers.py                    # Controller and safety monitor processes
├── sql/                              # Local and upstream SQLite schemas
├── systemd/                          # User services and hourly backup timer
└── tests/                            # Unit and multiprocessing test suite
```

## 3.1 Run the local process pipeline

On Ubuntu 24.04 or WSL2, from the `OS2` directory:

```bash
scripts/preflight.sh
scripts/setup.sh
scripts/start_demo.sh
```

Open `http://127.0.0.1:8000`. The supervisor starts the safety monitor, sensor
generator, controller, sync worker, and dashboard. Press Ctrl+C for a graceful
shutdown. Unexpected worker exits are restarted up to `restart_burst` times per
`restart_window_s`; exceeding that limit stops the service. Health transitions
are recorded in `process_health`.

The WAN buttons toggle delivery at the mock receiver. The obstacle button
injects a simulated 0.5 m LiDAR sample to demonstrate the latched E-stop.
To start only the receiver separately, use:

```bash
PYTHONPATH=src python3 -m edge.upstream_receiver
```

## 3.2 Run the OS2 acceptance scenarios

With the demo running, execute:

```bash
PYTHONPATH=src python3 scenarios/run_os2_scenarios.py
```

The runner checks all five OS2 scenarios, including process restart within two
seconds and event delivery after a ten-minute simulated WAN outage. Use
`--offline-seconds N` only for a shorter development demonstration.

## 3.3 Linux setup and deployment

The OCI image and two-service Compose setup are in `container/`. From the
`OS2` directory, use `docker compose -f container/compose.yaml up --build`.
The host dashboard port is bound to loopback.

The systemd user units and hourly online-backup timer are in `systemd/`; adjust
the unit working directory if the repository is not at
`$HOME/operating_system/OS2`. Install and enable them with:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/songdo-edge@.service systemd/songdo-edge-upstream@.service \
  systemd/songdo-edge-backup.service systemd/songdo-edge-backup.timer \
  ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now songdo-edge@OS2.service \
  songdo-edge-upstream@OS2.service songdo-edge-backup.timer
```

## 3.4 OSM pathway reference map

The dashboard loads `/api/map`, which serves
`sources/songdo_central_park_pathways.geojson`. The extract contains 390
OpenStreetMap pathway ways within the recorded bounding box. The dashboard
renders the geometry as a reference overview and displays the required
attribution and ODbL 1.0 link.

The extract is not surveyed or validated for navigation. The project still
does not provide robot localization, route planning, or physical movement.
Use the GeoJSON metadata and `sources/source_registry.csv` for source,
retrieval, license, and scope details.

## 4. Data Models: `src/edge/models.py`

### `SensorReading`

`SensorReading` represents one observation from one sensor. It stores a sensor name, a numeric value, its unit, and the event time when the sensor made the measurement.

Example:

```python
reading = SensorReading(
    sensor_id="LIDAR_PROXIMITY_M",
    value=0.72,
    unit="m",
    observed_at=12.5,
)
```

The class is a frozen dataclass. After creation, its fields cannot be changed. Validation rejects blank names, blank units, and non-finite numbers such as NaN or infinity. This prevents invalid sensor values from entering the queue.

### `ActuatorCommand`

`ActuatorCommand` represents one requested output. It includes a unique command ID, the actuator name, the requested value, and the command's issue and expiry times.

For safety, `issued_at` and `expires_at` must use the same monotonic time source. Wall-clock time can change when the system clock is corrected; monotonic time is intended for measuring durations.

`is_expired(now)` returns `True` when `now` is equal to or later than `expires_at`. The exact expiry boundary is therefore rejected, not accepted.

## 5. Bounded Queue: `src/edge/bounded_queue.py`

`BoundedSensorQueue` wraps Python's multiprocessing queue. Its maximum size is fixed when the queue is created; the default is 500 readings.

### Drop-oldest behavior

When the queue is full, `put(reading)` removes the oldest reading and inserts the new reading. This policy is useful for control data because a recent distance measurement is usually more useful than an old one. The queue stays within its size limit instead of growing without control.

The producer lock protects the remove-and-insert operation. Without this lock, two producers could both react to a full queue and remove more readings than necessary. A shared counter records how many readings were dropped.

### Reading data

`get(timeout)` returns the oldest available reading. If a timeout is supplied and no reading arrives before it ends, the method returns `None`. A negative timeout is rejected. Waiting uses a monotonic deadline.

Example:

```python
sensor_queue = BoundedSensorQueue(maxsize=500)
sensor_queue.put(reading)
next_reading = sensor_queue.get(timeout=0.1)
```

The queue can be passed to child processes created from the same multiprocessing context. The unit test uses the `spawn` context to verify this behavior.

## 6. Simulated Sensors: `src/edge/sensor.py`

`make_simulated_readings(rng, observed_at)` creates one pair of sample values:

- LiDAR distance is between `0.2` and `3.0` metres. The range includes distances below the E-stop threshold so the safety behavior can be demonstrated.
- IMU yaw rate is between `-1.5` and `1.5` radians per second.

Both readings share the same `observed_at` value because they belong to the same sample cycle. A `random.Random` instance is passed in so a test can use a fixed seed and produce repeatable values.

`run_sensor_generator(sensor_queue, stop_event, interval_s, seed)` is the process worker. It creates a local random generator, publishes both sensor readings, then waits for the next sample interval. The wait uses the stop event, so a supervisor can request shutdown without waiting for a full sleep interval. The default sample interval is `50 ms`, matching the control-loop target.

The worker only generates simulated data. It does not open a physical sensor device. A separate process can be started with Python's multiprocessing API and given the same `BoundedSensorQueue` used by the controller.

## 7. Unix Domain Socket: `src/edge/unix_socket.py`

`UnixMessageServer` and `UnixMessageClient` provide local request/response communication between processes on one host. A Unix domain socket does not require a TCP port.

### Message format

Messages are JSON objects encoded as UTF-8. Each message ends with a newline, which marks the end of one request or response. One client connection carries one request and one response.

Example request:

```json
{"cmd":"status"}
```

The server passes the decoded object to its handler. The handler returns another object for the response. If decoding or handling raises a supported error, the server sends an object with an `error` field and keeps running.

### Start and stop

The server creates the parent directory if it is missing and removes a stale socket file before binding. `close()` stops the server thread, closes the socket, and removes the socket file. The server supports a `with` statement so cleanup happens even when an exception leaves the block.

Both sides use timeouts so a client that connects but sends nothing cannot block the server forever. The socket test runs only on systems that provide `socket.AF_UNIX`. Windows Python may not provide this feature; use WSL Ubuntu to run the full socket test.

## 8. Control Logic: `src/edge/control.py`

### `JitterMonitor`

The target period is `0.05` seconds. For every tick after the first one, jitter is calculated as:

```text
jitter = abs(actual_period - target_period)
```

For example, if the actual period is `0.053` seconds and the target is `0.050` seconds, the jitter is `0.003` seconds, or 3 ms. The first tick has no previous tick to compare with, so its result is `None`. Tick timestamps must increase monotonically.

### `run_periodic_control_loop`

This function waits for monotonic deadlines and calls a callback for every control tick. The callback receives the current monotonic time and the measured jitter. The first callback runs immediately.

If the callback takes too long and misses one or more deadlines, the scheduler skips those deadlines. It does not run many immediate callbacks to catch up. This prevents one slow cycle from causing a burst of unsafe or outdated actions. A stop event can wake the loop early during shutdown.

The current function is a scheduling helper. A process must still supply an `on_tick` callback that reads data and applies the returned decisions.

`evaluate_pending_sensor_readings(sensor_queue, controller, now_monotonic)` connects the bounded queue to the safety controller. It waits briefly for the first reading, drains the current queue batch, ignores IMU readings for the LiDAR stop rule, and evaluates every LiDAR reading in order. Processing the full batch is important: a safe reading that follows a close-obstacle reading must not hide that hazard because the E-stop is latched.

### `RobotSafetyController`

`evaluate_proximity(reading, now_monotonic)` accepts only a reading named `LIDAR_PROXIMITY_M`. When the reading is below the configured threshold, the controller latches E-stop and returns two commands:

1. `SAFETY_ESTOP_LATCH = True`
2. `MOTOR_VEL = 0.0`

Both commands expire after the configured TTL. The latch remains active after the obstacle moves away. This is intentional: the robot must not restart by itself after a safety event.

`accepts(command, now_monotonic)` rejects expired commands. While E-stop is latched, it also rejects non-zero motor velocity and a command that tries to clear the safety latch. A manual reset policy has not been implemented yet.

## 9. Configuration: `config/node.yaml`

`edge.config.load_config()` reads the runtime settings from the YAML file:

- `name` identifies the node in the dashboard.
- `control` contains the 50 ms period, 0.8 m threshold, and 500 ms TTL.
- `ipc` contains queue capacity and the local Unix socket paths.
- `offline` contains the local and mock-upstream database paths and sync batch
  size. Both databases use durable SQLite storage.
- `supervisor` sets the restart limit and rolling time window.
- `api` sets the dashboard bind address and port. `OS2_API_HOST` and
  `OS2_API_PORT` environment variables can override these two values.

`project`, `location`, `sensors`, and `actuators` are descriptive entries; the
current runtime uses fixed sensor and actuator names in its workers.
Relative database paths are resolved under the OS2 project directory. IPC
socket paths must be absolute and distinct.

## 10. Tests and How to Run Them

Run all tests from the `OS2` directory.

### Ubuntu or WSL Ubuntu

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

### PowerShell on Windows

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

The model tests check finite values and TTL boundaries. The queue tests check drop-oldest behavior and child-process sharing. The sensor tests check generated ranges and clean process shutdown. The control tests check the 50 ms schedule, jitter, the strict 0.8 m threshold, the latched stop, and command expiry. The socket test is skipped when `AF_UNIX` is not available.

## 11. Important Safety Notes

- This code is an educational simulation. It must not be connected to real motors without hardware safety review and additional interlocks.
- A Python process and a general-purpose Linux scheduler do not guarantee hard real-time behavior. The 50 ms period is a target that the code measures, not a hard real-time guarantee.
- The socket path in the config is local to a Linux host. It is not a network address.
- Local control does not wait for WAN access. Events remain in the durable
  local outbox until the optional mock upstream acknowledges them; this
  demonstrates retry and recovery behavior but is not a production cloud
  receiver.
- The current E-stop latch has no reset function. Do not add an automatic reset when the obstacle disappears.