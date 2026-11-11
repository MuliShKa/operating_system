import multiprocessing as mp
import socket
import tempfile
import unittest
from pathlib import Path

from edge.bounded_queue import BoundedSensorQueue
from edge.models import SensorReading
from edge.unix_socket import UnixMessageClient, UnixMessageServer


def put_reading(sensor_queue: BoundedSensorQueue) -> None:
    """Send one sample from a spawned child process."""
    sensor_queue.put(SensorReading("LIDAR_PROXIMITY_M", 0.7, "m", 1.0))


class BoundedSensorQueueTests(unittest.TestCase):
    """Check the queue limit, drop policy, and process sharing."""

    def test_drops_oldest_readings_when_full(self) -> None:
        """New readings replace older ones when capacity is reached."""
        sensor_queue = BoundedSensorQueue(maxsize=3)
        for value in range(5):
            sensor_queue.put(SensorReading("LIDAR_PROXIMITY_M", value, "m", float(value)))

        readings = [sensor_queue.get(timeout=1) for _ in range(3)]

        self.assertEqual([reading.value for reading in readings if reading], [2, 3, 4])
        self.assertEqual(sensor_queue.dropped_count(), 2)

    def test_queue_is_shared_with_child_process(self) -> None:
        """A child can write a reading that the parent later receives."""
        context = mp.get_context("spawn")
        sensor_queue = BoundedSensorQueue(maxsize=2, context=context)
        producer = context.Process(target=put_reading, args=(sensor_queue,))

        producer.start()
        producer.join(timeout=5)
        if producer.is_alive():
            producer.terminate()
            producer.join()

        self.assertEqual(producer.exitcode, 0)
        reading = sensor_queue.get(timeout=1)
        self.assertIsNotNone(reading)
        self.assertEqual(reading.sensor_id, "LIDAR_PROXIMITY_M")


@unittest.skipUnless(hasattr(socket, "AF_UNIX"), "Unix domain sockets are unavailable")
class UnixMessageSocketTests(unittest.TestCase):
    """Check one complete local JSON request/response round trip."""

    def test_request_response_and_socket_cleanup(self) -> None:
        """The server replies to a client and removes its file on shutdown."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            socket_path = Path(temporary_directory) / "controller.sock"
            with UnixMessageServer(socket_path, lambda message: {"received": message}) as server:
                response = UnixMessageClient(socket_path).request({"cmd": "status"})
                self.assertEqual(response, {"received": {"cmd": "status"}})

            self.assertFalse(socket_path.exists())


if __name__ == "__main__":
    unittest.main()