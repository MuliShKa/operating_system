"""Tests for the Actuator: freshness check with its own monotonic clock.

Run: PYTHONPATH=src python3 tests/test_actuator.py -v
"""

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edge import actuator, decision, storage  # noqa: E402
from edge.models import ActuatorCommand  # noqa: E402


def make_command(event_id: str, expires_at: float, value: float = 30) -> ActuatorCommand:
    return ActuatorCommand(
        event_id=event_id,
        action="VARIABLE_SPEED_SIGN_KMH",
        value=value,
        expires_at=expires_at,
        reason="test surge",
    )


class TestSignActuator(unittest.TestCase):
    def setUp(self) -> None:
        self.original_path = storage.DATABASE_PATH
        self.tmp = tempfile.TemporaryDirectory()
        storage.DATABASE_PATH = Path(self.tmp.name) / "test.db"
        storage.initialize_database()
        # decisions.event_id is a foreign key: the commands refer to stored events.
        for event_id in ("e1", "e2", "e3"):
            storage.save_event(event_id, "PED_CROSSWALK_COUNT", "2026-01-01T00:00:00+00:00", {"v": 1})
        self.state: dict = {}
        self.actuator = actuator.SignActuator(self.state)
        self.actuator.start()

    def tearDown(self) -> None:
        storage.DATABASE_PATH = self.original_path
        self.tmp.cleanup()

    def decision_types(self) -> list[str]:
        with closing(sqlite3.connect(storage.DATABASE_PATH)) as connection:
            return [row[0] for row in connection.execute(
                "SELECT decision_type FROM decisions ORDER BY decision_id")]

    def test_fresh_command_moves_the_sign(self) -> None:
        outcome = self.actuator.handle(make_command("e1", expires_at=110.0), now=100.0)
        self.assertEqual(outcome, actuator.APPLIED)
        self.assertEqual(storage.get_sign_state()["speed_limit_kmh"], 30)
        self.assertTrue(self.state["sign_state"]["surge_active"])

    def test_stale_command_is_rejected_and_the_sign_does_not_move(self) -> None:
        outcome = self.actuator.handle(make_command("e1", expires_at=100.0), now=116.0)
        self.assertEqual(outcome, actuator.EXPIRED)
        self.assertEqual(storage.get_sign_state()["speed_limit_kmh"], 50)
        self.assertEqual(storage.get_sign_state()["version"], 0)
        self.assertEqual(self.state["actuator_expired"], 1)
        self.assertEqual(self.decision_types(), [actuator.EXPIRED])

    def test_command_exactly_at_its_deadline_is_still_valid(self) -> None:
        outcome = self.actuator.handle(make_command("e1", expires_at=100.0), now=100.0)
        self.assertEqual(outcome, actuator.APPLIED)

    def test_second_command_during_a_surge_only_refreshes_the_deadline(self) -> None:
        self.actuator.handle(make_command("e1", expires_at=110.0), now=100.0)
        outcome = self.actuator.handle(make_command("e2", expires_at=111.0), now=101.0)
        self.assertEqual(outcome, actuator.REFRESHED)
        self.assertEqual(storage.get_sign_state()["version"], 1)   # no extra version bump
        self.assertEqual(self.actuator.active_until, 111.0)
        self.assertEqual(self.decision_types(), [actuator.APPLIED])

    def test_sign_is_restored_only_after_the_last_deadline(self) -> None:
        self.actuator.handle(make_command("e1", expires_at=110.0), now=100.0)
        self.actuator.handle(make_command("e2", expires_at=111.0), now=101.0)
        self.assertFalse(self.actuator.tick(now=110.5))   # first deadline passed, latest not yet
        self.assertEqual(storage.get_sign_state()["speed_limit_kmh"], 30)
        self.assertTrue(self.actuator.tick(now=111.5))
        self.assertEqual(storage.get_sign_state()["speed_limit_kmh"], decision.SPEED_LIMIT_NORMAL)
        self.assertFalse(self.state["sign_state"]["surge_active"])
        self.assertEqual(self.decision_types(), [actuator.APPLIED, actuator.RESTORED])

    def test_tick_without_an_active_command_does_nothing(self) -> None:
        self.assertFalse(self.actuator.tick(now=1_000.0))
        self.assertEqual(storage.get_sign_state()["version"], 0)

    def test_startup_resets_a_stale_surge_sign(self) -> None:
        storage.update_sign_state(30, expected_version=0)   # left over from a previous run
        fresh = actuator.SignActuator({})
        fresh.start()
        self.assertEqual(storage.get_sign_state()["speed_limit_kmh"], decision.SPEED_LIMIT_NORMAL)


if __name__ == "__main__":
    unittest.main()
