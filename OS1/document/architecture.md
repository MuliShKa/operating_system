# OS1 – Smart Building Edge Gateway (Songdo Convensia)

Node `EDGE_NODE_OS1_CONVENSIA` · lat 37.3888, lon 126.6534

> **Mission:** sense, decide and act **locally**, and keep working when the Internet is down,
> **without losing a single event.**

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
| Involuntary switches / s | ~4 | **~12** |
| Sampling period | 2.0 s | 2.0 s |

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
       |                         |  -> 1202 events      |                   |
  ===== WAN RESTORED ======================================================= |
       |                         |   backlog            |                   |
       |                         |--------------------> |  batches of 50    |
       |                         |                      |-----------------> |
       |                         |                      |  drained 11.5 s   |
       |                         |                      |                   |
                              0 lost  -  0 duplicates
```

| Check | Result |
|---|---|
| Workers crashed or PID changed | none |
| Dashboard while offline | answering |
| Decisions made offline | 628 |
| Backlog / drain time | 1202 events / 11.5 s |
| Lost / duplicates | **0 / 0** |
