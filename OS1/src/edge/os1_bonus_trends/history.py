"""
OS1 bonus (Phase 3 / Optional of the assessment): resource trends over time,
a before/after comparison, and a CSV export.

The dashboard chart and the CSV file are both built by build_history() from the
same process_health rows, so the plotted values and the exported file always agree.
"""

import csv
import io
import json
import time
from datetime import datetime, timezone

from edge.core import storage

METRICS = ("cpu_pct", "rss_mb", "voluntary_per_s", "involuntary_per_s")


def load_samples(since, until):
    """The /proc samples written by ProcSampler between two wall-clock times."""
    rows = storage.execute(
        "SELECT process_name, details FROM process_health "
        "WHERE status = 'sampled' AND checked_at >= datetime(?, 'unixepoch') ORDER BY health_id",
        (since - 5,),  # checked_at has 1 s precision: take a small margin, filter exactly below
    )
    samples = [{"name": name, **json.loads(details)} for name, details in rows]
    return [sample for sample in samples if since <= sample["wall"] <= until]


def build_trends(samples):
    """
    One point per pair of consecutive samples of the same process:
    a rate (CPU %, switches per second) needs two readings of the counters.
    """
    trends = {}
    previous = {}
    for sample in samples:
        name = sample["name"]
        before = previous.get(name)
        previous[name] = sample
        if before is None or before["pid"] != sample["pid"]:
            continue  # first sample of this process, or a new process with the same name
        elapsed = sample["t"] - before["t"]
        if elapsed <= 0:
            continue
        trends.setdefault(name, []).append({
            "wall": round(sample["wall"], 3),
            "cpu_pct": round(100 * (sample["cpu_s"] - before["cpu_s"]) / elapsed, 1),
            "rss_mb": round(sample["rss_kb"] / 1024, 2),
            "voluntary_per_s": round((sample["voluntary_ctxt"] - before["voluntary_ctxt"]) / elapsed, 1),
            "involuntary_per_s": round((sample["involuntary_ctxt"] - before["involuntary_ctxt"]) / elapsed, 1),
        })
    return trends


def average(points):
    if not points:
        return None
    return {metric: round(sum(point[metric] for point in points) / len(points), 2) for metric in METRICS}


def compare(trends, split):
    """Per process: the average of each metric before and after `split` (wall-clock time)."""
    return {
        name: {
            "before": average([point for point in points if point["wall"] < split]),
            "after": average([point for point in points if point["wall"] >= split]),
        }
        for name, points in trends.items()
    }


def build_history(minutes=5, since=None, until=None, split=None):
    """
    Default: the last 2 x `minutes`, compared as "previous window" vs "last window".
    A scenario can give exact times instead (for example idle start, load start, load end).
    """
    until = until if until is not None else time.time()
    since = since if since is not None else until - 2 * minutes * 60
    split = split if split is not None else until - minutes * 60
    trends = build_trends(load_samples(since, until))
    return {"since": since, "until": until, "split": split,
            "trends": trends, "comparison": compare(trends, split)}


def to_csv(history):
    """The exported manifest: exactly the points that the chart plots."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["process", "time_utc", "wall", *METRICS])
    for name, points in sorted(history["trends"].items()):
        for point in points:
            time_utc = datetime.fromtimestamp(point["wall"], timezone.utc).isoformat(timespec="seconds")
            writer.writerow([name, time_utc, point["wall"], *(point[metric] for metric in METRICS)])
    return output.getvalue()


def read_csv(text):
    """Read an exported manifest back into the same shape as history["trends"]."""
    trends = {}
    for row in csv.DictReader(io.StringIO(text)):
        trends.setdefault(row["process"], []).append(
            {"wall": float(row["wall"]), **{metric: float(row[metric]) for metric in METRICS}}
        )
    return trends
