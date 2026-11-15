"""OS1-4: ProcSampler worker. Reads /proc for every worker every 2.0 s into process_health."""

import json
import time

from edge.core import storage
from edge.core.ipc import list_workers
from edge.node_config import SAMPLE_PERIOD_S
from edge.os1_4_contention.proc_stats import read_process


def sample_once(state) -> list[dict]:
    """Read /proc for every running worker and save one row per worker."""
    samples = []
    for name, worker in list_workers(state).items():
        if worker["status"] != "running":
            continue
        try:
            sample = {"wall": time.time(), "t": time.monotonic(), **read_process(worker["pid"])}
        except OSError:  # the process has gone in the meantime
            storage.save_process_health(name, "missing", json.dumps({"pid": worker["pid"]}))
            continue
        storage.save_process_health(name, "sampled", json.dumps(sample))
        samples.append({"name": name, **sample})
    return samples


def run_proc_sampler(channels, state) -> None:
    previous = {}
    next_sample = time.monotonic()
    while not channels.stop.is_set():
        latest = {}
        for sample in sample_once(state):
            name = sample.pop("name")
            # CPU % = CPU seconds used since the last sample / seconds elapsed.
            before = previous.get(name)
            if before and before["pid"] == sample["pid"]:
                sample["cpu_pct"] = round(100 * (sample["cpu_s"] - before["cpu_s"]) / (sample["t"] - before["t"]), 1)
            latest[name] = sample
        state["proc_samples"] = previous = latest

        # Fixed schedule on the monotonic clock: a slow sample does not shift the next ones.
        next_sample += SAMPLE_PERIOD_S
        channels.stop.wait(max(0.0, next_sample - time.monotonic()))
