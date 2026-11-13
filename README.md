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
| 🚦 **OS3** | Autonomous mobility node: traffic flow and local speed-limit control | 🧩 Folder scaffold; no working application implementation yet |
| 🌫️ **OS4** | IoT gateway: air quality and noise monitoring, with local processing | 🧩 Folder scaffold; no working application implementation yet |
| 🌊 **OS5** | Fault-tolerant smart-city node: water level, power, local decisions, and event delivery after connectivity returns | ✅ Educational simulation available; [project README](OS5/README.md) |

The OS1–OS5 names and scenarios reflect the team mini-projects described in the
course materials. The status above describes what is actually present in the
repository: OS1, OS3, and OS4 currently contain only directory scaffolds, not
completed applications.

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

The **autonomous mobility node** is intended to process road conditions locally
at an intersection.

- **Input:** vehicle speeds and pedestrian counts at a crosswalk.
- **Goal:** demonstrate a local decision that can operate near the road without
  waiting for a remote server.
- **Intended output:** a recommendation or command for a variable speed-limit
  sign.
- **Status:** `OS3/` currently contains only a directory structure; its working
  logic has not yet been implemented.

### 🌫️ OS4 — IoT Edge Gateway

The **environmental monitoring gateway** is intended to collect air-quality and
noise measurements.

- **Input:** PM2.5 and equivalent noise-level readings.
- **Goal:** receive and process measurements on a local node.
- **Intended output:** a decision for a controlled device, such as a
  demonstration relay command.
- **Status:** `OS4/` currently contains only a directory structure; its working
  logic has not yet been implemented.

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
4. For **OS5**, start with the [OS5 README](OS5/README.md).
5. Do not use this code to control physical devices: sensors, receivers, and
   actuators in these demonstrations are software simulations.

### 🏷️ Status legend

- ✅ Project code and its own run instructions are available.
- 🧩 Only a scaffold is present; the application still needs to be implemented.
- 🎓 Educational demonstration — not an industrial system and not intended to
  control real-world equipment.
