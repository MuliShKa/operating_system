# 04 – OS1-4 contention profiling

Handbook: sample `/proc/[pid]/stat`, record to `process_health` every 2.0 s, measure RSS
and context switches under synthetic load.

Design:
- `proc_stats.py` parses `/proc/[pid]/stat` (CPU time, RSS, threads) and
  `/proc/[pid]/status` (voluntary / involuntary context switches; they are not in `stat`).
  The name field can contain spaces and brackets, so parsing starts after the last `)`.
- `ProcSampler` is a node worker: fixed monotonic schedule of 2.0 s, one row per worker,
  status `sampled`, JSON in `details`. A vanished PID gives a `missing` row.
- `scenarios/os1_4_contention.py` adds CPU burners (2 × CPU count) for the load phase and
  reads the rows back from the database.

Evidence (short run, 10 s per phase, 28 burners): all 8 workers sampled in both phases,
median period 2.0 s, involuntary switches up under load (Processor 2.9 → 15.2 /s,
SyncWorker 3.0 → 16.8 /s). The full 30 s run is still to do.

Why Processor and Actuator show ~100 voluntary switches/s even when idle:
`BoundedQueue.get()` polls with `time.sleep(0.01)` (POLL_S) while the queue is empty, so the
process gives the CPU back about 100 times per second. This is the price of never waiting
inside the queue lock (safer if the consumer is killed).
