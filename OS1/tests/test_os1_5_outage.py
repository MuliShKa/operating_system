"""OS1-5: conservation check, receiver deduplication, no delivery while offline."""

import importlib.util
import multiprocessing
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

OS1_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OS1_DIR / "src"))

from edge import receiver, storage, sync_worker  # noqa: E402
from edge.ipc import IpcChannels  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "os1_5_wan_outage", OS1_DIR / "scenarios" / "os1_5_wan_outage.py"
)
sys.path.insert(0, str(OS1_DIR / "scenarios"))
outage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(outage)


class TestConservation(unittest.TestCase):
    def test_all_delivered_once(self):
        result = outage.check_conservation(["a", "b"], ["b", "a"])
        self.assertEqual((result["lost"], result["duplicates"]), (0, 0))

    def test_detects_a_lost_event(self):
        self.assertEqual(outage.check_conservation(["a", "b"], ["a"])["lost"], 1)

    def test_detects_a_duplicate(self):
        self.assertEqual(outage.check_conservation(["a"], ["a", "a"])["duplicates"], 1)

    def test_events_after_the_boundary_are_not_lost(self):
        self.assertEqual(outage.check_conservation(["a"], ["a", "later"])["lost"], 0)


class TestReceiverAndSync(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.originals = (storage.DATABASE_PATH, receiver.RECEIVER_DATABASE)
        storage.DATABASE_PATH = Path(self.folder.name) / "node.db"
        receiver.RECEIVER_DATABASE = Path(self.folder.name) / "node_upstream.db"
        storage.initialize_database()
        receiver.initialize_receiver_database()

    def tearDown(self):
        storage.DATABASE_PATH, receiver.RECEIVER_DATABASE = self.originals
        self.folder.cleanup()

    def test_receiver_stores_an_event_id_once(self):
        event = {"event_id": "e1", "payload": {"value": 1}}
        self.assertTrue(receiver.accept_event(event))
        self.assertFalse(receiver.accept_event(event))
        with closing(sqlite3.connect(receiver.RECEIVER_DATABASE)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM received_events").fetchone()[0], 1)

    def test_sync_worker_sends_nothing_while_offline(self):
        storage.save_event("e1", "INDOOR_CO2_PPM", "2026-11-11T00:00:00", {"value": 1200})
        channels = IpcChannels(multiprocessing.get_context("spawn"))
        channels.wan_online.clear()
        sent = []
        original_deliver = sync_worker.deliver_event
        sync_worker.deliver_event = lambda event: sent.append(event) or True
        original_wait = channels.stop.wait
        try:
            # One loop turn: the stop flag is set as soon as the worker waits.
            channels.stop.wait = lambda _timeout: channels.stop.set() or True
            sync_worker.run_sync_worker(channels, {})
        finally:
            sync_worker.deliver_event = original_deliver
            channels.stop.wait = original_wait
        self.assertEqual(sent, [])
        self.assertEqual(storage.get_pending_event_count(), 1)

    def test_wan_starts_online(self):
        channels = IpcChannels(multiprocessing.get_context("spawn"))
        self.assertTrue(channels.wan_online.is_set())


if __name__ == "__main__":
    unittest.main()
