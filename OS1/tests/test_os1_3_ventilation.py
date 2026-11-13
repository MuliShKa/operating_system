"""OS1-3: CO2 rule, 15 s monotonic TTL, actuator accepts or rejects."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edge import actuator, decision  # noqa: E402
from edge.models import ActuatorCommand  # noqa: E402

READ_AT = 1000.0  # a monotonic time; any value works


class TestVentilationRule(unittest.TestCase):
    def test_below_threshold_gives_no_command(self):
        self.assertEqual(decision.make_decision(999.9, READ_AT), (None, None))

    def test_at_threshold_gives_no_command(self):
        self.assertEqual(decision.make_decision(1000.0, READ_AT), (None, None))

    def test_above_threshold_opens_damper_to_100(self):
        result, _ = decision.make_decision(1000.1, READ_AT)
        self.assertEqual(result.action, "HVAC_DAMPER_PCT")
        self.assertEqual(result.value, 100)

    def test_ttl_counts_from_the_reading(self):
        _, expires_at = decision.make_decision(1200, READ_AT)
        self.assertEqual(expires_at, READ_AT + 15.0)

    def test_expiry_boundary(self):
        expires_at = READ_AT + 15.0
        self.assertFalse(decision.is_command_expired(expires_at, READ_AT + 14.9))
        self.assertFalse(decision.is_command_expired(expires_at, READ_AT + 15.0))
        self.assertTrue(decision.is_command_expired(expires_at, READ_AT + 15.1))

    def test_missing_expiry_is_expired(self):
        self.assertTrue(decision.is_command_expired(None, READ_AT))


class TestActuator(unittest.TestCase):
    def command(self):
        _, expires_at = decision.make_decision(1200, READ_AT)
        return ActuatorCommand("event-1", "HVAC_DAMPER_PCT", 100, "test", expires_at)

    def test_fresh_command_is_applied(self):
        outcome, _ = actuator.handle_command(self.command(), READ_AT + 1)
        self.assertEqual(outcome, actuator.APPLIED)

    def test_stale_command_is_rejected(self):
        outcome, reason = actuator.handle_command(self.command(), READ_AT + 16)
        self.assertEqual(outcome, actuator.EXPIRED)
        self.assertIn("expired", reason)


if __name__ == "__main__":
    unittest.main()
