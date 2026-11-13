"""
OS1-2: competing occupancy writers (turnstiles) and the race condition.

80 turnstile processes each record one entry in the same shared occupancy
counter at the same moment (a barrier releases them together).

- Without a lock, `occupancy = occupancy + 1` is LOAD, ADD, STORE: if the OS
  preempts a writer between LOAD and STORE, another writer's update is lost,
  so the final count is below 80.
- With a multiprocessing.Lock around the read-modify-write, only one writer
  is in the critical section at a time, so the final count is exactly 80.

The pause between LOAD and STORE stands for an involuntary context switch.
Each writer gets a random pause between 0 and PREEMPTION_PAUSE_S, like a
scheduler that preempts writers at different moments: some updates are lost,
not all, and the loss changes from run to run. With pause_s=0 the race window
is a few microseconds and the loss depends on the machine (shown, not asserted).

Run: PYTHONPATH=src python -m edge.occupancy
"""

from __future__ import annotations

import multiprocessing as mp
import random
import time
from multiprocessing.synchronize import Barrier

from edge.shared_counter import SharedCounter

TURNSTILES = 80
PREEMPTION_PAUSE_S = 0.005


def _turnstile_entry(counter: SharedCounter, start_line: Barrier, use_lock: bool, pause_s: float) -> None:
    """One turnstile: wait for all the others, then count one person in."""
    start_line.wait()
    if use_lock:
        counter.increment()
    else:
        counter.unsafe_increment(pause_s=random.uniform(0, pause_s))


def count_entries(
    turnstiles: int = TURNSTILES,
    use_lock: bool = True,
    pause_s: float = PREEMPTION_PAUSE_S,
) -> dict:
    """Run one trial and return the final count, the lost updates and the time taken."""
    context = mp.get_context("spawn")
    counter = SharedCounter(context)
    start_line = context.Barrier(turnstiles)
    writers = [
        context.Process(target=_turnstile_entry, args=(counter, start_line, use_lock, pause_s))
        for _ in range(turnstiles)
    ]
    started = time.monotonic()
    for writer in writers:
        writer.start()
    for writer in writers:
        # join() reaps every child: no zombie is left behind.
        writer.join()
    final = counter.get_value()
    return {
        "mode": "mutex" if use_lock else "unprotected",
        "expected": turnstiles,
        "final": final,
        "lost_updates": turnstiles - final,
        "seconds": round(time.monotonic() - started, 3),
        "exit_codes_ok": all(writer.exitcode == 0 for writer in writers),
    }


if __name__ == "__main__":
    for lock in (False, True):
        print(count_entries(use_lock=lock))
