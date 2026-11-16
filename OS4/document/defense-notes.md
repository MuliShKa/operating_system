# OS4 — oral defense preparation

Purpose: you wrote (with help) a lot of code. In the defense you must explain **what each part does,
why it is built that way, and what its limits are**. This file is organised the way a professor asks:
first the big picture, then each scenario, then the OS concepts, then the hard questions.

Rule for yourself: never say a thing works unless you ran it. Everything below was run (see
`document/results/`), except the items listed in section 7 ("Not verified").

---

## 1. The 60-second pitch

"OS4 is the IoT gateway on the Techno-Strip Tower. Three sensors (PM2.5, noise, light) with different
rates and message formats send readings over Unix sockets to **one** Ingest process that waits in epoll.
A Processor stores every reading in SQLite with **two timestamps** (when the sensor measured it, when we
received it), applies a local rule — PM2.5 above 50 µg/m³ switches the mist cannon relay on for 30 s — and
puts every event in a durable outbox. An Actuator is the only process that moves the relay, and it
re-checks that the command is still fresh. If the internet is cut, nothing stops: the outbox grows, and
when the link returns it drains, the receiver ignores duplicates, and 100 % of events are acknowledged.
Eight processes run under a supervisor; backups run on a timer under `flock`. We added two scenarios:
sensor-fault protection (a hung or frozen sensor can never keep the pump running) and a quiet-night
policy (the loud pump stays off at night for ordinary dust)."

---

## 2. Read the code in this order (about 40 minutes)

| # | File | One-sentence meaning |
|---|---|---|
| 1 | `config/node.yaml`, `config.py` | Every number, with "handbook" vs "team decision" labels. |
| 2 | `sensors.py` | The three devices: units, periods, three wire formats, encoders/parsers, range checks. |
| 3 | `sensor_gen.py` | The simulated devices: jitter, delayed delivery (heap), episode / night / fault switches. |
| 4 | `ingest.py` | **Core of OS4-1.** Bind 3 non-blocking sockets, `selector.select()`, drain each, validate, stamp receipt time. |
| 5 | `models.py` | `SensorEvent` carries both clocks plus a monotonic conversion. |
| 6 | `bounded_queue.py`, `shared_counter.py` | Drop-oldest queue and its lock-protected counters (team code, reused). |
| 7 | `processor.py` | **Core of OS4-2/6/7.** `StreamProcessor.handle_event` top to bottom. |
| 8 | `decision.py` | The pure rule: NONE / DISPATCH / HOLD, TTL from event time. |
| 9 | `guard.py` | STALE / STUCK detection with monotonic time. |
| 10 | `actuator.py` | **Core of OS4-3.** Freshness check, version-guarded relay, TTL switch-off, fail-safe start/stop. |
| 11 | `storage.py`, `sql/schema.sql` | Transactions, WAL, outbox, relay compare-and-swap. |
| 12 | `sync_worker.py`, `receiver.py` | Store-and-forward and idempotent receiver (team code, reused). |
| 13 | `backup.py`, `scripts/backup.sh` | **Core of OS4-4.** Online backup API + `flock`. |
| 14 | `baseline.py` | **Core of OS4-5 benchmark.** Cached AirKorea file, grades, comparison. |
| 15 | `supervisor.py`, `health.py`, `api_server.py` | Lifecycle, health metrics, dashboard. |

Reused from the team's OS3 (understand them, they are asked about too): `bounded_queue.py`,
`shared_counter.py`, `race_demo.py`, `deadlock_demo.py`, `receiver.py`, `sync_worker.py`, `backup.py`,
the supervisor pattern, the scripts and unit templates. New in OS4: everything about sockets/epoll,
two clocks, the relay, channel health, the night policy, the baseline.

---

## 3. Scenario by scenario: what to show and what to say

