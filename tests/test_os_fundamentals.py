"""Automated OS concurrency and durability test suite.

Run: python tests/test_os_fundamentals.py -v
"""

import multiprocessing as mp
from multiprocessing.queues import Queue
from multiprocessing.sharedctypes import Synchronized
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from edge.bounded_queue import STOP, BoundedQueue  # noqa: E402
from edge.deadlock_demo import LOCK_TIMEOUT_S, DeadlockDemo  # noqa: E402
from edge.ipc import IpcChannels  # noqa: E402
from edge.priority_demo import PriorityDemo  # noqa: E402
from edge.priority_queue import PriorityQueue  # noqa: E402
from edge.race_demo import RaceDemo  # noqa: E402
from edge.unix_socket import UnixSocketClient, UnixSocketServer  # noqa: E402


def put_numbers(queue: BoundedQueue, producer_id: int, count: int) -> None:
    for number in range(count):
        queue.put((producer_id, number))


def put_numbers_then_stop(queue: BoundedQueue, count: int) -> None:
    put_numbers(queue, 0, count)
    queue.put(STOP)


def count_forever(queue: BoundedQueue, result: Synchronized) -> None:
    while True:
        if queue.get(timeout=0.2) is not None:
            result.value += 1


def count_until_stop(queue: BoundedQueue, result: Synchronized) -> None:
    handled = 0
    while queue.get() != STOP:
        handled += 1
    result.value = handled


class TestBoundedQueue(unittest.TestCase):
    def test_drop_oldest_keeps_the_newest_items(self) -> None:
        queue = BoundedQueue(maxsize=500)
        for number in range(1000):
            queue.put(number)

        self.assertEqual(queue.stats(), {"size": 500, "maxsize": 500, "put_count": 1000, "dropped_count": 500})
        remaining = [queue.get(timeout=1) for _ in range(500)]
        self.assertEqual(remaining, list(range(500, 1000)))
        self.assertIsNone(queue.get(timeout=0.1))

    def test_many_producers_nothing_lost_without_being_counted(self) -> None:
        queue = BoundedQueue(maxsize=500)
        producers = [mp.Process(target=put_numbers, args=(queue, p, 1000)) for p in range(4)]
        for producer in producers:
            producer.start()

        received = []
        while any(producer.is_alive() for producer in producers) or queue.size():
            self.assertLessEqual(queue.size(), 500)
            item = queue.get(timeout=0.05)
            if item is not None:
                received.append(item)
        for producer in producers:
            producer.join()

        self.assertEqual(queue.put_count.get_value(), 4000)
        self.assertEqual(len(received) + queue.dropped_count.get_value(), 4000)


class TestConsumerKilled(unittest.TestCase):
    """The supervisor kills the Processor with SIGKILL, then starts a new one."""

    def kill_waiting_consumer(self, queue: BoundedQueue) -> None:
        result = mp.Value("i", 0)
        consumer = mp.Process(target=count_forever, args=(queue, result))
        consumer.start()
        time.sleep(0.3)  # the consumer is now waiting inside get()
        consumer.kill()  # sends SIGKILL: cannot be caught, no cleanup runs
        consumer.join()

    def test_new_consumer_still_reads_the_queue(self) -> None:
        queue = BoundedQueue(maxsize=500)
        self.kill_waiting_consumer(queue)

        result = mp.Value("i", 0)
        new_consumer = mp.Process(target=count_forever, args=(queue, result))
        new_consumer.start()
        put_numbers(queue, 0, 10)
        time.sleep(1)
        new_consumer.kill()
        new_consumer.join()
        self.assertEqual(result.value, 10)

    def test_producer_does_not_hang_when_queue_is_full(self) -> None:
        queue = BoundedQueue(maxsize=500)
        self.kill_waiting_consumer(queue)

        producer = mp.Process(target=put_numbers, args=(queue, 0, 600))
        producer.start()
        producer.join(timeout=10)
        stuck = producer.is_alive()
        if stuck:
            producer.kill()
            producer.join()
        self.assertFalse(stuck)
        self.assertEqual(queue.dropped_count.get_value(), 100)


class TestShutdownSentinel(unittest.TestCase):
    def test_consumer_handles_everything_then_exits(self) -> None:
        queue = BoundedQueue(maxsize=500)
        result = mp.Value("i", -1)
        consumer = mp.Process(target=count_until_stop, args=(queue, result))
        producer = mp.Process(target=put_numbers_then_stop, args=(queue, 200))
        consumer.start()
        producer.start()
        producer.join(timeout=5)
        consumer.join(timeout=5)

        self.assertFalse(consumer.is_alive())
        self.assertEqual(consumer.exitcode, 0)  # exited on its own, and was collected
        self.assertEqual(result.value, 200)


