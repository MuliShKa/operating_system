import multiprocessing as mp
import random
import unittest

from edge.bounded_queue import BoundedSensorQueue
from edge.sensor import make_simulated_readings, run_sensor_generator


class SimulatedSensorTests(unittest.TestCase):
    """Check generated values and the sensor worker lifecycle."""

    def test_creates_lidar_and_imu_readings(self) -> None:
        """One sample contains both expected sensors at the same event time."""
        readings = make_simulated_readings(random.Random(4), observed_at=12.0)

        self.assertEqual(
            [reading.sensor_id for reading in readings],
            ["LIDAR_PROXIMITY_M", "IMU_YAW_RATE"],
        )
        self.assertTrue(0.2 <= readings[0].value <= 3.0)
        self.assertTrue(-1.5 <= readings[1].value <= 1.5)
        self.assertEqual(readings[0].observed_at, readings[1].observed_at)

    def test_worker_publishes_and_stops_on_event(self) -> None:
        """The spawned sensor process publishes readings and exits cleanly."""
        context = mp.get_context("spawn")
        sensor_queue = BoundedSensorQueue(maxsize=8, context=context)
        stop_event = context.Event()
        worker = context.Process(
            target=run_sensor_generator,
            args=(sensor_queue, stop_event, 0.01, 7),
        )

        worker.start()
        first_reading = sensor_queue.get(timeout=3)
        second_reading = sensor_queue.get(timeout=3)
        stop_event.set()
        worker.join(timeout=3)
        if worker.is_alive():
            worker.terminate()
            worker.join()

        self.assertEqual(worker.exitcode, 0)
        self.assertIsNotNone(first_reading)
        self.assertIsNotNone(second_reading)
        self.assertEqual(first_reading.observed_at, second_reading.observed_at)


if __name__ == "__main__":
    unittest.main()