### OS4-1 Heterogeneous multi-stream ingestion
*Demo:* `python3 scenarios/os4_1_ingestion.py --seconds 20`, then show the dashboard "Sensor Channels" table and, in a terminal, `ls -l /proc/<Ingest pid>/fd` (an `eventpoll` entry) and `ss -xlp | grep songdo`.

*What to say:* The three devices differ in rate (2 s / 1 s / 5 s), unit and **text format** (JSON, CSV, key=value), so each has its own parser (`sensors.py`). They send datagrams to three Unix socket files. Ingest registers the three sockets with one `selectors.DefaultSelector` (epoll on Linux), sleeps in `select()`, and when woken reads each ready socket until it would block (`BlockingIOError`). 

*Why this design (expect "why not threads / why not a loop?"):*
- A loop that polls each socket in turn either blocks on a quiet sensor (blocking read) or burns CPU (busy wait). epoll lets the kernel wake us only when data exists: measured CPU of Ingest was 0.02 s over 20 s.
- One thread per sensor works but costs three stacks, needs locks around the shared queue, and the GIL gives no parallel speed-up for this I/O-bound job.
- Fairness: `MAX_PER_WAKEUP = 64` stops a chatty sensor starving the others.
- Datagram (not stream) sockets: each reading is one message, so no framing code; if a sensor dies there is no connection state to clean up.
- Socket directory is `chmod 700` so only our user's processes can feed the gateway.

### OS4-2 Event time vs receipt time
*Demo:* `python3 scenarios/os4_2_event_time.py` (about 90 s) and the dashboard "Recent Readings" table: observed vs received, lateness, "OUT OF ORDER".

*What to say:* Remote sensor nodes deliver late and out of order. The sensor's timestamp (`observed_at`, event time) is the truth about the physical world; our clock (`received_at`) only says when we heard. We store both in separate columns and never overwrite the first. Rules must follow event time:
- Per sensor we keep the newest reading *by event time*. A reading older than that is **stored** (the platform needs complete history) but **cannot start or extend a spray**. Scenario: an old reading of 95 µg/m³ arriving late does not switch the pump on.
- The 30 s TTL is counted from event time: a reading that travelled 4 s gets 26 s of life, which the scenario measured (26.0 s).
- Wall clocks can jump (NTP, manual change), so deadlines use `time.monotonic()`. We convert once at arrival: `observed_mono = received_mono − (received_at − observed_at)`, and never look at a wall clock again. A device clock *ahead* of ours gives a negative age; we clamp it to 0.

### OS4-3 Dust suppression mist cannon relay
*Demo:* `python3 scenarios/os4_3_mist_relay.py` (about 1.5 min) or press "Dust episode" in the dashboard.

*What to say:* Rule: PM2.5 **> 50** (handbook) → `MIST_CANNON_RELAY` with a 30 s TTL. The Processor only *issues* commands; the Actuator is the only process that touches the relay, and right before acting it compares `expires_at` with **its own** `time.monotonic()` (valid across processes because on Linux `CLOCK_MONOTONIC` is system-wide). The relay stays ON only while fresh high readings keep renewing the command. When they stop, the Actuator switches OFF by itself 30 s after the last high reading (measured: 30.1 s). That is a **dead-man switch**: if the sensor dies, the Processor crashes, or the machine hangs, the pump stops. We also start OFF and stop OFF, so a relay left ON by a crashed run is never trusted.

*Trade-off to admit:* after the dust ends the pump runs up to 30 s more (the TTL), wasting some water. A hysteresis OFF command (e.g. below 40) would fix it but adds a rule the handbook does not ask for.

### OS4-4 Scheduled backup with flock
*Demo:* `python3 scenarios/os4_4_backup.py` and `systemctl --user list-timers` if installed.