class TestPriorityQueue(unittest.TestCase):
    def test_urgent_items_come_out_first(self) -> None:
        queue = PriorityQueue()
        for number in range(5):
            queue.put(("log", number))
        queue.put(("alarm", 0), urgent=True)
        queue.put(("alarm", 1), urgent=True)

        order = [queue.get(timeout=1) for _ in range(7)]
        self.assertEqual(order[:2], [("alarm", 0), ("alarm", 1)])
        self.assertEqual(order[2:], [("log", number) for number in range(5)])
        self.assertIsNone(queue.get(timeout=0.1))

    def test_each_lane_is_bounded(self) -> None:
        queue = PriorityQueue(maxsize=50)
        for number in range(200):
            queue.put(number)
            queue.put(number, urgent=True)
        self.assertEqual(queue.urgent.size(), 50)
        self.assertEqual(queue.normal.size(), 50)
        self.assertEqual(queue.stats()["normal"]["dropped_count"], 150)

    def test_stop_comes_after_pending_alarms(self) -> None:
        queue = PriorityQueue()
        queue.put(("log", 0))
        queue.put(STOP)
        queue.put(("alarm", 0), urgent=True)
        self.assertEqual(queue.get(timeout=1), ("alarm", 0))
        self.assertEqual(queue.get(timeout=1), ("log", 0))
        self.assertEqual(queue.get(timeout=1), STOP)

    def test_alarms_skip_the_backlog(self) -> None:
        demo = PriorityDemo(items=300, alarm_every=30)
        self.assertEqual(demo.run(use_priority=False), list(range(29, 300, 30)))
        self.assertEqual(demo.run(use_priority=True), list(range(10)))


class TestIpcChannels(unittest.TestCase):
    def test_initial_state(self) -> None:
        ipc = IpcChannels()
        self.assertEqual(ipc.sensor_events.maxsize, 500)
        self.assertFalse(ipc.stop.is_set())
        self.assertTrue(ipc.wan_online.is_set())


class TestRaceCondition(unittest.TestCase):
    def test_without_lock_loses_updates(self) -> None:
        demo = RaceDemo(workers=80)
        self.assertLess(demo.run(use_lock=False), 80)

    def test_with_lock_counts_exactly(self) -> None:
        demo = RaceDemo(workers=80)
        self.assertEqual(demo.run(use_lock=True), 80)


class TestDeadlock(unittest.TestCase):
    def test_opposite_lock_order_deadlocks(self) -> None:
        result = DeadlockDemo().run(use_timeout=False)
        self.assertTrue(result["deadlocked"])
        self.assertEqual(result["finished_workers"], 0)

    def test_acquire_timeout_recovers(self) -> None:
        result = DeadlockDemo().run(use_timeout=True)
        self.assertFalse(result["deadlocked"])
        self.assertEqual(result["finished_workers"], 2)
        self.assertGreaterEqual(result["retries"], 1)
        self.assertGreaterEqual(result["elapsed_s"], LOCK_TIMEOUT_S)


def echo_cmd(question: dict) -> dict:
    return {"echo": question["cmd"]}


def read_missing_key(question: dict) -> dict:
    return {"value": question["missing"]}  # raises KeyError on purpose


def answer_ok(question: dict) -> dict:
    return {"ok": True}


def ask_status(path: Path, answers: Queue) -> None:
    answers.put(UnixSocketClient(path).ask({"cmd": "status"}))


class TestUnixSocket(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "node.sock"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_question_and_answer_between_processes(self) -> None:
        server = UnixSocketServer(self.path, echo_cmd)
        server.start()
        answers: Queue = mp.Queue()
        client = mp.Process(target=ask_status, args=(self.path, answers))
        client.start()
        client.join(timeout=5)
        server.stop()

        self.assertEqual(answers.get(timeout=1), {"echo": "status"})
        self.assertFalse(self.path.exists())

    def test_bad_question_returns_error_and_server_survives(self) -> None:
        server = UnixSocketServer(self.path, read_missing_key)
        server.start()
        client = UnixSocketClient(self.path)
        self.assertIn("error", client.ask({}))
        self.assertIn("error", client.ask({}))
        server.stop()

    def test_silent_client_does_not_block_the_server(self) -> None:
        server = UnixSocketServer(self.path, answer_ok)
        server.start()
        silent = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        silent.connect(str(self.path))  # connects, never sends anything
        try:
            self.assertEqual(UnixSocketClient(self.path, timeout=2).ask({}), {"ok": True})
        finally:
            silent.close()
            server.stop()

    def test_missing_folder_is_created(self) -> None:
        path = Path(self.tmp.name) / "songdo" / "node.sock"
        server = UnixSocketServer(path, answer_ok)
        server.start()
        self.assertEqual(UnixSocketClient(path).ask({}), {"ok": True})
        server.stop()

    def test_old_socket_file_is_replaced(self) -> None:
        self.path.touch()  # left behind by a crashed run
        server = UnixSocketServer(self.path, answer_ok)
        server.start()
        self.assertEqual(UnixSocketClient(self.path).ask({}), {"ok": True})
        server.stop()


if __name__ == "__main__":
    unittest.main()
