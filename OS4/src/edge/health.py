"""HealthMon process: persist a health record for every worker (process_health table).

Per worker it stores the PID, status, CPU %, resident memory (RSS) and the
voluntary / involuntary context switches, read through psutil from /proc/<pid>.
  voluntary switch   - the process gave up the CPU itself (it waited for I/O, a queue, a sleep)
  involuntary switch - the scheduler took the CPU away (time slice used up, or a higher priority task)
A process that mostly waits (Ingest in epoll) shows many voluntary and few
involuntary switches; a CPU-hungry one shows the opposite.
"""

from __future__ import annotations

import json
import time
from typing import Any

import psutil

from edge import storage

HEALTH_EVERY_S = 10.0

# psutil.Process objects are kept: cpu_percent(interval=None) needs a previous
# call on the same object to return a meaningful value.
_CACHE: dict[int, psutil.Process] = {}


def process_metrics(pid: int | None, status: str | None) -> dict[str, Any]:
    """Metrics of one running worker, or Nones if it is not running / not readable."""
    empty = {"cpu_percent": None, "memory_mb": None, "ctx_voluntary": None, "ctx_involuntary": None}
    if not pid or status != "running":
        return empty
    try:
        process = _CACHE.get(pid)
        if process is None:
            process = _CACHE[pid] = psutil.Process(pid)
        switches = process.num_ctx_switches()
        return {
            "cpu_percent": process.cpu_percent(interval=None),
            "memory_mb": round(process.memory_info().rss / (1024 * 1024), 2),
            "ctx_voluntary": switches.voluntary,
            "ctx_involuntary": switches.involuntary,
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        _CACHE.pop(pid, None)
        return empty


def run_health_monitor(state: Any, stop_event: Any) -> None:
    while not stop_event.is_set():
        snapshot = dict(state)
        names = sorted(key.split(":", 1)[1] for key in snapshot if key.startswith("worker_status:"))
        for name in names:
            pid, status = snapshot.get(f"worker_pid:{name}"), snapshot.get(f"worker_status:{name}")
            details = {"pid": pid, **process_metrics(pid, status)}
            storage.save_process_health(name, status or "unknown", json.dumps(details))
        state["last_health_check"] = time.time()
        if stop_event.wait(HEALTH_EVERY_S):
            break