*What to say:* `backup.py` uses SQLite's online backup API (`Connection.backup`), copying 256 pages at a time so the node's writers are never blocked for long; it runs `PRAGMA integrity_check` on the copy and renames it atomically (no half-written file is ever visible). `backup.sh` takes `flock -n` on file descriptor 9: if another backup holds the lock it exits 0 immediately instead of piling up. The kernel releases a `flock` when the process dies, so a SIGKILLed backup cannot leave a stale lock (the scenario kills one and runs again). The database is in WAL mode so readers and the writer do not block each other, and every connection sets `busy_timeout = 10000`. The timer is `Persistent=true`: a run missed while the machine was off happens at boot.

### OS4-5 WAN outage backlog drain and AirKorea benchmark
*Demo:* `python3 scenarios/os4_5_offline_demo.py --offline-seconds 60` (quick) or the official 600 s; or by hand: dashboard → cut WAN → watch "Pending Events" grow → restore → watch it fall to 0.

*What to say:* An event and its outbox row are inserted in **one transaction**, so there is no state where an event exists without being queued. SyncWorker sends while the WAN flag is set and marks a row `sent` only **after** the receiver confirmed that `event_id`. If the process dies between sending and marking, the event is sent again; the receiver has `event_id` as primary key and ignores the duplicate. At-least-once delivery plus an idempotent receiver is effectively exactly-once. The scenario proves it: 100 % of the events are acknowledged, none lost, none unknown to the node, and a replayed event is answered `duplicate=true` without changing the count.

*AirKorea:* `baseline.py` reads a **cached** hourly file for station 131233 (works offline), takes the median of the local PM2.5 readings of the last 60 s (median resists single spikes), finds the station value for that hour, and reports the bias, the Korean grade of each, and AGREE / DEVIATES against a 15 µg/m³ tolerance (team decision). Every row says whether the data is a SAMPLE.

*Be honest about this (they will ask):* until you save the real file, the benchmark runs on **synthetic** data, and the simulator's background PM2.5 is generated *around* that same baseline, so "AGREE" is expected and proves the **pipeline**, not the accuracy of a real sensor. The real value of the check appears with real station data and a real sensor.

### OS4-6 (extra) Sensor faults must never drive the pump
*Why we added it:* automation that sprays water because a broken sensor says "dust" is worse than none. It is also a natural fit for OS concepts: a hung device produces **no error and no EOF**, only silence, so health must be measured by time.
- Range check at the door (NaN, negative, > 1000 µg/m³) and malformed datagrams are counted, never stored.
- STALE: no datagram for 10 s (monotonic clock). STUCK: the same PM2.5 value 6 times in a row (checked on event-time order only; checked only for PM2.5, because a real light sensor legitimately reads 0 lux all night).
- Fail-safe: no command is issued from a STALE or STUCK channel; the relay then falls OFF by the TTL. The scenario shows both cases, recovery, and that the other channels keep working.

*Limit to admit:* real PM sensors often report integers, where six identical values at clean air are plausible; then "stuck" would give a harmless false alarm (the pump is merely not driven). We chose 6 and made it configurable.

### OS4-7 (extra) Quiet-night policy
*Why:* it gives the noise and illumination streams a real job (multi-sensor aggregation, as Table 1 of the handbook says) and models a real conflict: a high-pressure pump is loud. Dark (< 10 lux) **and** quiet (< 45 dB) → an ordinary Bad reading (50–75) is *held* and reported once (`MIST_HELD_QUIET_HOURS`); a Very Bad reading (> 75) overrides. Missing or stale context (older than 30 s) never blocks the action: we prefer to act for public health than to be silenced by a broken light sensor.

*Limit:* the thresholds 10 lux, 45 dB and 75 µg/m³ are team decisions, not data-driven. The simulator uses a switch, not the real clock, for "night", so the demo never depends on the hour of your presentation.

---

## 4. OS concepts: where each appears, in the words of the handbook rubric

