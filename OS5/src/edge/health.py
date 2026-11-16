"""Health status rules shared by the OS5 monitor and local API."""

from collections.abc import Mapping
from time import time
from typing import Any

REQUIRED_WORKERS = (
    "SensorGen",
    "Processor",
    "HealthMon",
    "API",
    "Receiver",
    "SyncWorker",
)
HEARTBEAT_STALE_AFTER_SECONDS = 15


def build_readiness_report(
    heartbeats: Mapping[str, Mapping[str, Any]],
    *,
    database_ready: bool,
    database_error: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Report ready only when the database and all worker heartbeats are healthy."""
    checked_at = time() if now is None else now
    worker_checks: dict[str, dict[str, Any]] = {}

    for process_name in REQUIRED_WORKERS:
        heartbeat = heartbeats.get(process_name)
        if heartbeat is None:
            worker_checks[process_name] = {
                "status": "starting",
                "last_checked_at": None,
                "age_seconds": None,
            }
            continue

        status = heartbeat.get("status")
        timestamp = heartbeat.get("checked_at_epoch")
        age_seconds: float | None = None
        if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
            age_seconds = max(0.0, checked_at - timestamp)
            if age_seconds > HEARTBEAT_STALE_AFTER_SECONDS:
                status = "stale"
        elif status == "running":
            status = "unknown"

        worker_checks[process_name] = {
            "status": status if isinstance(status, str) else "unknown",
            "last_checked_at": heartbeat.get("checked_at"),
            "age_seconds": (
                round(age_seconds, 1) if age_seconds is not None else None
            ),
        }

    database_check: dict[str, Any] = {
        "status": "ready" if database_ready else "unavailable",
    }
    if database_error:
        database_check["error"] = database_error

    ready = database_ready and all(
        check["status"] == "running" for check in worker_checks.values()
    )
    return {
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "checks": {
            "database": database_check,
            "workers": worker_checks,
        },
    }
