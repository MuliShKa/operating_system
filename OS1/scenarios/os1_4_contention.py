"""
OS1-4: measure RSS and context switches of every worker, idle then under CPU load.

The node's ProcSampler worker reads /proc/[pid]/stat and /proc/[pid]/status
every 2.0 s and writes one process_health row per worker. This scenario
only adds load and reads those rows back.

Usage: python scenarios/os1_4_contention.py [--seconds 30] [--burners N]
"""

import argparse
import json
import multiprocessing as mp
import os
import sqlite3
import statistics
import time
from contextlib import closing

import node_runner

SAMPLE_PERIOD_S = 2.0


def burn_cpu(stop) -> None:
    """Synthetic load: keep one CPU busy until told to stop."""
    while not stop.is_set():
        sum(number * number for number in range(10_000))


def read_samples(run_dir) -> list[dict]:
    with closing(sqlite3.connect(run_dir / "node.db")) as connection:
        rows = connection.execute(
            "SELECT process_name, details FROM process_health WHERE status = 'sampled'"
        ).fetchall()
    return [{"name": name, **json.loads(details)} for name, details in rows]


def summarize(samples: list[dict], start: float, end: float) -> dict[str, dict]:
    """Per-worker rates between the first and last sample inside [start, end]."""
    by_worker: dict[str, list[dict]] = {}
    for sample in samples:
        if start <= sample["wall"] <= end:
            by_worker.setdefault(sample["name"], []).append(sample)

    summary = {}
    for name, rows in sorted(by_worker.items()):
        rows.sort(key=lambda row: row["t"])
        first, last = rows[0], rows[-1]
        elapsed = last["t"] - first["t"]
        if elapsed <= 0:
            continue
        summary[name] = {
            "samples": len(rows),
            "cpu_pct": round((last["cpu_s"] - first["cpu_s"]) / elapsed * 100, 1),
            "max_rss_kb": max(row["rss_kb"] for row in rows),
            "voluntary_per_s": round((last["voluntary_ctxt"] - first["voluntary_ctxt"]) / elapsed, 1),
            "involuntary_per_s": round((last["involuntary_ctxt"] - first["involuntary_ctxt"]) / elapsed, 1),
            "median_period_s": round(statistics.median(
                b["t"] - a["t"] for a, b in zip(rows, rows[1:])
            ), 2),
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seconds", type=float, default=30, help="length of each phase")
    parser.add_argument("--burners", type=int, default=(os.cpu_count() or 1) * 2)
    args = parser.parse_args()

    run_dir = node_runner.new_run_dir("os1_4")
    with node_runner.running_node(run_dir):
        workers = node_runner.running_workers(node_runner.get_status())

        print(f"Idle phase: {args.seconds:g} s")
        idle_start = time.time()
        time.sleep(args.seconds)
        idle_end = time.time()

        print(f"Load phase: {args.seconds:g} s, {args.burners} CPU burners")
        stop = mp.Event()
        burners = [mp.Process(target=burn_cpu, args=(stop,)) for _ in range(args.burners)]
        for burner in burners:
            burner.start()
        load_start = time.time()
        try:
            time.sleep(args.seconds)
        finally:
            load_end = time.time()
            stop.set()
            for burner in burners:
                burner.join()

    samples = read_samples(run_dir)
    idle = summarize(samples, idle_start, idle_end)
    load = summarize(samples, load_start, load_end)

    print(f"{'worker':<12}{'phase':<6}{'cpu%':>7}{'rss kB':>10}{'vol/s':>8}{'invol/s':>9}{'period':>8}")
    for name in sorted(workers):
        for phase, table in (("idle", idle), ("load", load)):
            row = table.get(name)
            if row:
                print(f"{name:<12}{phase:<6}{row['cpu_pct']:>7}{row['max_rss_kb']:>10}"
                      f"{row['voluntary_per_s']:>8}{row['involuntary_per_s']:>9}{row['median_period_s']:>8}")

    periods = [row["median_period_s"] for table in (idle, load) for row in table.values()]
    checks = {
        "every worker sampled in both phases": set(idle) == set(load) == set(workers),
        "samples every 2.0 s (median within 0.2 s)":
            bool(periods) and all(abs(p - SAMPLE_PERIOD_S) <= 0.2 for p in periods),
        "load raised involuntary context switches overall":
            sum(r["involuntary_per_s"] for r in load.values())
            > sum(r["involuntary_per_s"] for r in idle.values()),
    }
    report = {
        "scenario": "OS1-4", "seconds_per_phase": args.seconds, "burners": args.burners,
        "rows_in_process_health": len(samples), "idle": idle, "load": load, "checks": checks,
    }
    path = node_runner.write_report(run_dir, report)
    passed = node_runner.print_checks(checks)
    print(f"Report: {path}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
