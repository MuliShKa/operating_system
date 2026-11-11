import multiprocessing as mp
from multiprocessing.synchronize import Barrier

from edge.shared_counter import SharedCounter

class RaceDemo:
    """
    Race condition demo: 80 processes add 1 to the same counter at the same time.

    Run: PYTHONPATH=src python -m edge.race_demo
    """

    def __init__(self, workers: int = 80) -> None:

        # The workers is the number of processes that add 1 to the counter.
        self.workers = workers

    def run(self, use_lock: bool) -> int:
        """
        Start the processes and return the final counter value.
        Expected: exactly `workers`.
        """

        counter = SharedCounter()

        # The barrier holds every process until all are ready,
        # then releases them together, so they really collide.
        start_line = mp.Barrier(self.workers)

        processes = []
        for _ in range(self.workers):
            process = mp.Process(target=self.add_one, args=(counter, start_line, use_lock))
            processes.append(process)

        for process in processes:
            process.start()
        for process in processes:
            process.join()
        return counter.get_value()

    def add_one(self, counter: SharedCounter, start_line: Barrier, use_lock: bool) -> None:
        """
        Wait for every other process, then add 1 to the counter (with or without the lock).
        """

        start_line.wait()
        if use_lock:
            counter.increment()
        else:
            counter.unsafe_increment(pause_s=0.005)

if __name__ == "__main__":
    demo = RaceDemo()
    print(f"{demo.workers} processes, without lock: counter = {demo.run(use_lock=False)}")
    print(f"{demo.workers} processes, with lock:    counter = {demo.run(use_lock=True)}")
