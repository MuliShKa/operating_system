# Songdo Edge Intelligence (송도 엣지 인텔리전스)

> **Status:** This file preserves the original course brief and target
> architecture. Some features below are planned goals, not current
> implementation. For accurate instructions for the integrated demo, see the
> repository [README](../README.md) and [demo integration guide](demo-integration.md).

## Inha University — Operating System (운영체제)
**Instructor**: Prof. Mehdi Pirahandeh  
**Platform**: Ubuntu 24.04 LTS | Python 3.12 | SQLite 3 (WAL Mode)  
**Semester Effort**: 7 Weeks | 5 Teams | 5 Students per Team  
**Project Mission**: *“Make Songdo compute locally and reliably.”* (송도가 로컬에서 신뢰성 있게 연산하도록 만든다.)  
**Signature Demonstration**: **“Disconnect Internet $\longrightarrow$ system continues operating.”**  

---

## 1. Project Mission & Non-Negotiable Boundaries

### What Students Deliver
- A multi-process edge computing service with explicit Linux processes (`SensorGen`, `Processor`, `HealthMon`, `API`).
- Robust Inter-Process Communication (IPC) via bounded queues (`maxsize=500`, `drop_oldest` policy) and Unix Domain Sockets.
- Local decision intelligence with monotonic clock command expiry TTLs ($t_{\text{mono}} + \Delta t$).
- ACID-compliant SQLite WAL persistence with an atomic, durable offline outbox.
- A stylish, zero-dependency offline web dashboard (`http://127.0.0.1:8000`) exposing live `/proc` metrics, PIDs, and outbox queues.
- Automated systemd user services (`songdo-edge@.service`) with restart limits and OCI container configurations (`Dockerfile`, `compose.yaml`).

### What Students Do NOT Deliver
- **No commercial cloud reliance**: Nodes must execute all primary control rules locally without requiring Internet connectivity.
- **No web frontend frameworks**: The local console uses native HTML/CSS/JavaScript served directly by Python's built-in `http.server` with zero external dependencies.
- **No ungrounded simulation**: Coordinates and context are grounded in Songdo International District using official Korean open data standards (Incheon Data Portal, KMA, AirKorea, VWorld, MEIS).

---

## 2. Team Allocations & Mini-Projects

| Team | Mini-Project Name | Target Location | Primary Sensors | Local Actuators | Open Data Benchmark |
| :---: | :--- | :--- | :--- | :--- | :--- |
| **OS1** | Smart Building Edge Gateway | Songdo Convensia Hall 3 | `OCCUPANCY_PIR`, `INDOOR_CO2_PPM` | `HVAC_DAMPER_PCT` | VWorld Facility Spatial Info (`LT_P_DGPRT`) |
| **OS2** | Robot Edge Controller | Central Park Pathway 2 | `LIDAR_PROXIMITY_M`, `IMU_YAW_RATE` | `SAFETY_ESTOP_LATCH`, `MOTOR_VEL` | Songdo Central Park Pathway Geometries |
| **OS3** | Autonomous Mobility Edge Node | Techno-Park Intersection | `RADAR_SPEED`, `PED_CROSSWALK_COUNT` | `VARIABLE_SPEED_SIGN_KMH` | Incheon BIS Bus Stop Sequences (`15048265`) |
| **OS4** | IoT Edge Gateway | Techno-Strip Tower | `PM25_UG_M3`, `NOISE_LEQ_DBA` | `MIST_CANNON_RELAY` | AirKorea Ambient Air Quality (`15073861`) |
| **OS5** | Fault-Tolerant Smart-City Node | Waterfront Lake Sluice | `SLUICE_WATER_LEVEL_M`, `MAINS_VOLT` | `BACKUP_SLUICE_GATE_OPEN` | MEIS Coastal Oceanographic Station |

---

## 3. Quickstart: The First 90 Minutes

Follow this path to verify your local environment and run the full pipeline:

### Step 1: Preflight Audit (Minutes 0–15)
```bash
cd scripts
bash preflight.sh
```
Checks Linux kernel version, active shell, Python 3.12 or 3.14, SQLite3, and required POSIX utilities (`ps`, `pkill`, `awk`, `sed`, `flock`, `curl`).

