"""OS concurrency fundamentals for the OS4 node: bounded queue, race condition, deadlock.

Run: python tests/test_os_fundamentals.py -v
"""

import multiprocessing as mp
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("EDGE_SOCKET_DIR", f"/tmp/songdo-os4-test-{os.getpid()}")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edge.bounded_queue import BoundedQueue  # noqa: E402
from edge.deadlock_demo import DeadlockDemo  # noqa: E402
from edge.ipc import SIM_FLAGS, IpcChannels  # noqa: E402
from edge.race_demo import RaceDemo  # noqa: E402


def put_numbers(queue: BoundedQueue, producer_id: int, count: int) -> None:
    for number in range(count):
        queue.put((producer_id, number))


class TestBoundedQueue(unittest.TestCase):
    def test_drop_oldest_keeps_the_newest_500(self) -> None:
        queue = BoundedQueue(maxsize=500)
        for number in range(1000):
            queue.put(number)
        self.assertEqual(queue.stats(), {"size": 500, "maxsize": 500, "put_count": 1000, "dropped_count": 500})
        self.assertEqual([queue.get(timeout=1) for _ in range(500)], list(range(500, 1000)))

    def test_many_producers_nothing_lost_without_being_counted(self) -> None:
        queue = BoundedQueue(maxsize=500)
        producers = [mp.Process(target=put_numbers, args=(queue, p, 1000)) for p in range(4)]
        for producer in producers:
            producer.start()
        received = []
        while any(p.is_alive() for p in producers) or queue.size():
            self.assertLessEqual(queue.size(), 500)
            item = queue.get(timeout=0.05)
            if item is not None:
                received.append(item)
        for producer in producers:
            producer.join()
        self.assertEqual(queue.put_count.get_value(), 4000)
        self.assertEqual(len(received) + queue.dropped_count.get_value(), 4000)


class TestRaceCondition(unittest.TestCase):
    def test_unprotected_counter_loses_updates_and_mutex_fixes_it(self) -> None:
        demo = RaceDemo(workers=80)
        self.assertLess(demo.run(use_lock=False), 80)
        self.assertEqual(demo.run(use_lock=True), 80)


class TestDeadlock(unittest.TestCase):
    def test_opposite_lock_order_deadlocks_and_timeout_recovers(self) -> None:
        demo = DeadlockDemo()
        naive = demo.run(use_timeout=False)
        self.assertTrue(naive["deadlocked"])
        self.assertEqual(naive["finished_workers"], 0)
        fixed = demo.run(use_timeout=True)
        self.assertFalse(fixed["deadlocked"])
        self.assertEqual(fixed["finished_workers"], 2)


class TestChannels(unittest.TestCase):
    def test_flags_and_initial_state(self) -> None:
        channels = IpcChannels(mp.get_context("spawn"))
        self.assertTrue(channels.wan_online.is_set())          # the internet is up at startup
        self.assertFalse(channels.stop.is_set())
        self.assertEqual(set(channels.sim), set(SIM_FLAGS))
        self.assertTrue(all(not flag.is_set() for flag in channels.sim.values()))
        self.assertEqual(channels.sensor_events.maxsize, 500)


if __name__ == "__main__":
    unittest.main()
