# 🏙️ Operating System — Songdo Edge Projects

> **In a nutshell:** this repository contains educational operating systems and
> edge-computing projects — processing data near its sensors, even when the
> internet is unavailable.
>
> 🎓 These are learning simulations. They demonstrate processes, queues, IPC,
> data storage, and fault tolerance, but **do not control real-world equipment**.

## 🗺️ Project map

| Project | Idea | Repository status |
|---|---|---|
| 🏢 **OS1** | Smart building gateway: occupancy and CO₂ sensors, with local HVAC logic | 🧩 Folder scaffold; no working application implementation yet |
| 🤖 **OS2** | Robot edge controller: obstacle distance, emergency stop, and offline operation | ✅ Simulation implemented; [detailed README](OS2/README.md) |
| 🚦 **OS3** | Autonomous mobility node: pedestrian-aware variable speed sign, bus stop context, and offline operation | ✅ Educational simulation implemented and tested; [detailed README](OS3/README.md) |
| 🌫️ **OS4** | IoT gateway: PM2.5, noise and light streams, dust-suppression mist cannon, backups, AirKorea benchmark | ✅ Educational simulation implemented and tested; [detailed README](OS4/README.md) |
| 🌊 **OS5** | Fault-tolerant smart-city node: water level, power, local decisions, and event delivery after connectivity returns | ✅ Educational simulation available; [project README](OS5/README.md) |

The OS1–OS5 names and scenarios reflect the team mini-projects described in the
course materials. The status above describes what is actually present in the
repository: projects marked 🧩 contain only directory scaffolds, not completed
applications.

## 🔎 What each project means

### 🏢 OS1 — Smart Building Edge Gateway

The **smart building gateway** is intended to collect occupancy and CO₂
readings, process them locally, and produce a decision for HVAC — heating,
ventilation, and air conditioning.

- **Input:** occupancy/motion sensor readings and CO₂ levels.
- **Goal:** demonstrate how a gateway makes a decision close to the data source.
- **Intended output:** a command for a ventilation damper.
- **Status:** `OS1/` contains the project directory structure, but no application
  code has been added yet.

### 🤖 OS2 — Robot Edge Controller

The **local robot controller** demonstrates sensor processing and safe behavior
without depending on internet connectivity.

- **Input:** simulated LiDAR and IMU readings.
- **Goal:** pass readings between processes, monitor safety, and store events
  locally.
- **Intended output:** a latched emergency stop and movement commands (in this
  version, they do not control a real robot).
- **Feature:** events are saved to a SQLite outbox while connectivity is down
  and sent to a mock receiver after it returns.
- **Status:** a software demonstration is implemented, including an API,
  dashboard, tests, and operational documentation.

➡️ Getting started and limitations: [OS2/README.md](OS2/README.md).

### 🚦 OS3 — Autonomous Mobility Edge Node

The **autonomous mobility node** processes road conditions locally at an
intersection.

- **Input:** simulated vehicle speeds and pedestrian counts at a crosswalk, plus
  cached Incheon bus stop context.
- **Goal:** keep deciding when the WAN is cut. A pedestrian surge lowers the
  variable speed sign to 30 km/h with no remote server involved.
- **Output:** a sign command that expires 15 s after the sensor reading; a
  separate Actuator rejects stale commands. In this version it does not control a
  real sign.
- **Features:** priority and bounded queues (drop-oldest), version-guarded SQLite
  state, an outbox that delivers events after a simulated WAN cut with an event
  conservation check, systemd units, a `flock`-guarded backup, a Docker image,
  and a script for each scenario (OS3-1 to OS3-5).
- **Status:** an educational simulation is implemented, with an API, dashboard,
  tests, official run reports, and technical documentation.

➡️ Setup, tests and scenarios: [OS3/README.md](OS3/README.md).

### 🌫️ OS4 — IoT Edge Gateway

The **environmental monitoring gateway** on the Techno-Strip Tower aggregates three different sensors
and decides locally whether to run a dust-suppression mist cannon.

