"""
OS1 bonus (assessment Phase 3 / Optional): resource trends and historical comparison.

The node runs idle, then under CPU load. The scenario then downloads, for the
same time range:
  /api/history      what the dashboard plots (trends + idle vs load comparison)
  /api/history.csv  the exported manifest
and checks that the plotted metrics agree with the exported manifest.
It also draws trends.svg (involuntary context switches over time).

Usage: python scenarios/os1_bonus_trends.py [--seconds 30] [--burners N]
"""

import argparse
import json
import multiprocessing as mp
import os
import sys
import time

import node_runner

sys.path.insert(0, str(node_runner.OS1_DIR / "src"))
from edge.os1_bonus_trends.history import read_csv  # noqa: E402

SAMPLE_PERIOD_S = 2.0
COLORS = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2", "#ca8a04", "#475569"]


def burn_cpu(stop) -> None:
    """Synthetic load: keep one CPU busy until told to stop."""
    while not stop.is_set():
        sum(number * number for number in range(10_000))


def write_svg(history: dict, metric: str, path) -> None:
    """A small line chart, one line per worker, with the idle / load boundary."""
    left, right, top, bottom = 50, 760, 20, 260
    since, until, split = history["since"], history["until"], history["split"]
    trends = history["trends"]
    top_value = max([1.0] + [point[metric] for points in trends.values() for point in points])

    def x(wall):
        return left + (wall - since) / (until - since) * (right - left)

    def y(value):
        return bottom - value / top_value * (bottom - top)

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 300" font-family="sans-serif" font-size="12">',
        '<rect width="900" height="300" fill="white"/>',
        f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#94a3b8"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="#94a3b8"/>',
        f'<text x="{left - 6}" y="{top + 10}" text-anchor="end">{top_value:.1f}</text>',
        f'<text x="{left - 6}" y="{bottom}" text-anchor="end">0</text>',
        f'<line x1="{x(split):.1f}" y1="{top}" x2="{x(split):.1f}" y2="{bottom}" stroke="#64748b" stroke-dasharray="4 4"/>',
        f'<text x="{(left + x(split)) / 2:.1f}" y="{bottom + 20}" text-anchor="middle">idle</text>',
        f'<text x="{(x(split) + right) / 2:.1f}" y="{bottom + 20}" text-anchor="middle">CPU load</text>',
        f'<text x="{left}" y="{top - 6}">{metric}</text>',
    ]
    for index, name in enumerate(sorted(trends)):
        color = COLORS[index % len(COLORS)]
        points = " ".join(f"{x(p['wall']):.1f},{y(p[metric]):.1f}" for p in trends[name])
        parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2"/>')
        parts.append(f'<text x="{right + 15}" y="{top + 15 + 18 * index}" fill="{color}">{name}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seconds", type=float, default=30, help="length of each phase")
    parser.add_argument("--burners", type=int, default=(os.cpu_count() or 1) * 2)
    args = parser.parse_args()

    run_dir = node_runner.new_run_dir("os1_bonus")
    node = node_runner.start_node(run_dir)
    try:
        print(f"Idle phase: {args.seconds:g} s")
        idle_start = time.time()
        time.sleep(args.seconds)

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

        time.sleep(SAMPLE_PERIOD_S)  # let the last sample of the load phase be written
        query = f"since={idle_start}&until={load_end}&split={load_start}"
        history = json.loads(node_runner.api_get(f"/api/history?{query}"))
        manifest = node_runner.api_get(f"/api/history.csv?{query}")
    finally:
        node_runner.stop_node(node)

    (run_dir / "trends.csv").write_text(manifest, encoding="utf-8")
    write_svg(history, "involuntary_per_s", run_dir / "trends.svg")
    comparison = history["comparison"]

    print(f"{'worker':<12}{'invol/s idle':>14}{'invol/s load':>14}{'cpu% idle':>11}{'cpu% load':>11}")
    for name, row in sorted(comparison.items()):
        idle, load = row["before"] or {}, row["after"] or {}
        print(f"{name:<12}{idle.get('involuntary_per_s', '-'):>14}{load.get('involuntary_per_s', '-'):>14}"
              f"{idle.get('cpu_pct', '-'):>11}{load.get('cpu_pct', '-'):>11}")

    def total(side):
        return sum((row[side] or {}).get("involuntary_per_s", 0) for row in comparison.values())

    checks = {
        "every worker has a trend": len(history["trends"]) == node_runner.EXPECTED_WORKERS,
        "plotted metrics agree with the exported CSV manifest":
            bool(history["trends"]) and read_csv(manifest) == history["trends"],
        "comparison: more involuntary switches under load": total("after") > total("before"),
    }
    report = {
        "scenario": "OS1-bonus", "seconds_per_phase": args.seconds, "burners": args.burners,
        "trend_points": sum(len(points) for points in history["trends"].values()),
        "comparison_idle_vs_load": comparison, "checks": checks,
    }
    path = node_runner.write_report(run_dir, report)
    passed = node_runner.print_checks(checks)
    print(f"Report: {path}  ·  chart: {run_dir / 'trends.svg'}  ·  manifest: {run_dir / 'trends.csv'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
