"""OS1-4: sample every worker from /proc every 2.0 s into process_health."""

from __future__ import annotations

import json
import time
from typing import Any

from edge import storage
from edge.node_config import SAMPLE_PERIOD_S
from edge.proc_stats import read_process


def worker_pids(state: Any) -> dict[str, int]:
    """Return {worker name: PID} for the workers reported as running."""
    snapshot = dict(state)
    pids = {}
    for key, status in snapshot.items():
        if not key.startswith("worker_status:") or status != "running":
            continue
        name = key.split(":", 1)[1]
        pid = snapshot.get(f"worker_pid:{name}")
        if pid:
            pids[name] = pid
    return pids


def sample_once(state: Any) -> list[dict]:
    """Read /proc for every running worker and save one row per worker."""
    samples = []
    for name, pid in worker_pids(state).items():
        try:
            sample = {"wall": time.time(), "t": time.monotonic(), **read_process(pid)}
        except OSError:
            # The process has gone between reading the state and reading /proc.
            storage.save_process_health(name, "missing", json.dumps({"pid": pid}))
            continue
        storage.save_process_health(name, "sampled", json.dumps(sample))
        samples.append({"name": name, **sample})
    return samples


def run_proc_sampler(channels: Any, state: Any) -> None:
    # A fixed monotonic schedule: a slow sample does not shift the next ones.
    next_sample = time.monotonic()
    while not channels.stop.is_set():
        samples = sample_once(state)
        state["proc_samples"] = {row.pop("name"): row for row in samples}
        next_sample += SAMPLE_PERIOD_S
        if channels.stop.wait(max(0.0, next_sample - time.monotonic())):
            break