### Step 2: Virtual Environment & Database Setup (Minutes 15–30)
```bash
bash setup.sh
```
Creates `.venv`, installs dependencies (`psutil`, `pyyaml`), applies `sql/schema.sql`, and enables WAL mode.

### Step 3: Run the Automated OS Concurrency Suite (Minutes 30–45)
```bash
python tests/test_os_fundamentals.py
```
Verifies:
1. SQLite WAL mode & atomic outbox enqueue.
2. Bounded queue backpressure (`drop_oldest` policy under load).
3. Classic race condition demonstration and Mutex resolution.
4. Deadlock detection with timeout recovery.
5. Online SQLite database backup integrity check.

### Step 4: Run the OS5 Validation Suite (Minutes 45–60)
```bash
python scenarios/run_all_scenarios.py
```
Discovers and runs OS5 unit and integration tests, including worker recovery,
backup integrity, and the compound WAN/Processor failure scenario. The other
teams' scenarios are outside this repository's current OS5 implementation.

### Step 5: Launch the Signature Offline Demo & Local UI (Minutes 60–90)
```bash
bash scripts/start_demo.sh OS1
```
1. Open your browser at `http://127.0.0.1:8000`.
2. Inspect live PIDs, CPU%, RSS memory, and ingested sensor events.
3. Click **Simulate WAN Internet Cut**:
   - The badge transitions to **WAN: OFFLINE (DISCONNECTED)**.
   - Sensor events, local decision logic, and actuator commands continue executing uninterrupted.
   - The **Outbox Queued** counter increments while local operations proceed normally.
4. Click **Restore WAN Connection**:
   - The queued outbox backlog drains cleanly to the upstream sink with zero lost events.

---

## 4. File Layout

```
Songdo_Edge_Intelligence/
├── config/
│   └── node.yaml                       # Master configuration (teams, network, IPC, geography)
├── container/
│   ├── Dockerfile                      # Non-root Ubuntu 24.04 container definition
│   └── compose.yaml                    # OCI compose file with CPU/RAM cgroup limits
├── data/
│   ├── backups/                        # Safe online SQLite backups
│   └── songdo_edge.db                  # Local edge SQLite database (WAL mode)
├── docs/handbook/                      # XeLaTeX handbook source files
├── integration/                        # Mock upstream consumers
├── scenarios/
│   └── run_all_scenarios.py            # OS5 unit and integration scenario runner
├── scripts/
│   ├── preflight.sh                    # System environment audit
│   ├── setup.sh                        # Environment initializer
│   └── start_demo.sh                   # Multi-process supervisor and web launcher
├── sources/
│   └── source_registry.csv             # Korean open data registry (Incheon, KMA, AirKorea, VWorld, MEIS)
├── sql/
│   └── schema.sql                      # Complete SQLite DDL (WAL, nodes, events, decisions, outbox)
├── src/
│   ├── edge/
│   │   ├── api_server.py               # Zero-dependency local HTTP API server
│   │   ├── decision.py                 # Local rule-based and compact inference engines
│   │   ├── ipc.py                      # BoundedQueue, UnixSocket, SharedMemory primitives
│   │   ├── models.py                   # SensorEvent, EdgeDecision, ProcessHealth dataclasses
│   │   ├── storage.py                  # Thread-safe SQLite manager & online backup
│   │   ├── supervisor.py               # Multi-process supervisor managing worker lifecycles
│   │   └── sync_worker.py              # Durable offline outbox synchronizer
│   └── ui/static/
│       └── index.html                  # Styled responsive local edge console
├── systemd/
│   └── songdo-edge@.service            # Systemd user service unit template
├── tests/
│   └── test_os_fundamentals.py         # Automated OS concurrency and durability test suite
├── requirements.txt                    # Python dependencies
├── Songdo_Edge_Intelligence_Handbook.pdf # Compiled 11-page publication-grade handbook
└── README.md                           # This document
```

---

## 5. Seven-Week Implementation Roadmap