| Rubric item | Where in OS4 | One-line answer |
|---|---|---|
| Processes, distinct roles | 8 processes in `supervisor.py` | Sensor, Ingest, Processor, Actuator, Health, UI, Sync, Receiver, each its own address space and PID. |
| Bounded queues and drop policy | `bounded_queue.py` (500) | Unbounded queue → memory grows → OOM killer. Bounded + drop-oldest keeps RSS capped and data fresh; drops are counted. |
| Unix domain sockets | `ingest.py`, `sensor_gen.py` | Local, kernel-only, framed datagrams, no network stack. |
| Shutdown / zombies | `supervisor.stop_processes` | `stop` Event → each worker leaves its loop → `join()` reaps it; `terminate()` only after 5 s. `ingest_done` lets the Processor drain before exit. |
| Signal handling | `supervisor.main` | SIGTERM/SIGINT only set a flag; the main loop reacts, so cleanup is never done inside a signal handler. |
| Race condition + mutex | `race_demo.py`, `shared_counter.py`, `test_os_fundamentals.py` | `counter = counter + 1` is load/add/store; 80 processes without a lock lose updates (< 80), with the lock exactly 80. In OS4 the lock protects the queue counters. |
| Deadlock | `deadlock_demo.py` | Opposite lock order deadlocks; bounded `acquire(timeout)` + release + random back-off recovers (random, to avoid livelock). |
| Compare-and-swap in SQL | `update_relay_state` | `UPDATE … WHERE version = ?` is atomic; a stale writer matches 0 rows, re-reads, decides again. |
| SQLite WAL + busy timeout | `storage.py` | Five processes write one file; WAL lets readers and the writer proceed; `busy_timeout` waits instead of failing. |
| Online backup, flock | `backup.py`, `backup.sh` | See OS4-4. |
| Monotonic TTL | `decision.py`, `actuator.py` | See OS4-2/3. |
| Context switches | `health.py`, dashboard | Voluntary = process gave up the CPU (waiting for I/O or a queue); involuntary = scheduler preempted it (CPU-bound work). On our node every worker is overwhelmingly voluntary, e.g. Processor 3758 vs 30. Read from `/proc/<pid>/status` via psutil. |
| Virtual memory | `bounded_queue`, systemd `MemoryMax=512M` | Each process has its own virtual address space; RSS is what is really resident. The limit is enforced by the cgroup, not by Python. |
| systemd, burst limits, cgroups | `systemd/songdo-edge@.service` | `Restart=on-failure`, `StartLimitBurst=5` in 60 s, `MemoryMax`, `CPUQuota`, `TasksMax`. |
| Container | `container/` | A container is a cgroup + namespaces around ordinary processes; it does no extra computation. The healthcheck requires the API to answer and all workers to be `running`. |
| Spawn vs fork | `supervisor.main` | `spawn` starts a clean interpreter: no inherited locks or threads, same behaviour on every OS. |

---

## 5. Decisions table (be ready to defend each one)

| Decision | Alternative | Why we chose it | Cost |
|---|---|---|---|
| Unix datagram sockets for sensors | `multiprocessing.Queue` / pipes | Decouples devices from the node by a file name; framing for free; inspectable with `ss`; handbook command ladder | Linux only; a datagram sent while the gateway is down is lost (the device would resend in real life) |
| `selectors` (epoll) | thread per sensor / `asyncio` | Simplest correct non-blocking multiplexing, no locks, visible in `/proc` | Single thread: a slow parser would delay all (parsers are microseconds) |
| Ingest only does I/O | Parse and decide in Ingest | Receipt time is stamped at the earliest moment; meaning lives in one place | One extra queue hop |
| Two timestamp columns | One `event_time` | Handbook OS4-2; lets you measure lateness and prove order | Slightly bigger rows |
| ISO-8601 UTC strings with microseconds | Epoch floats | Human-readable; fixed width so text order equals time order | Parsing needed for arithmetic |
| Late readings stored but inert | Drop them / let them act | Platform needs history; actuation must follow newest truth | A genuinely important late alarm cannot act (acceptable: it is already history) |
| TTL from event time | TTL from receipt | A reading that waited has already used part of its life | Needs the clock conversion |
| Dead-man TTL, no explicit OFF command | Hysteresis OFF | Fail-safe by construction, matches handbook | Up to 30 s extra spraying |
| Single relay writer + version guard | Anyone may write | One authority for hardware; CAS protects against future second writers | A little more code |
| Fail-safe start/stop OFF | Restore last state | A persisted ON is stale information | None |
| Outbox in the event's transaction | Send directly | No event without a queue entry; survives crashes | Disk write per event |
| Receiver dedup by `event_id` | Exactly-once protocol | Simple and robust | Receiver needs a unique index |
| Median for the benchmark | Mean | Robust to spikes and to the dust episodes | Needs ≥ 5 readings |
| Cached baseline file | Call AirKorea API live | Must work offline; API needs a key | Data can be old |
| Supervisor exits when a worker dies | Restart workers one by one | Same policy as OS3; systemd/Docker restart the whole node and state is in SQLite | A sensor crash restarts everything (about 3 s) |

