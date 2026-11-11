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

The current code provides data models, inter-process communication helpers, a periodic scheduler, and local safety decisions. Unit tests cover these parts.

The following work is not implemented yet:

- A sensor generator or a process that reads physical LiDAR or IMU hardware.
- A supervisor that starts workers and restarts a killed process within two seconds.
- A network outbox worker that saves events during WAN loss and delivers them later.
- A dashboard, container setup, or systemd service for OS2.
- Loading `config/node.yaml` automatically into the Python classes.

Because of these limits, the current project is a tested foundation, not a complete robot application. It does not control real motors.

## 3. Folder Layout

```text
OS2/
├── config/
│   └── node.yaml             # Robot identity, sensors, safety values, and IPC settings
├── document/
│   └── code-guide.md         # This guide
├── src/edge/
│   ├── __init__.py           # Marks edge as a Python package
│   ├── bounded_queue.py      # Process-safe, bounded sensor queue
│   ├── control.py            # E-stop decisions, command checks, and periodic loop
│   ├── models.py             # Validated sensor and actuator data objects
│   └── unix_socket.py        # Local JSON request/response socket
└── tests/
    ├── test_control.py       # Timing and safety behavior tests
    ├── test_ipc.py           # Queue and socket tests
    └── test_models.py        # Data validation tests
```

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

## 6. Unix Domain Socket: `src/edge/unix_socket.py`

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

## 7. Control Logic: `src/edge/control.py`

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

### `RobotSafetyController`

`evaluate_proximity(reading, now_monotonic)` accepts only a reading named `LIDAR_PROXIMITY_M`. When the reading is below the configured threshold, the controller latches E-stop and returns two commands:

1. `SAFETY_ESTOP_LATCH = True`
2. `MOTOR_VEL = 0.0`

Both commands expire after the configured TTL. The latch remains active after the obstacle moves away. This is intentional: the robot must not restart by itself after a safety event.

`accepts(command, now_monotonic)` rejects expired commands. While E-stop is latched, it also rejects non-zero motor velocity and a command that tries to clear the safety latch. A manual reset policy has not been implemented yet.

## 8. Configuration: `config/node.yaml`

The YAML file is the planned source for OS2 settings:

- `name`, `project`, and `location` identify the node.
- `sensors` and `actuators` list supported input and output names.
- `control` contains the 50 ms period, 0.8 m threshold, and 500 ms TTL.
- `ipc` contains queue capacity and the Unix socket path.
- `offline.durable_outbox` records the offline-persistence requirement.

At this stage, Python constructors still use matching default values; the YAML file is not loaded by code yet. A later integration step should load and validate this file rather than duplicate its values.

## 9. Tests and How to Run Them

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

The model tests check finite values and TTL boundaries. The queue tests check drop-oldest behavior and child-process sharing. The control tests check the 50 ms schedule, jitter, the strict 0.8 m threshold, the latched stop, and command expiry. The socket test is skipped when `AF_UNIX` is not available.

## 10. Important Safety Notes

- This code is an educational simulation. It must not be connected to real motors without hardware safety review and additional interlocks.
- A Python process and a general-purpose Linux scheduler do not guarantee hard real-time behavior. The 50 ms period is a target that the code measures, not a hard real-time guarantee.
- The socket path in the config is local to a Linux host. It is not a network address.
- Local control should not wait for WAN access. Durable offline event storage and reconnection behavior are still future work for OS2.
- The current E-stop latch has no reset function. Do not add an automatic reset when the obstacle disappears.