```
W1: Linux Platform, Git, Virtualenv & Multi-Process Skeleton
W2: Multi-Process IPC, Bounded Buffering & Concurrency Race Invariant Testing
W3: Local SQLite WAL Persistence, Atomic Batching & Durable Offline Outbox
W4: Local Rule Processing, Compact ML Inference & Monotonic Command Expiry
W5: Process Supervision, systemd Units, Timers & Flocked Maintenance
W6: Signature 10-Minute Offline Demonstration & Event Conservation Verification
W7: Final 25-Scenario Defense, Code Audit & Systems Handbook Submission
```

---

## 6. Evaluation & Grading (100 Points)

1. **OS Concepts, Processes & IPC Architecture (20 Pts)**: Clean multi-process roles, bounded queues, and zombie-free termination.
2. **Synchronization & Data Correctness (15 Pts)**: Race condition demonstration vs. Mutex resolution, deadlock prevention, and SQLite WAL durability.
3. **Executable Python/Shell Implementation (15 Pts)**: Runnable Bash ladder, rule-based decision engine, and monotonic command TTLs.
4. **Supervision, Schedulers & Containers (15 Pts)**: systemd user units, flocked backups, and container health checks.
5. **Signature Offline Demonstration (10 Pts)**: 10-minute WAN disconnect test with complete event conservation.
6. **Local Web Console Usability (5 Pts)**: Responsive dashboard displaying live PIDs, memory, and outbox queues.
7. **Individual Technical Defense (20 Pts)**: Oral defense of virtual memory, context switches, locks, signals, and offline edge fault models.

---

## 7. My Work: Environment and Processes

I work on two parts of the OS5 project: preparing the program to start and
managing its worker processes. The goal is that the node can run locally and
stop cleanly when the computer is shutting down.

### Environment and Startup

The startup scripts are in `scripts/`:

- `preflight.sh` checks that the computer uses Linux and has Bash, Python 3.12
   or 3.14, SQLite, and the command-line tools used by the project. It reports
   missing tools before stopping.
- `setup.sh` creates the Python virtual environment in `.venv` and installs the
   packages from `requirements.txt`. It creates `data/os5.db`, runs
   `sql/schema.sql`, turns on SQLite WAL mode, and checks that WAL is active.
- `start_demo.sh` runs the preflight check. If `.venv` is missing, it runs the
   setup script. Then it starts `src/edge/supervisor.py` in the foreground. The
   terminal shows the dashboard address, `http://127.0.0.1:8000`.

The usual command on Linux is:

```bash
bash scripts/start_demo.sh
```

The scripts are for Linux, so I should run them in Ubuntu or WSL, not directly
in a normal Windows PowerShell window.

The current setup applies the checked-in `sql/schema.sql` and verifies that
SQLite WAL mode is active. The six demo workers share the supervisor-created
IPC channels; the outbox synchronizes to a local idempotent receiver whenever
WAN is online.

### Processes and Restart

The supervisor is in `src/edge/supervisor.py`. It starts six named processes:
`SensorGen`, `Processor`, `HealthMon`, `API`, `Receiver`, and `SyncWorker`.

- Workers share the bounded sensor queue and stop/WAN events created by the
  supervisor.
- SIGINT (Ctrl+C) and SIGTERM request shutdown; workers are joined, terminated,
  or killed using bounded waits.
- If a worker exits unexpectedly, the supervisor records its exit code and
  restarts only that worker, reusing the existing IPC channels.
- A worker may restart at most three times in a 60-second window. If it keeps
  failing, the supervisor stops the remaining workers and returns an error.

The worker processes are integrated with the sensor pipeline, health monitor,
API, receiver, and sync worker. Unexpected worker exits trigger a bounded
restart of only the failed process; systemd-level restart behavior remains a
separate deployment concern.

### What I Checked

The OS5 scenario runner completed with 43 tests passing on WSL Debian with
Python 3.13.5. The preflight accepts Python 3.12 or 3.14, neither of which was
installed in that environment; repeat the run on a supported interpreter to
verify that runtime matrix. The runner is `python3 scenarios/run_all_scenarios.py`.

### How to Switch Between My Branches

Each task has a separate local branch:

```powershell
git switch feature/environment-startup
git switch feature/process-restart
```

The commits are local and have not been pushed to the remote repository.
