"""Unit tests: mist rule, quiet-night policy, TTL, AirKorea baseline.

Run: python tests/test_decision_and_baseline.py -v
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

os.environ.setdefault("EDGE_SOCKET_DIR", f"/tmp/songdo-os4-test-{os.getpid()}")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edge import baseline, decision  # noqa: E402


class TestMistRule(unittest.TestCase):
    def test_threshold_is_strictly_greater_than_50(self) -> None:
        self.assertEqual(decision.evaluate_mist(50.0, 0.0).kind, decision.NONE)
        self.assertEqual(decision.evaluate_mist(50.1, 0.0).kind, decision.DISPATCH)

    def test_ttl_counts_from_the_sensor_reading(self) -> None:
        verdict = decision.evaluate_mist(60.0, observed_mono=100.0)
        self.assertEqual(verdict.expires_at, 100.0 + decision.COMMAND_TTL)
        self.assertEqual(decision.COMMAND_TTL, 30.0)       # handbook

    def test_expiry_check(self) -> None:
        self.assertFalse(decision.is_command_expired(130.0, now=130.0))
        self.assertTrue(decision.is_command_expired(130.0, now=130.1))
        self.assertTrue(decision.is_command_expired(None))

    def test_quiet_night_holds_bad_but_not_very_bad(self) -> None:
        self.assertEqual(decision.evaluate_mist(60.0, 0.0, lux=3.0, noise_db=38.0).kind, decision.HOLD)
        very_bad = decision.evaluate_mist(80.0, 0.0, lux=3.0, noise_db=38.0)
        self.assertEqual(very_bad.kind, decision.DISPATCH)
        self.assertIn("override", very_bad.reason)

    def test_daylight_or_noise_or_missing_context_never_blocks(self) -> None:
        self.assertEqual(decision.evaluate_mist(60.0, 0.0, lux=400.0, noise_db=38.0).kind, decision.DISPATCH)
        self.assertEqual(decision.evaluate_mist(60.0, 0.0, lux=3.0, noise_db=60.0).kind, decision.DISPATCH)
        self.assertEqual(decision.evaluate_mist(60.0, 0.0, lux=None, noise_db=38.0).kind, decision.DISPATCH)
        self.assertEqual(decision.evaluate_mist(60.0, 0.0).kind, decision.DISPATCH)


class TestBaseline(unittest.TestCase):
    def write(self, text: str) -> Path:
        folder = Path(tempfile.mkdtemp())
        path = folder / "b.csv"
        path.write_text(text, encoding="utf-8")
        return path

    def test_grades(self) -> None:
        self.assertEqual([baseline.pm25_grade(v) for v in (10, 15, 16, 35, 36, 75, 76)],
                         ["GOOD", "GOOD", "NORMAL", "NORMAL", "BAD", "BAD", "VERY_BAD"])

    def test_exact_hour_and_hour_of_day_lookup(self) -> None:
        path = self.write("datetime,pm25\n2026-11-16 20:00,30\n2026-11-15 21:00,10\n2026-11-16 21:00,20\n")
        base = baseline.load_baseline("131233", path, Path("/nonexistent"))
        t20 = datetime(2026, 11, 16, 20, 30, tzinfo=baseline.KST).timestamp()
        self.assertEqual(base.lookup(t20), (30.0, "exact-hour"))
        other_day = datetime(2026, 11, 20, 21, 5, tzinfo=baseline.KST).timestamp()
        self.assertEqual(base.lookup(other_day), (15.0, "hour-of-day"))   # mean of 10 and 20

    def test_bad_rows_are_counted_not_silent_and_24h_is_midnight(self) -> None:
        path = self.write("datetime,pm25\n2026-11-16 24:00,12\n2026-11-16 03:00,-\n2026-11-16 04:00,\nnonsense,5\n")
        base = baseline.load_baseline("131233", path, Path("/nonexistent"))
        self.assertEqual((base.rows_read, base.rows_skipped), (4, 3))
        self.assertIn("2026-11-17 00", base.by_hour)

    def test_falls_back_to_sample_and_flags_it(self) -> None:
        sample = self.write("datetime,pm25\n2026-11-15 00:00,16\n")
        base = baseline.load_baseline("131233", Path("/nonexistent.csv"), sample)
        self.assertTrue(base.is_sample)
        empty = baseline.load_baseline("131233", Path("/a"), Path("/b"))
        self.assertFalse(empty.available)
        self.assertIsNone(empty.lookup(0))

    def test_compare(self) -> None:
        self.assertEqual(baseline.compare(24.0, 22.0, 15)["status"], "AGREE")
        result = baseline.compare(60.0, 22.0, 15)
        self.assertEqual((result["status"], result["bias"], result["local_grade"], result["baseline_grade"]),
                         ("DEVIATES", 38.0, "BAD", "NORMAL"))


if __name__ == "__main__":
    unittest.main()
