"""
OS1-2: 80 turnstile processes count people into one shared occupancy counter.

- Without a lock, "+1" is READ, ADD, WRITE. If the scheduler preempts a turnstile
  between READ and WRITE, another one's update is lost: the count ends below 80.
- With a mutex around READ-ADD-WRITE, only one turnstile is in that critical
  section at a time: the count is exactly 80.

Each turnstile waits a random 0..5 ms between READ and WRITE, standing for a
preemption at a random moment, so the loss shows up on every run.

Run: PYTHONPATH=src python -m edge.os1_2_race.occupancy
"""

import multiprocessing as mp
import random
import time

from edge.os1_2_race.shared_counter import SharedCounter

TURNSTILES = 80
MAX_PAUSE_S = 0.005


def turnstile(counter: SharedCounter, start_line, use_lock: bool, max_pause_s: float) -> None:
    """One turnstile: wait until all are ready, then count one person in."""
    start_line.wait()
    if use_lock:
        counter.increment()
    else:
        counter.unsafe_increment(pause_s=random.uniform(0, max_pause_s))


def count_entries(turnstiles: int = TURNSTILES, use_lock: bool = True, pause_s: float = MAX_PAUSE_S) -> dict:
    """Run one trial and return the final count and the lost updates."""
    context = mp.get_context("spawn")
    counter = SharedCounter(context)
    start_line = context.Barrier(turnstiles)  # releases all turnstiles at the same moment
    processes = [
        context.Process(target=turnstile, args=(counter, start_line, use_lock, pause_s))
        for _ in range(turnstiles)
    ]
    started = time.monotonic()
    for process in processes:
        process.start()
    for process in processes:
        process.join()  # reap every child: no zombie left
    final = counter.get()
    return {
        "mode": "mutex" if use_lock else "unprotected",
        "expected": turnstiles,
        "final": final,
        "lost_updates": turnstiles - final,
        "seconds": round(time.monotonic() - started, 3),
        "exit_codes_ok": all(process.exitcode == 0 for process in processes),
    }


if __name__ == "__main__":
    for lock in (False, True):
        print(count_entries(use_lock=lock))
