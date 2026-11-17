"""OS1 bonus: resource trends, before/after comparison and CSV export."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edge.os1_bonus_trends.history import build_trends, compare, read_csv, to_csv  # noqa: E402


def sample(name, pid, t, cpu_s, voluntary, involuntary, rss_kb=2048):
    return {"name": name, "pid": pid, "wall": 1000.0 + t, "t": t, "cpu_s": cpu_s,
            "rss_kb": rss_kb, "voluntary_ctxt": voluntary, "involuntary_ctxt": involuntary}


SAMPLES = [
    sample("Processor", 10, 0.0, 1.0, 100, 10),
    sample("Processor", 10, 2.0, 1.1, 170, 14),    # +0.1 s CPU, +70 vol, +4 invol in 2 s
    sample("Processor", 10, 4.0, 1.3, 230, 44),    # +0.2 s CPU, +60 vol, +30 invol in 2 s
    sample("Actuator", 20, 0.0, 0.0, 0, 0),
    sample("Actuator", 21, 2.0, 0.0, 0, 0),        # restarted: new PID, no rate across it
]


class TestTrends(unittest.TestCase):
    def test_rates_between_consecutive_samples(self):
        points = build_trends(SAMPLES)["Processor"]
        self.assertEqual(len(points), 2)
        self.assertEqual(points[0], {"wall": 1002.0, "cpu_pct": 5.0, "rss_mb": 2.0,
                                     "voluntary_per_s": 35.0, "involuntary_per_s": 2.0})
        self.assertEqual(points[1]["involuntary_per_s"], 15.0)
        self.assertEqual(points[1]["cpu_pct"], 10.0)

    def test_no_rate_across_a_pid_change(self):
        self.assertNotIn("Actuator", build_trends(SAMPLES))

    def test_comparison_before_and_after_the_split(self):
        result = compare(build_trends(SAMPLES), split=1003.0)["Processor"]
        self.assertEqual(result["before"]["involuntary_per_s"], 2.0)
        self.assertEqual(result["after"]["involuntary_per_s"], 15.0)

    def test_empty_side_of_the_split_is_none(self):
        result = compare(build_trends(SAMPLES), split=0.0)["Processor"]
        self.assertIsNone(result["before"])

    def test_csv_manifest_reads_back_to_the_plotted_points(self):
        trends = build_trends(SAMPLES)
        manifest = to_csv({"trends": trends})
        self.assertTrue(manifest.startswith("process,time_utc,wall,cpu_pct"))
        self.assertEqual(read_csv(manifest), trends)


if __name__ == "__main__":
    unittest.main()
