"""OS1-2: unprotected turnstile counter loses updates, the mutex does not."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edge.occupancy import TURNSTILES, count_entries  # noqa: E402


class TestOccupancyRace(unittest.TestCase):
    def test_unprotected_counter_is_below_80(self):
        result = count_entries(use_lock=False)
        self.assertEqual(result["expected"], TURNSTILES)
        self.assertLess(result["final"], TURNSTILES)
        self.assertGreater(result["lost_updates"], 0)

    def test_mutex_counter_is_exactly_80(self):
        result = count_entries(use_lock=True)
        self.assertEqual(result["final"], TURNSTILES)
        self.assertEqual(result["lost_updates"], 0)

    def test_mutex_holds_even_with_the_preemption_pause(self):
        # The pause only matters inside the unprotected path; the lock still wins.
        self.assertEqual(count_entries(turnstiles=20, use_lock=True, pause_s=0.01)["final"], 20)

    def test_every_writer_is_reaped(self):
        self.assertTrue(count_entries(turnstiles=10, use_lock=False)["exit_codes_ok"])


if __name__ == "__main__":
    unittest.main()
