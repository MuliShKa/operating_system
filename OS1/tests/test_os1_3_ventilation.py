"""OS1-3: CO2 rule, 15 s monotonic TTL, actuator accepts or rejects."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edge.os1_3_ventilation import actuator  # noqa: E402
from edge.os1_3_ventilation import decision  # noqa: E402

READ_AT = 1000.0  # a monotonic time; any value works


class TestVentilationRule(unittest.TestCase):
    def test_below_threshold_gives_no_command(self):
        self.assertIsNone(decision.make_command("e1", 999.9, READ_AT))

    def test_at_threshold_gives_no_command(self):
        self.assertIsNone(decision.make_command("e1", 1000.0, READ_AT))

    def test_above_threshold_opens_damper_to_100(self):
        command = decision.make_command("e1", 1000.1, READ_AT)
        self.assertEqual(command.action, "HVAC_DAMPER_PCT")
        self.assertEqual(command.value, 100)
        self.assertEqual(command.event_id, "e1")

    def test_ttl_counts_from_the_reading(self):
        self.assertEqual(decision.make_command("e1", 1200, READ_AT).expires_at, READ_AT + 15.0)

    def test_expiry_boundary(self):
        expires_at = READ_AT + 15.0
        self.assertFalse(decision.is_expired(expires_at, READ_AT + 14.9))
        self.assertFalse(decision.is_expired(expires_at, READ_AT + 15.0))
        self.assertTrue(decision.is_expired(expires_at, READ_AT + 15.1))


class TestActuator(unittest.TestCase):
    def setUp(self):
        self.command = decision.make_command("event-1", 1200, READ_AT)

    def test_fresh_command_is_applied(self):
        outcome, _ = actuator.check_command(self.command, READ_AT + 1)
        self.assertEqual(outcome, actuator.APPLIED)

    def test_stale_command_is_rejected(self):
        outcome, reason = actuator.check_command(self.command, READ_AT + 16)
        self.assertEqual(outcome, actuator.EXPIRED)
        self.assertIn("expired", reason)


if __name__ == "__main__":
    unittest.main()
