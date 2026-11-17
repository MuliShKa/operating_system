# OS1 – Smart Building Edge Gateway (Songdo Convensia)

> **Mission:** sense, decide and act **locally**, and keep working when the Internet is down, **without losing a single event.**

## Source layout

One folder per scenario, plus `core/` for what they all share.

```
src/edge/
├── supervisor.py          starts the 8 worker processes, stops and joins them
├── node_config.py         reads config/node.yaml (sensors, rule, ports)
│
├── core/                  shared by every scenario
│   ├── models.py          SensorEvent, ActuatorCommand
│   ├── bounded_queue.py   fixed-size queue between processes (drop oldest)
│   ├── ipc.py             the 2 queues + the stop / wan_online flags
│   ├── storage.py         SQLite in WAL mode, event + outbox in one transaction
│   ├── api_server.py      local dashboard and /api/status
│   └── backup.py          online backup (run by the systemd timer)
│
├── os1_1_ingestion/       OS1-1  sensors + cached building inventory
│   ├── sensors.py         SensorGen: CO2 and temperature, 1 reading/s each
│   ├── processor.py       stores each reading, tagged with the building
│   ├── inventory.py       raw file descriptors, ray casting
│   └── vworld_fetch.py    optional download of real VWorld data
│
├── os1_2_race/            OS1-2  race condition vs mutex
│   ├── shared_counter.py  counter in shared memory, with / without lock
│   └── occupancy.py       80 turnstile processes
│
├── os1_3_ventilation/     OS1-3  CO2 rule + command expiry
│   ├── decision.py        CO2 > 1000 ppm -> damper 100 %, expires 15 s after the reading
│   └── actuator.py        applies or rejects the command (monotonic clock)
│
├── os1_4_contention/      OS1-4  /proc profiling
│   ├── proc_stats.py      parses /proc/[pid]/stat and /status
│   └── proc_sampler.py    samples every worker every 2.0 s
│
├── os1_5_wan_outage/      OS1-5  Internet cut
│   ├── sync_worker.py     sends the outbox only while the WAN is up
│   └── receiver.py        mock upstream server, ignores duplicate event IDs
│
└── os1_bonus_trends/      BONUS  resource trends + comparison + CSV export
    └── history.py         rates over time, before/after averages, CSV manifest
```

---

## 1. OS1-1 – Sensor ingestion & cached building inventory

**Expected:** ingest indoor CO2 (ppm) and room temperature (°C) and match the node against cached VWorld building geometry, so every reading belongs to a known building.

**OS concepts:** file descriptors, user/kernel copy, offline-first data.

```
   USER SPACE (node process)                 KERNEL
  +--------------------------+          +------------------------+
  | open("buildings.geojson")| -------> | open-file table        |
  |   <- fd = 3              | <------- |  fd 3 -> the file      |
  |                          |          |                        |
  | read(fd 3)  (loop)       | -------> | copy bytes             |
  |   <- bytes in user memory| <------- | kernel -> user memory  |
  |                          |          |                        |
  | close(fd 3)  in finally  | -------> | free the slot          |
  +------------+-------------+          +------------------------+
               |                          (no fd leak, even on error)
               v
  +--------------------------+     +-----------------------------------+
  | parse the buildings      | --> | is the node's point inside a      |
  | (polygons)               |     | footprint?  (ray casting)         |
  +--------------------------+     +-----------------+-----------------+
                                                     | yes
                                                     v
                                   +-----------------------------------+
                                   | building = FIXTURE-CONVENSIA      |
                                   | every CO2 / temperature reading   |
                                   | is tagged with this building      |
                                   +-----------------------------------+
```

The node never calls an online map at runtime: it works from a **local cache**.
*The cache is a labelled fixture: the VWorld account needs a Korean identity check that failed.*

**Result:** 6/6 checks · 11 CO2 + 11 temperature readings, all tagged with the building.

**Code:**

