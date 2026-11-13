# 08 – OS1-2 competing occupancy writers

Handbook: run 80 concurrent increments; unprotected counter < 80, mutex counter = 80.

Design:
- `SharedCounter` (copied from OS5): a `RawValue` in shared memory (no built-in lock)
  plus a `multiprocessing.Lock`.
- `occupancy.count_entries`: 80 turnstile processes wait on a `Barrier`, then each adds 1.
  Unprotected: read, pause, write. With lock: the read-modify-write is inside the lock.
  Every process is joined (no zombie) and its exit code checked.
- The pause stands for an involuntary context switch between LOAD and STORE.

Mistake on the way: with a fixed 5 ms pause, all 80 writers read 0 and the result was
1/80 every time. Correct, but it looks staged. Now each writer pauses a random 0–5 ms,
like a scheduler preempting at different moments.

Evidence (2026-11-13, 5 trials): unprotected 14–20 / 80, mutex 80 / 80 every time.
Information only: with no pause at all, 52–59 / 80 – about 25 updates lost per run just
from real preemption on this 14-core machine. 3/3 checks.
Report: `document/results/os1_2_race.json`. Tests: `tests/test_os1_2_race.py`.