---

## 6. Numbers you must be able to justify

| Number | Source | Justification |
|---|---|---|
| 50 µg/m³, 30 s, queue 500, 600 s offline | **Handbook** | Given. |
| Periods 2 s / 1 s / 5 s | Team decision | Different on purpose to make streams asynchronous; PM2.5 sensors are slow, noise is fast, light changes slowly. |
| Stale after 10 s / 5 s / 20 s | Team decision | 5 missed periods each. |
| Stuck after 6 identical readings | Team decision | 12 s of identical 0.1-resolution values is not natural noise. |
| Very Bad > 75 | Team decision | Upper edge of the Korean "Bad" band (see 7). |
| 10 lux, 45 dB | Team decision | Typical "dark" and "quiet street at night" levels; tune on site. |
| Context max age 30 s | Team decision | Same as the command TTL. |
| Baseline window 60 s, ≥ 5 readings, every 20 s, tolerance 15 µg/m³ | Team decision | Enough readings for a median; tolerance wide enough for sensor-vs-station distance. |
| `MemoryMax 512M`, `CPUQuota 150%`, `TasksMax 128` | Copied from OS3, handbook mentions 512M | Eight small processes use about 25 MB each. |

---

## 7. Things to flag yourself before the professor does

1. **Handbook threshold vs official grades.** The handbook says the mist cannon fires above 50 µg/m³ and calls it the Korean "Bad" threshold. As far as I recall, the official Korean PM2.5 bands are Good 0–15, Normal 16–35, Bad 36–75, Very Bad 76+, so "Bad" starts lower than 50. **Please verify this yourself** before quoting it. We implemented the handbook's 50 (configurable) and use 75 for the override.
2. **AirKorea data is synthetic** until the real file for station 131233 is saved as `sources/airkorea_131233_pm25.csv` (format in `sources/source_registry.csv`). The dashboard and every `baseline_checks` row say SAMPLE. A live API fetcher was not written because it needs a personal service key.
3. **Not verified in development:** the Docker image was not built and the systemd service was not started on a real systemd host (the unit files were checked with `systemd-analyze verify`, which only complained that `.venv` did not exist yet, and the compose file parses). Run them once on your Linux/WSL2 machine before the demo.
4. **The benchmark's "AGREE" is partly circular** (the simulator follows the same baseline). It validates the pipeline, not the sensor.
5. **Simulated delay is on one machine.** Event-time → monotonic conversion assumes the device clock and ours are comparable; with real remote nodes you would need clock-offset estimation (NTP/PTP) or accept the error.
6. **A datagram is lost if the gateway is down**; real devices would buffer or resend.
7. **No real hardware timer** on the relay: software TTL is a safeguard, not a certified safety system.
8. **The saved results come from a Linux sandbox**, not from your machine. Re-run `python3 scenarios/run_os4_scenarios.py` on the machine you will present from and replace `document/results/` with your own run.
9. **Quick vs official runs:** the 10-minute OS4-5 result must come from the default (600 s) run; `--quick` is a smoke test.

