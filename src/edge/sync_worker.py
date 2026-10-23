"""Deliver pending outbox events to the mock upstream receiver."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from edge import storage


# need to ask: put this in node.yaml? for now it's hardcoded like the API port
RECEIVER_URL = "http://127.0.0.1:8001/api/events"
BATCH_SIZE = 50
RETRY_INTERVAL_SECONDS = 2
REQUEST_TIMEOUT_SECONDS = 3


def deliver_event(event: dict[str, Any]) -> bool:
    """Send one event and confirm that the receiver accepted it."""
    try:
        request_body = json.dumps({
            "event_id": event["event_id"],
            "payload": json.loads(event["payload"]),
        }).encode("utf-8")

        request = Request(
            RECEIVER_URL,
            data=request_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                return False

            result = json.loads(response.read().decode("utf-8"))

        return (
            result.get("accepted") is True
            and result.get("event_id") == event["event_id"]
        )

    except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError, TypeError):
        return False


def run_sync_worker(channels: Any, state: Any) -> None:
    """Drain the outbox while the simulated WAN is online."""
    while not channels.stop.is_set():
        if not channels.wan_online.is_set():
            if channels.stop.wait(RETRY_INTERVAL_SECONDS):
                break
            continue

        events = storage.get_pending_events(limit=BATCH_SIZE)

        if not events:
            state["pending_events"] = storage.get_pending_event_count()
            if channels.stop.wait(RETRY_INTERVAL_SECONDS):
                break
            continue

        delivered = True
        for event in events:
            if channels.stop.is_set():
                break

            if not channels.wan_online.is_set():
                break

            delivered = deliver_event(event)
            if delivered:
                storage.mark_event_sent(event["event_id"])
            else:
                storage.mark_event_attempt(event["event_id"])

            state["pending_events"] = storage.get_pending_event_count()

            if not delivered:
                # upstream is down, no point trying the rest of the batch now
                break

        pause = 0.1 if delivered else RETRY_INTERVAL_SECONDS
        if channels.stop.wait(pause):
            break