- **Input:** simulated PM2.5, ambient noise and illumination, each with its own rate, unit and message
  format, sent over Unix domain sockets to one Ingest process (epoll).
- **Goal:** keep working when the WAN is cut. Readings keep their sensor timestamp (`observed_at`)
  separately from the arrival time (`received_at`); late readings are ordered by event time.
- **Output:** `MIST_CANNON_RELAY` command when PM2.5 > 50 µg/m³, valid for 30 s; a separate Actuator
  rejects stale commands and switches the relay off when the command expires. No real pump is controlled.
- **Features:** durable SQLite outbox with idempotent receiver and 100 % acknowledgement check, `flock`-guarded
  online backup with a systemd timer, systemd service, Docker image, dashboard, a cached AirKorea station
  benchmark, and two extra scenarios (sensor-fault fail-safe, quiet-night policy).
- **Status:** an educational simulation is implemented, with an API, dashboard, unit tests, scenario
  scripts (OS4-1 to OS4-7) and documentation. AirKorea data is a flagged synthetic sample until the real
  station file is added.

➡️ Setup, tests and scenarios: [OS4/README.md](OS4/README.md).

### 🌊 OS5 — Fault-Tolerant Smart-City Node

The **fault-tolerant smart-city node** demonstrates how a local service can
continue processing events during a network failure.

- **Input:** simulated water-level and power-voltage readings.
- **Goal:** process measurements in multiple processes, record events and
  decisions in SQLite, and monitor worker health.
- **Intended output:** a software decision about a backup sluice gate. No real
  equipment is connected.
- **Feature:** events are placed in a local delivery queue and synchronized
  with a local mock receiver when simulated WAN connectivity is enabled.
- **Status:** `OS5/` contains an educational simulation and its own
  documentation.

➡️ Setup and details: [OS5/README.md](OS5/README.md).

## 🧠 Common concepts, simply explained

| Term | Plain-language explanation |
|---|---|
| **Edge computing** 📍 | Processing data near the sensors, instead of relying only on the cloud. |
| **Process** ⚙️ | An independently running part of an application, such as a sensor generator or API. |
| **IPC** 🔁 | Ways for processes to exchange data. |
| **Bounded queue** 📥 | A queue with a size limit, so data cannot consume all available memory. |
| **SQLite** 🗃️ | A local database stored in a file. |
| **Outbox / store-and-forward** 📤 | An event is saved locally first, then sent when connectivity is available. |
| **WAN** 🌐 | An external network connection; its state is simulated in these demos. |
| **Supervisor** 🛡️ | A process that starts and monitors workers and can restart a worker that fails. |

## 📁 Repository layout

- `OS1/`–`OS5/` — separate educational projects. Each project has its own
  configuration, source code, and data; similarly named folders belong to
  different projects.
- `src/` — a separate root-level folder with two source files
  (`shared_counter.py` and `storage.py`). It is not a standalone application and
  has no README; use the instructions for a specific project to run a demo.

Project folders may contain directories such as:

`src/` — source code · `config/` — settings · `tests/` — tests · `scenarios/` —
demonstration scenarios · `sql/` — database schema · `scripts/` — setup and
maintenance commands · `container/` — Docker files · `systemd/` — Linux
services · `documentation/` or `document/` — project materials · `data/` —
local data and backups.

## ▶️ Where to start

1. Choose a project from the table above.
2. Open its README and follow that project's requirements and run commands.
3. **OS2** requires Linux/WSL2; see the [OS2 README](OS2/README.md).
4. For **OS3**, use Linux/WSL2 and follow the [OS3 README](OS3/README.md).
5. For **OS5**, start with the [OS5 README](OS5/README.md).
6. Do not use this code to control physical devices: sensors, receivers, and
   actuators in these demonstrations are software simulations.

### 🏷️ Status legend

- ✅ Project code and its own run instructions are available.
- 🧩 Only a scaffold is present; the application still needs to be implemented.
- 🎓 Educational demonstration — not an industrial system and not intended to
  control real-world equipment.
