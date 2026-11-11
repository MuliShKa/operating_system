import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edge import receiver, storage, sync_worker


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestUpstreamSync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (storage.DATABASE_PATH, receiver.RECEIVER_DATABASE, sync_worker.RECEIVER_URL)
        storage.DATABASE_PATH = Path(self.tmp.name) / "edge.db"
        receiver.RECEIVER_DATABASE = Path(self.tmp.name) / "upstream.db"
        storage.initialize_database()

    def tearDown(self):
        storage.DATABASE_PATH, receiver.RECEIVER_DATABASE, sync_worker.RECEIVER_URL = self.saved
        self.tmp.cleanup()

    def test_receiver_ignores_duplicates(self):
        receiver.initialize_receiver_database()
        self.assertTrue(receiver.accept_event({"event_id": "a", "payload": {}}))
        self.assertFalse(receiver.accept_event({"event_id": "a", "payload": {}}))
        self.assertEqual(receiver.get_received_count(), 1)

    def test_wan_cut_then_restore_loses_nothing(self):
        port = free_port()
        sync_worker.RECEIVER_URL = f"http://127.0.0.1:{port}/api/events"
        channels = SimpleNamespace(stop=threading.Event(), wan_online=threading.Event())
        state = {}

        # WAN is down from the start
        threads = [
            threading.Thread(target=receiver.run_receiver, args=(channels.stop, "127.0.0.1", port)),
            threading.Thread(target=sync_worker.run_sync_worker, args=(channels, state)),
        ]
        for t in threads:
            t.start()

        try:
            for i in range(20):
                storage.save_event(f"evt-{i}", "SLUICE_WATER_LEVEL_M", "2026-10-23T00:00:00", {"value": i})

            time.sleep(1)
            self.assertEqual(receiver.get_received_count(), 0)
            self.assertEqual(storage.get_pending_event_count(), 20)

            channels.wan_online.set()
            deadline = time.monotonic() + 10
            while storage.get_pending_event_count() and time.monotonic() < deadline:
                time.sleep(0.1)
        finally:
            channels.stop.set()
            for t in threads:
                t.join(5)

        report = receiver.check_conservation()
        self.assertEqual(report, {"created": 20, "received": 20, "queued": 0, "ok": True})


if __name__ == "__main__":
    unittest.main()
