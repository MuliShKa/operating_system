# OS2 implementation status, verification, and limitations

## 1. Implemented

OS2 currently includes the following simulation components:

- validated immutable sensor and actuator models;
- a bounded multiprocessing queue with a drop-oldest policy;
- simulated LiDAR and IMU generation;
- a monotonic control-loop scheduler and jitter telemetry;
- an E-stop latch for LiDAR readings below 0.8 m, zero-speed requests, and
  a process-level safety monitor with command TTL checks;
- a five-worker supervisor with a restart budget, signal handling, and child
  process cleanup;
- SQLite state, process-health records, a durable outbox, and idempotent
  mock-upstream storage;
- outbox retry and acknowledgement after simulated WAN outages;
- a local HTTP dashboard, status/events/map APIs, process metrics, sensor
  injection, and mock-WAN controls;
- OpenStreetMap pathway GeoJSON with attribution and ODbL 1.0 metadata,
  rendered as a reference SVG map in the dashboard;
- an online SQLite backup utility, setup/launch scripts, Docker Compose,
  systemd user units, and five acceptance demonstrations.

See [architecture.md](architecture.md) and [operations.md](operations.md)
for implementation and operating details.

## 2. Verification evidence

Latest OS2 verification on 2026-11-17:

- **26/26** unit and process tests passed in WSL2.
- OS2-1 through OS2-5 passed in an isolated 30-second acceptance run:
  **29 outage events** were acknowledged without loss or duplicate IDs.
- The full **600-second** acceptance run passed: **599 outage events** were
  acknowledged without loss or duplicate IDs.
- Both acceptance runs completed graceful SIGTERM shutdown without forced
  process-group termination.
- Compose configuration validation passed.
- The map API and rendered dashboard map were inspected; the GeoJSON contains
  **390 features** and OSM attribution.

The earlier SIGTERM hang after a controller crash was fixed by using a
lock-free shared stop flag for supervisor-managed workers. The lifecycle test
now covers controller restart followed by stopping every worker.

## 3. Remaining work and known limitations

### Physical robot and safety

- LiDAR and IMU are simulated; physical sensor drivers are not implemented.
- `MOTOR_VEL` and `SAFETY_ESTOP_LATCH` are simulated outputs; no actuator or
  motor controller is connected.
- There is no manual E-stop reset workflow. The latch must not clear
  automatically when an obstacle disappears.
- No hardware emergency-stop circuit, independent watchdog, fault-tolerant
  controller, safety certification, or hardware-in-the-loop test is included.
- Python/Linux does not provide hard real-time guarantees.

### Navigation and map

- The OSM extract is reference geometry, not a surveyed or validated robot
  navigation map.
- Localization, coordinate calibration, navigation graph generation, route
  planning, geofencing, and route-level obstacle avoidance are not implemented.
- The official data search and selected OSM extract are recorded in
  `sources/source_registry.csv`; license and retrieval metadata are in the
  GeoJSON.

### Connectivity and operations

- The upstream is a local mock receiver, not a production cloud service.
- Cloud authentication, secure remote transport, and production deployment
  configuration are not implemented.
- The dashboard is intended for loopback use and has no user authentication;
  do not expose it publicly.
- Backup rotation/retention and an external backup destination are not
  configured.

## 4. Map source and attribution

`sources/songdo_central_park_pathways.geojson` contains 390 pathway ways in
the Songdo Central Park bounding box recorded in its metadata. The source is
OpenStreetMap contributors and the license is Open Database License (ODbL)
1.0. Metadata records the source URL and query, retrieval time, included
pathway types, feature count, attribution, and limitations. The dashboard
links to the OSM copyright page.

This data is not represented as an official municipal survey or proof that
any route is accessible or safe.
