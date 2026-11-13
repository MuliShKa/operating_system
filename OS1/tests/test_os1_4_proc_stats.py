"""OS1-4: /proc parsing and the sampler writing to process_health."""

import json
import multiprocessing
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edge import proc_sampler, storage  # noqa: E402
from edge.proc_stats import parse_context_switches, parse_stat, read_process  # noqa: E402

# A /proc/[pid]/stat line whose name contains spaces and brackets.
STAT = "42 (my (odd) name) S 1 42 42 0 -1 4194560 100 0 0 0 250 50 0 0 20 0 3 0 99 1000 512"
STATUS = "Name:\tx\nvoluntary_ctxt_switches:\t17\nnonvoluntary_ctxt_switches:\t4\n"


class TestProcParsing(unittest.TestCase):
    def test_name_with_spaces_and_brackets_does_not_shift_fields(self):
        stat = parse_stat(STAT)
        self.assertEqual(stat["state"], "S")
        self.assertEqual(stat["threads"], 3)
        self.assertEqual(stat["rss_kb"], 512 * os.sysconf("SC_PAGE_SIZE") // 1024)
        self.assertAlmostEqual(stat["cpu_s"], 300 / os.sysconf("SC_CLK_TCK"))

    def test_context_switches_come_from_status(self):
        self.assertEqual(
            parse_context_switches(STATUS),
            {"voluntary_ctxt": 17, "involuntary_ctxt": 4},
        )

    def test_reads_a_real_process(self):
        sample = read_process(os.getpid())
        self.assertGreater(sample["rss_kb"], 0)
        self.assertGreaterEqual(sample["voluntary_ctxt"], 0)

    def test_process_gone_raises_oserror(self):
        with self.assertRaises(OSError):
            read_process(2**22 + 1)


class TestSampler(unittest.TestCase):
    def test_one_row_per_running_worker(self):
        original = storage.DATABASE_PATH
        with tempfile.TemporaryDirectory() as folder:
            try:
                storage.DATABASE_PATH = Path(folder) / "node.db"
                storage.initialize_database()
                state = {
                    "worker_status:Me": "running", "worker_pid:Me": os.getpid(),
                    "worker_status:Gone": "running", "worker_pid:Gone": 2**22 + 1,
                    "worker_status:Off": "stopped", "worker_pid:Off": os.getpid(),
                }
                samples = proc_sampler.sample_once(state)

                with closing(sqlite3.connect(storage.DATABASE_PATH)) as connection:
                    rows = connection.execute(
                        "SELECT process_name, status, details FROM process_health ORDER BY process_name"
                    ).fetchall()
            finally:
                storage.DATABASE_PATH = original

        self.assertEqual([s["name"] for s in samples], ["Me"])
        self.assertEqual([(r[0], r[1]) for r in rows], [("Gone", "missing"), ("Me", "sampled")])
        details = json.loads(rows[1][2])
        for key in ("wall", "t", "pid", "rss_kb", "voluntary_ctxt", "involuntary_ctxt"):
            self.assertIn(key, details)


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn")
    unittest.main()