| What | File | Function |
|---|---|---|
| Read the file with a raw fd (`os.open` / `os.read` / `os.close`) | [`inventory.py`](../src/edge/os1_1_ingestion/inventory.py#L32) | `read_file_with_fd` |
| Parse GeoJSON buildings | [`inventory.py`](../src/edge/os1_1_ingestion/inventory.py#L58) | `parse_buildings` |
| Ray casting: point inside polygon | [`inventory.py`](../src/edge/os1_1_ingestion/inventory.py#L91) | `point_in_ring`, `find_building` |
| Cache or fixture, store in SQLite | [`inventory.py`](../src/edge/os1_1_ingestion/inventory.py#L136) | `load_inventory`, `save_inventory` |
| Loaded once at startup | [`supervisor.py`](../src/edge/supervisor.py#L62) | `main` |
| Readings generated (CO2, temperature) | [`sensors.py`](../src/edge/os1_1_ingestion/sensors.py#L10) | `run_sensors` |
| Each reading tagged with `building_id` | [`processor.py`](../src/edge/os1_1_ingestion/processor.py#L21) | `run_processor` |
| Node coordinates, sensors, cache path | [`node.yaml`](../config/node.yaml) |  |
| The fixture file (labelled, not VWorld) | [`os1_convensia_buildings.fixture.geojson`](../sources/vworld/os1_convensia_buildings.fixture.geojson) |  |
| Table `building_inventory` | [`schema.sql`](../sql/schema.sql#L50) |  |
| Scenario / tests | [`os1_1_ingestion.py`](../scenarios/os1_1_ingestion.py) · [`test_os1_1_inventory.py`](../tests/test_os1_1_inventory.py) |  |

---

## 2. OS1-2 – Race condition on the occupancy counter

**Expected:** prove that concurrent turnstile counts get corrupted without protection (80 increments → counter < 80), then fix it with a mutex (counter = 80).

**OS concepts:** shared memory, preemption, critical section, mutex.

80 turnstile processes each add **+1** to the same counter in shared memory.

```
  WITHOUT A LOCK                              counter
  ---------------------------------------------------
  Turnstile A          Turnstile B
  read  -> 5                                     5
                       read  -> 5                5
  write 5+1 = 6                                  6
                       write 5+1 = 6             6
  ---------------------------------------------------
  2 people entered, counter only +1  ->  ONE UPDATE LOST


  WITH A MUTEX                                counter
  ---------------------------------------------------
  Turnstile A          Turnstile B
  lock                                           6
  read 6, write 7      lock -> WAITS             7
  unlock               ...                       7
                       lock acquired             7
                       read 7, write 8           8
                       unlock                    8
  ---------------------------------------------------
  2 people entered, counter +2  ->  correct
```

| 5 trials | Final counter (expected 80) |
|---|---|
| No lock | **14 – 20** |
| Mutex | **80 every time** |

All 80 processes joined, exit code 0.

**Code:**

| What | File | Function |
|---|---|---|
| Counter in shared memory (`RawValue`) + lock | [`shared_counter.py`](../src/edge/os1_2_race/shared_counter.py#L6) | `SharedCounter` |
| Protected increment (mutex) | [`shared_counter.py`](../src/edge/os1_2_race/shared_counter.py#L16) | `increment` |
| Unprotected read → pause → write | [`shared_counter.py`](../src/edge/os1_2_race/shared_counter.py#L26) | `unsafe_increment` |
| 80 turnstile processes, Barrier start, join | [`occupancy.py`](../src/edge/os1_2_race/occupancy.py#L34) | `count_entries`, `turnstile` |
| Scenario / tests | [`os1_2_race.py`](../scenarios/os1_2_race.py) · [`test_os1_2_race.py`](../tests/test_os1_2_race.py) |  |

---

## 3. OS1-3 – Ventilation rule & command expiry (TTL)

**Expected:** when CO2 goes above 1000 ppm, open the damper to 100 %, and never apply a command older than its 15.0 s lifetime.

**OS concepts:** monotonic clock, stale command rejection, producer/consumer.

```
  +--------------------+
  | CO2 reading        |
  | + monotonic time t |
  +---------+----------+
            v
     +--------------+    no     +-------------+
     | CO2 > 1000 ? | --------> | no command  |
     +------+-------+           +-------------+
            | yes
            v
  +----------------------------+
  | command: damper 100 %      |
  | expires at t + 15.0 s      |
  +------------+---------------+
               |  commands queue
               v
  +----------------------------+   yes   +------------------+
  | Actuator, just before      | ------> | DAMPER_APPLIED   |
  | acting: still before       |         +------------------+
  | the expiry?                |   no    +------------------+
  |                            | ------> | COMMAND_EXPIRED  |
  +----------------------------+         | damper not moved |
                                         +------------------+

  Timeline of one command (monotonic clock, seconds after the reading)

  0 s                                 14.9 s  15.0 s  15.1 s
  |-----------------------------------|-------|-------|------->
  reading           VALID                   expiry    EXPIRED
```

Why **monotonic**? The wall clock can jump (NTP, manual change); the monotonic clock
**only goes forward**, so a stale command can never look fresh.

| Test | Result |
|---|---|
| 999.9 / 1000 / 1000.1 ppm | no / no / **yes** |
| Command at 14.9 s / 15.1 s | valid / **expired** |
| Normal actuator | 7 commands applied |
| Actuator slowed by 16 s | every command rejected, damper never moved |

11/11 checks.

**Code:**

| What | File | Function |
|---|---|---|
| Rule (threshold, action, TTL 15.0 s) | [`node.yaml`](../config/node.yaml#L14) | `rule:` |
| Reading stamped with `time.monotonic()` | [`sensors.py`](../src/edge/os1_1_ingestion/sensors.py#L12) | `run_sensors` |
| CO2 > 1000 → command, expiry = reading + 15 s | [`decision.py`](../src/edge/os1_3_ventilation/decision.py#L13) | `make_command` |
| Expiry check | [`decision.py`](../src/edge/os1_3_ventilation/decision.py#L31) | `is_expired` |
| Command sent on the `commands` queue | [`processor.py`](../src/edge/os1_1_ingestion/processor.py#L43) | `run_processor` |
| Actuator: check just before acting → APPLIED / EXPIRED | [`actuator.py`](../src/edge/os1_3_ventilation/actuator.py#L16) | `check_command`, `run_actuator` |
| Bounded queues (`sensor_events`, `commands`) | [`ipc.py`](../src/edge/core/ipc.py#L7) | `IpcChannels` |
| Scenario / tests | [`os1_3_ventilation.py`](../scenarios/os1_3_ventilation.py) · [`test_os1_3_ventilation.py`](../tests/test_os1_3_ventilation.py) |  |

---

## 4. OS1-4 – Process profiling under load

**Expected:** measure memory (RSS) and context switches of every process under synthetic load, sampled from `/proc/[pid]/stat` into `process_health` every 2.0 s.

**OS concepts:** `/proc` filesystem, RSS, voluntary vs involuntary context switches.

```
  +---------------+   /proc/<pid>/stat     +----------------+     +------------------+
  |  Linux kernel | ---------------------> |  ProcSampler   | --> |  process_health  |
  |               |   /proc/<pid>/status   |  every 2.0 s   |     |  1 row / worker  |
  +---------------+                        +----------------+     +------------------+
                                                                    CPU %, RSS memory,
                                                                    context switches


  Context switches: why a process leaves the CPU

                          scheduler picks it
          +-----------+ <------------------- +--------------+
          |  RUNNING  |                      | READY queue  |
          |  on CPU   | -------------------> |              |
          +-----+-----+   INVOLUNTARY:       +--------------+
                |         time slice over,          ^
                |         kernel takes the CPU      |
                |                                   | data arrived /
                | VOLUNTARY: waits for data,        | sleep over
                | sleeps, blocks on I/O             |
                v                                   |
          +-----------+                             |
          |  WAITING  | ----------------------------+
          +-----------+
```

Experiment: 30 s idle, then 30 s with 28 CPU-burner processes.

| Processor worker | Idle | Under load |
|---|---|---|
| Involuntary switches / s | ~2 | **~14** |
| Voluntary switches / s (waits for a reading) | ~37 | ~26 |
| Sampling period | 2.0 s | 2.0 s |

**Code:**

| What | File | Function |
|---|---|---|
| Parse `/proc/[pid]/stat` (CPU ticks, RSS) | [`proc_stats.py`](../src/edge/os1_4_contention/proc_stats.py#L13) | `parse_stat` |
| Parse `/proc/[pid]/status` (context switches) | [`proc_stats.py`](../src/edge/os1_4_contention/proc_stats.py#L27) | `parse_context_switches` |
| Read one process | [`proc_stats.py`](../src/edge/os1_4_contention/proc_stats.py#L38) | `read_process` |
| Sample every worker, write `process_health` | [`proc_sampler.py`](../src/edge/os1_4_contention/proc_sampler.py#L12) | `sample_once` |
| Fixed 2.0 s monotonic schedule, CPU % | [`proc_sampler.py`](../src/edge/os1_4_contention/proc_sampler.py#L28) | `run_proc_sampler` |
| Table `process_health` | [`schema.sql`](../sql/schema.sql#L23) |  |
| Scenario (idle + CPU burners) / tests | [`os1_4_contention.py`](../scenarios/os1_4_contention.py) · [`test_os1_4_proc_stats.py`](../tests/test_os1_4_proc_stats.py) |  |

---

## 5. OS1-5 – Signature WAN outage (10 minutes)

**Expected:** cut the WAN for 10 minutes, watch events pile up in the outbox, then reconnect and check that the whole backlog drains with zero loss and no duplicates.

**OS concepts:** durable outbox, store-and-forward, idempotent delivery.

```
  Sensors + rule        Local SQLite + outbox       SyncWorker          Receiver
       |                         |                      |                   |
  ===== WAN ONLINE ======================================================== |
       |  event + outbox row     |                      |                   |
       |  (same transaction)     |                      |                   |
       |-----------------------> |   pending rows       |                   |
       |                         |--------------------> |   batch           |
       |                         |                      |-----------------> |
       |                         |                      |  stored (dupes    |
       |                         |                      | <-----------------|
       |                         |                      |   ignored)        |
  ===== WAN CUT - 10 MINUTES =============================================== |
       |  readings + decisions   |                      |                   |
       |  continue               |                      |    nothing sent   |
       |-----------------------> |                      |  ---X             |
       |                         |  outbox grows        |                   |
       |                         |  -> 1200 events      |                   |
  ===== WAN RESTORED ======================================================= |
       |                         |   backlog            |                   |
       |                         |--------------------> |  batches of 50    |
       |                         |                      |-----------------> |
       |                         |                      |  drained 9.5 s    |
       |                         |                      |                   |
                              0 lost  -  0 duplicates
```

| Check | Result |
|---|---|
| Workers crashed or PID changed | none |
| Dashboard while offline | answering |
| Decisions made offline | 598 |
| Backlog / drain time | 1200 events / 9.5 s |
| Lost / duplicates | **0 / 0** |

**Code:**

| What | File | Function |
|---|---|---|
| Event + outbox row in ONE transaction | [`storage.py`](../src/edge/core/storage.py#L37) | `save_event` |
| SQLite WAL mode + busy timeout | [`storage.py`](../src/edge/core/storage.py#L15) | `connect`, `initialize_database` |
| Tables `events`, `outbox` | [`schema.sql`](../sql/schema.sql#L6) |  |
| WAN flag (starts online) | [`ipc.py`](../src/edge/core/ipc.py#L25) | `IpcChannels` |
| Dashboard buttons cut / restore the WAN | [`api_server.py`](../src/edge/core/api_server.py#L55) | `do_POST` |
| Sends batches of 50 only while the WAN is up | [`sync_worker.py`](../src/edge/os1_5_wan_outage/sync_worker.py#L25) | `run_sync_worker` |
| Receiver: `INSERT OR IGNORE` on event ID → no duplicate | [`receiver.py`](../src/edge/os1_5_wan_outage/receiver.py#L26) | `accept_event` |
| Scenario (cut, drain, conservation check) / tests | [`os1_5_wan_outage.py`](../scenarios/os1_5_wan_outage.py) · [`test_os1_5_outage.py`](../tests/test_os1_5_outage.py) |  |

---

## Bonus – Resource trends & historical comparison

**Expected:** (assessment, Phase 3 / Optional) add historical comparisons and resource trends, so that the **plotted metrics agree with the exported manifest**.

**OS concepts:** `/proc` counters turned into rates over time, time windows, one source of truth for the chart and the export.

```
  +---------------+  /proc every 2.0 s   +----------------+     +------------------+
  |  Linux kernel | -------------------> |  ProcSampler   | --> |  process_health  |
  +---------------+   (from OS1-4)       +----------------+     |  (SQLite)        |
                                                                +--------+---------+
                                                                         |
                                                                         v
                                          +-------------------------------------------+
                                          | history.build_history()                   |
                                          |  two consecutive samples -> one rate      |
                                          |  CPU %, RSS, voluntary / involuntary /s   |
                                          |  averages: previous window vs last window |
                                          +---------------------+---------------------+
                                                                |  same data
                                    +---------------------------+---------------------------+
                                    v                                                       v
                     +------------------------------+                    +------------------------------+
                     | GET /api/history             |                    | GET /api/history.csv         |
                     | -> dashboard chart + table   |                    | -> exported manifest (file)  |
                     +--------------+---------------+                    +--------------+---------------+
                                    |                                                   |
                                    +-------------------> equal ? <---------------------+
                                                       (checked by the scenario)


  Trend of one worker (involuntary switches / s)

     ^
  12 |                                   ___/\___/\____
     |                                  /
   4 |  ____/\_____/\____/\____________/
     +-----------------------------------+------------------> time
                 idle (30 s)             :     CPU load (30 s)
                                       split
```

A rate needs **two readings** of a counter: no point is drawn across a PID change
(a restarted worker starts its counters again from 0).

| Check | Result |
|---|---|
| Every worker has a trend | 8 / 8 |
| Plotted metrics == exported CSV manifest | **identical** |
| Comparison: more involuntary switches under load | yes (Processor 3.8 → 12.5 /s) |

Experiment: 30 s idle, then 30 s with 28 CPU-burner processes; 232 points plotted and exported.

| Worker (top 4) | Involuntary switches / s, idle | Under load |
|---|---|---|
| ProcSampler | 7.14 | **19.35** |
| Processor | 3.82 | **12.51** |
| SyncWorker | 3.54 | **10.29** |
| Actuator | 0.43 | **1.84** |

Chart: [`os1_bonus_trends.svg`](results/os1_bonus_trends.svg) · manifest: [`os1_bonus_trends.csv`](results/os1_bonus_trends.csv)

**Code:**

| What | File | Function |
|---|---|---|
| Read the samples of a time range | [`history.py`](../src/edge/os1_bonus_trends/history.py#L20) | `load_samples` |
| Two samples → one point (rates), skip PID changes | [`history.py`](../src/edge/os1_bonus_trends/history.py#L31) | `build_trends` |
| Previous window vs last window | [`history.py`](../src/edge/os1_bonus_trends/history.py#L63) | `compare`, `build_history` |
| Export / read back the CSV manifest | [`history.py`](../src/edge/os1_bonus_trends/history.py#L87) | `to_csv`, `read_csv` |
| API routes `/api/history` and `/api/history.csv` | [`api_server.py`](../src/edge/core/api_server.py#L40) | `history_from_query`, `do_GET` |
| Dashboard card: chart, comparison, Export CSV | [`index.html`](../src/ui/static/index.html#L189) | `drawChart`, `showComparison` |
| Samples written every 2.0 s (from OS1-4) | [`proc_sampler.py`](../src/edge/os1_4_contention/proc_sampler.py#L12) | `sample_once` |
| Scenario (idle, load, manifest check, SVG) / tests | [`os1_bonus_trends.py`](../scenarios/os1_bonus_trends.py) · [`test_os1_bonus_trends.py`](../tests/test_os1_bonus_trends.py) |  |
