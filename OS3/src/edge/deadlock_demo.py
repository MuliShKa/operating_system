import multiprocessing as mp
import random
import time
from multiprocessing.synchronize import Barrier, Lock

from edge.shared_counter import SharedCounter

# How long a process waits for its second lock before giving back the first one.
LOCK_TIMEOUT_S = 0.2

# After this long, the processes still alive are considered stuck forever.
GIVE_UP_AFTER_S = 1.0


class DeadlockDemo:
    """
    Deadlock demo: two processes take locks A and B in opposite order.

    Process 1 takes A then wants B. Process 2 takes B then wants A.
    Each waits for the other forever: that is a deadlock.
    The fix: wait at most 0.2 s for the second lock; if it fails, give back the
    first lock, pause a random time, and try again.

    Run: PYTHONPATH=src python -m edge.deadlock_demo
    """

    def run(self, use_timeout: bool) -> dict:
        """Start the two processes and return: deadlocked, finished_workers, retries, elapsed_s."""
        lock_a = mp.Lock()
        lock_b = mp.Lock()

        # The barrier makes sure both processes hold their first lock before
        # going on, so the deadlock happens every time.
        both_hold_first = mp.Barrier(2)

        finished = SharedCounter()   # processes that got both locks
        retries = SharedCounter()    # times a process gave back its first lock

        work = self.work_with_timeout if use_timeout else self.work_naive
        process_1 = mp.Process(target=work, args=(lock_a, lock_b, both_hold_first, finished, retries))
        process_2 = mp.Process(target=work, args=(lock_b, lock_a, both_hold_first, finished, retries))
        processes = [process_1, process_2]

        started = time.monotonic()
        for process in processes:
            process.start()
        deadlocked = self.wait_or_give_up(processes)
        elapsed = time.monotonic() - started

        return {
            "deadlocked": deadlocked,
            "finished_workers": finished.get_value(),
            "retries": retries.get_value(),
            "elapsed_s": round(elapsed, 3),
        }

    def wait_or_give_up(self, processes: list[mp.Process]) -> bool:
        """
        Wait up to GIVE_UP_AFTER_S for the processes to finish.
        Processes still alive are stuck: terminate them and return True.
        """
        deadline = time.monotonic() + GIVE_UP_AFTER_S
        for process in processes:
            process.join(timeout=max(0, deadline - time.monotonic()))

        deadlocked = False
        for process in processes:
            if process.is_alive():
                deadlocked = True
                process.terminate()
                # Collect the dead process so it is not left as a zombie.
                process.join()
        return deadlocked

    def work_naive(self, first: Lock, second: Lock, both_hold_first: Barrier,
                   finished: SharedCounter, retries: SharedCounter) -> None:
        """Take the first lock, then wait for the second one forever (deadlock)."""
        with first:
            both_hold_first.wait()
            # Never succeeds: the other process holds it.
            with second:
                finished.increment()

    def work_with_timeout(self, first: Lock, second: Lock, both_hold_first: Barrier,
                          finished: SharedCounter, retries: SharedCounter) -> None:
        """
        Take the first lock, then try the second one for at most LOCK_TIMEOUT_S.
        On failure, give back the first lock, pause a random time, and retry.

        The random pause matters: with the same pause, both processes would
        retry at the same instant and fail again forever (a livelock).
        """
        first.acquire()
        both_hold_first.wait()
        while not second.acquire(timeout=LOCK_TIMEOUT_S):
            # Give back what we hold so the other process can finish.
            first.release()
            retries.increment()
            time.sleep(random.uniform(0, LOCK_TIMEOUT_S))
            first.acquire()
        finished.increment()
        second.release()
        first.release()


if __name__ == "__main__":
    demo = DeadlockDemo()
    print(f"Opposite lock order:          {demo.run(use_timeout=False)}")
    print(f"With {LOCK_TIMEOUT_S} s acquire timeout:   {demo.run(use_timeout=True)}")
