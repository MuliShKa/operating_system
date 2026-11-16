import multiprocessing as mp
import random
import time
from multiprocessing.synchronize import Barrier, Lock

from edge.shared_counter import SharedCounter

# How long a process waits for its second lock before giving back the first one.
LOCK_TIMEOUT_S = 0.2

# Bound the whole demonstration, including lock acquisition retries.
GIVE_UP_AFTER_S = 5.0

# Stop retrying with a clear failure instead of allowing an indefinite livelock.
MAX_LOCK_RETRIES = 10
PROCESS_REAP_TIMEOUT_S = 1.0

class DeadlockDemo:
    """
    Deadlock demo: two processes take locks A and B in opposite order.

    Process 1 takes A then wants B. Process 2 takes B then wants A.
    Each waits for the other forever: that is a deadlock.
    The fix: wait at most 0.2 s for the second lock; if it fails, give back the
    first lock, pause a random time, and retry up to a fixed limit.

    Run: PYTHONPATH=src python -m edge.deadlock_demo
    """

    def run(self, use_timeout: bool) -> dict:
        """
        Start both processes and report deadlock, completion, failures, retries,
        and elapsed time.
        """

        lock_a = mp.Lock()
        lock_b = mp.Lock()

        # The barrier makes sure both processes hold their first lock before going on,
        # so the deadlock happens every time.
        both_hold_first = mp.Barrier(2)

        # The finished counter counts the processes that got both locks.
        finished = SharedCounter()

        # The retries counter counts how many times a process gave back its first lock.
        retries = SharedCounter()
        failed = SharedCounter()

        if use_timeout:
            work = self.work_with_timeout
        else:
            work = self.work_naive
        process_1 = mp.Process(
            target=work,
            args=(lock_a, lock_b, both_hold_first, finished, retries, failed),
        )
        process_2 = mp.Process(
            target=work,
            args=(lock_b, lock_a, both_hold_first, finished, retries, failed),
        )
        processes = [process_1, process_2]

        started = time.monotonic()
        started_processes = []
        try:
            for process in processes:
                process.start()
                started_processes.append(process)
        except BaseException as start_error:
            try:
                self._stop_and_reap_processes(started_processes)
            except RuntimeError as cleanup_error:
                raise RuntimeError(
                    f"could not clean up after process startup failed: {cleanup_error}"
                ) from start_error
            raise
        deadlocked = self.wait_or_give_up(processes)
        elapsed = time.monotonic() - started

        return {
            "deadlocked": deadlocked,
            "finished_workers": finished.get_value(),
            "failed_workers": failed.get_value(),
            "retries": retries.get_value(),
            "elapsed_s": round(elapsed, 3),
        }

    def wait_or_give_up(self, processes: list[mp.Process]) -> bool:
        """
        Wait up to GIVE_UP_AFTER_S for the processes to finish.
        The processes still alive are stuck: kill them and return True.
        """

        deadline = time.monotonic() + GIVE_UP_AFTER_S
        for process in processes:
            time_left = max(0, deadline - time.monotonic())
            process.join(timeout=time_left)

        deadlocked = any(process.is_alive() for process in processes)
        exit_codes = {
            process.name: process.exitcode
            for process in processes
        }
        self._stop_and_reap_processes(processes)

        if not deadlocked:
            failed_workers = {
                name: exit_code
                for name, exit_code in exit_codes.items()
                if exit_code != 0
            }
            if failed_workers:
                raise RuntimeError(
                    f"deadlock demo worker failed: {failed_workers}"
                )
        return deadlocked

    @staticmethod
    def _stop_and_reap_processes(processes: list[mp.Process]) -> None:
        for process in processes:
            if process.is_alive():
                process.terminate()

        for process in processes:
            process.join(timeout=PROCESS_REAP_TIMEOUT_S)
            if process.is_alive():
                process.kill()
                process.join(timeout=PROCESS_REAP_TIMEOUT_S)
            if process.is_alive():
                raise RuntimeError(
                    f"could not reap deadlock demo process {process.name}"
                )
            process.close()

    def work_naive(
        self,
        first: Lock,
        second: Lock,
        both_hold_first: Barrier,
        finished: SharedCounter,
        retries: SharedCounter,
        _failed: SharedCounter,
    ) -> None:
        """
        Take the first lock, then wait for the second one forever.

            Process 1 (A then B)    Process 2 (B then A)
            --------------------    --------------------
            take A                  take B
            barrier: wait           barrier: wait          <- both now hold their first lock
            wants B: waits          wants A: waits
            ...waits forever        ...waits forever       <- DEADLOCK

                   holds              holds
            P1 ------------> A        P2 ------------> B
            P1 ...waits for B         P2 ...waits for A    (a cycle: nobody can go on)
        """

        with first:
            both_hold_first.wait()
            # Never succeeds: the other process holds it.
            with second:
                finished.increment()

    def work_with_timeout(
        self,
        first: Lock,
        second: Lock,
        both_hold_first: Barrier,
        finished: SharedCounter,
        retries: SharedCounter,
        failed: SharedCounter,
    ) -> None:
        """
        Take the first lock, then try the second one for at most LOCK_TIMEOUT_S.
        On failure, give back the first lock, pause, and try again.

            Process 1 (A then B)        Process 2 (B then A)
            --------------------        --------------------
            take A                      take B
            barrier: wait               barrier: wait
            wants B (0.2 s max)         wants A (0.2 s max)
            0.2 s: failed               0.2 s: failed
            give back A                 give back B            <- the cycle is broken
            random pause (0.05 s)       random pause (0.15 s)
            take A again
            take B: OK  -> finished
            give back B and A
                                        take B again
                                        take A: OK  -> finished

        The random pause matters: with the same pause, both would take their
        first lock again at the same time and fail again, forever (a livelock).
        """

        first.acquire()
        holds_first = True
        try:
            both_hold_first.wait(timeout=GIVE_UP_AFTER_S)
            for attempt in range(MAX_LOCK_RETRIES + 1):
                if second.acquire(timeout=LOCK_TIMEOUT_S):
                    try:
                        finished.increment()
                    finally:
                        second.release()
                    return

                retries.increment()
                if attempt == MAX_LOCK_RETRIES:
                    failed.increment()
                    return

                # Give back what we hold so the other process can make progress.
                first.release()
                holds_first = False
                time.sleep(random.uniform(0, LOCK_TIMEOUT_S))
                first.acquire()
                holds_first = True
        finally:
            if holds_first:
                first.release()


if __name__ == "__main__":
    demo = DeadlockDemo()
    print(f"Opposite lock order:          {demo.run(use_timeout=False)}")
    print(f"With {LOCK_TIMEOUT_S} s acquire timeout:   {demo.run(use_timeout=True)}")
