# OS2 — Robot Edge Controller

OS2 is an educational simulation of an offline-first robot edge controller for
the pathways around Songdo Central Park. It demonstrates local sensor
processing, emergency-stop behavior that does not depend on WAN connectivity,
and durable telemetry buffering with delivery after connectivity is restored.

> **Important:** This project does not control a physical robot. Sensors and
> actuators are simulated, and the map is provided for reference only. Do not
> connect this software to real motors.

## What the project does

- Generates simulated LiDAR and IMU readings every 50 ms.
- Passes readings between processes through a bounded queue.
- Latches an emergency stop when LiDAR reports a distance **below 0.8 m**.
  The latch does not clear automatically.
- Rejects expired actuator commands; command TTL is 500 ms.
- Runs the sensor generator, controller, safety monitor, sync worker, and
  dashboard as separate supervised processes.
- Stores events in a local SQLite outbox until the mock upstream receiver
  acknowledges them.
- Shows process health, safety state, outbox status, WAN simulation controls,
  and a reference map of OpenStreetMap pathways.

## Requirements

Linux or WSL2 is supported. You need Python **3.12+**, SQLite **3.35+**,
Bash, and `flock`. Python dependencies are listed in
[`requirements.txt`](requirements.txt). Native Windows Python is not suitable
for the full runtime because OS2 uses Unix domain sockets.

## Run on Ubuntu / WSL2

Open an Ubuntu/WSL terminal in the `OS2` directory and run:

```bash
scripts/preflight.sh
scripts/setup.sh
scripts/start_demo.sh
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The demo starts the mock
upstream receiver and the five application workers. Use **Inject 0.5 m
obstacle** to demonstrate the emergency stop, and the WAN control to simulate
a disconnect and recovery. Press **Ctrl+C** in the terminal for a graceful
shutdown.

The first setup creates `.venv/` and local SQLite databases under `data/`.
These runtime files are ignored by Git.

## Tests and acceptance scenarios

Run the unit and process test suite from the `OS2` directory:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

With the demo running, use a second terminal:

```bash
PYTHONPATH=src .venv/bin/python scenarios/run_os2_scenarios.py
```

Scenario OS2-5 simulates a **600-second (10-minute)** WAN outage by default.
For a shorter development run:

```bash
PYTHONPATH=src .venv/bin/python scenarios/run_os2_scenarios.py --offline-seconds 30
```

Scenario OS2-4 deliberately kills the controller process with SIGKILL. Run
the scenarios only against a disposable OS2 instance. Do not toggle WAN
manually while OS2-5 is running.

## Run with Docker Compose

From the `OS2` directory:

```bash
docker compose -f container/compose.yaml up --build
```

The dashboard is published only on the host loopback interface
(`127.0.0.1:8000`). Press Ctrl+C to stop. Do not remove Compose volumes if
you need to preserve the demo data.

## Documentation

- [Architecture and code reference](documentation/architecture.md) — process
  topology, data flow, safety behavior, APIs, storage, and source files.
- [Operations and deployment](documentation/operations.md) — setup, launch,
  tests, scenarios, Docker/systemd, backups, and troubleshooting.
- [Implementation status](documentation/implementation-status.md) — completed
  work, verification evidence, and remaining limitations.
- [OSM source registry](sources/source_registry.csv) and
  [pathway GeoJSON](sources/songdo_central_park_pathways.geojson).

The existing [code guide](document/code-guide.md) is retained as a link to the
current documentation.