---

## 8. Hard questions and short answers

**Why is a Unix socket better than a pipe here?** It is addressable by name (several unrelated processes can connect, a device can restart), preserves message boundaries with datagrams, and shows up in `ss -xlp`. A pipe needs a common parent to hand out file descriptors.

**What happens if the Processor is slower than the sensors?** The bounded queue fills, the oldest item is dropped and counted in `dropped_count`; memory stays bounded. The dashboard shows queue size and drops.

**What if the Ingest process is killed?** The supervisor sees a dead worker and exits with code 1, systemd restarts the node (about 2 s + start-up). SQLite already holds everything stored; datagrams sent in between are lost.

**Why monotonic and not `time.time()`?** `time.time()` can jump backwards or forwards (NTP, manual change). A jump would make a stale command look fresh. `CLOCK_MONOTONIC` only moves forward, and on Linux it is shared by all processes.

**Why must the Actuator re-check freshness if the Processor already did?** The command can wait in a queue, or the Actuator can be slow. The check must happen as close as possible to the act (a classic time-of-check / time-of-use gap). `EDGE_ACTUATOR_DELAY_S` demonstrates it, and a unit test covers it.

**What is the difference between a process, a thread and a systemd service?** Process: own address space and PID. Thread: shares its process's memory. systemd service: a supervised cgroup unit with restart policy and resource accounting around a process tree (handbook section 2.1).

**What is `flock` and why `-n`?** An advisory lock on an open file descriptor, released by the kernel when the process dies. `-n` is non-blocking: if the lock is held we exit at once instead of queueing runs behind each other.

**Why WAL?** In rollback-journal mode a writer blocks readers. In WAL mode writers append to a log and readers read a consistent snapshot, so the dashboard, backup and SyncWorker can read while the Processor writes.

**How do you know no event is lost during the outage?** Every event has an outbox row in the same transaction; the scenario compares the sets of IDs: node events = outbox rows, and, after the sensors are paused and the outbox is empty, node events = receiver events (100 %).

**Does `sent` mean delivered?** Only after the receiver's JSON answer confirms `accepted` for that same `event_id`; any error leaves the row `pending` and increments `attempts`.

**What does the `spawn` start method change?** Children start a fresh interpreter and receive their arguments by pickling, so locks and threads of the parent are not inherited; everything shared must be explicit (Events, queues, Manager dict).

**Why is `SharedCounter` needed in the bounded queue?** `put_count` and `dropped_count` are incremented by several processes; `+= 1` is load-add-store and loses updates without the lock (`race_demo.py` shows it).

**What would you do with more time?** Hysteresis OFF for the pump; clock-offset estimation for remote sensors; a live AirKorea fetcher; per-worker restart instead of restarting the node; persistent actuation budget (water tank).

---

## 9. Suggested 10-minute demo

1. (1 min) `bash scripts/preflight.sh`, `bash scripts/start_demo.sh`, open the dashboard. Point at the 8 processes and the three sockets.
2. (2 min) OS4-1/2: show Sensor Channels and Recent Readings; show a late reading marked OUT OF ORDER.
3. (2 min) OS4-3: press "Dust episode"; the relay turns ON; release it; show it falls OFF after the TTL.
4. (2 min) OS4-5: cut the WAN; pending grows; processes stay green; restore; pending falls to 0.
5. (1 min) Extras: press "PM2.5 sensor hangs" during an episode; show STALE and the relay falling OFF; press "Quiet night" + "Dust episode" to show the hold.
6. (1 min) `python3 scenarios/os4_4_backup.py` result or `ls data/backups`; show `flock` refusal.
7. (1 min) Show `document/results/` (the official reports).

Do not press "Restore WAN" during a scenario run; do not run two nodes on the same ports.
