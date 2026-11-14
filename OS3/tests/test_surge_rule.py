"""Tests for the OS3 local rule and the version-guarded sign state.

Run: python tests/test_surge_rule.py -v
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edge import decision, storage  # noqa: E402


class TestSurgeRule(unittest.TestCase):
    def test_below_threshold_issues_no_command(self) -> None:
        command, expires_at = decision.make_decision(decision.SURGE_THRESHOLD - 1, time.monotonic())
        self.assertIsNone(command)
        self.assertIsNone(expires_at)

    def test_at_threshold_issues_30_kmh_command(self) -> None:
        observed = time.monotonic()
        command, expires_at = decision.make_decision(decision.SURGE_THRESHOLD, observed)
        self.assertEqual(command.action, "VARIABLE_SPEED_SIGN_KMH")
        self.assertEqual(command.value, 30)
        self.assertGreater(expires_at, observed)

    def test_ttl_counts_from_the_reading_not_from_now(self) -> None:
        observed = time.monotonic() - 10.0   # the reading waited 10 s in a queue
        _, expires_at = decision.make_decision(decision.SURGE_THRESHOLD, observed)
        self.assertAlmostEqual(expires_at, observed + decision.COMMAND_TTL, places=6)
        # Only about TTL - 10 s of life is left.
        self.assertLess(expires_at - time.monotonic(), decision.COMMAND_TTL - 9.0)

    def test_reading_older_than_the_ttl_gives_an_already_expired_command(self) -> None:
        observed = time.monotonic() - (decision.COMMAND_TTL + 1.0)
        _, expires_at = decision.make_decision(decision.SURGE_THRESHOLD, observed)
        self.assertTrue(decision.is_command_expired(expires_at))

    def test_ttl_expiry_uses_the_monotonic_clock(self) -> None:
        self.assertFalse(decision.is_command_expired(time.monotonic() + 5))
        self.assertTrue(decision.is_command_expired(time.monotonic() - 0.01))
        self.assertTrue(decision.is_command_expired(None))
        # An explicit "now" makes the check deterministic.
        self.assertFalse(decision.is_command_expired(100.0, now=99.9))
        self.assertTrue(decision.is_command_expired(100.0, now=100.1))


class TestSignState(unittest.TestCase):
    """Scenario OS3-4: version guarding rejects stale writers."""

    def setUp(self) -> None:
        self.original_path = storage.DATABASE_PATH
        self.tmp = tempfile.TemporaryDirectory()
        storage.DATABASE_PATH = Path(self.tmp.name) / "test.db"
        storage.initialize_database()

    def tearDown(self) -> None:
        storage.DATABASE_PATH = self.original_path
        self.tmp.cleanup()

    def test_initial_state_is_normal_limit_version_zero(self) -> None:
        state = storage.get_sign_state()
        self.assertEqual(state["speed_limit_kmh"], 50)
        self.assertEqual(state["version"], 0)

    def test_update_bumps_the_version(self) -> None:
        self.assertTrue(storage.update_sign_state(30, expected_version=0))
        state = storage.get_sign_state()
        self.assertEqual((state["speed_limit_kmh"], state["version"]), (30, 1))

    def test_stale_writer_is_rejected(self) -> None:
        self.assertTrue(storage.update_sign_state(30, expected_version=0))
        # A second writer still holding version 0 must lose.
        self.assertFalse(storage.update_sign_state(50, expected_version=0))
        state = storage.get_sign_state()
        self.assertEqual((state["speed_limit_kmh"], state["version"]), (30, 1))

    def test_decision_without_event_is_allowed(self) -> None:
        storage.save_decision(None, "VARIABLE_SPEED_SIGN_KMH", "TTL expired", 50)

    def test_decision_with_unknown_event_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            storage.save_decision("missing-id", "VARIABLE_SPEED_SIGN_KMH")


if __name__ == "__main__":
    unittest.main()
