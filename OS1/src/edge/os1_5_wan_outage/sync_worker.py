"""SyncWorker: sends the outbox to the upstream receiver, only while the WAN is up (OS1-5)."""

import json
from urllib.request import Request, urlopen

from edge.core import storage
from edge.node_config import RECEIVER_PORT

RECEIVER_URL = f"http://127.0.0.1:{RECEIVER_PORT}/api/events"
BATCH_SIZE = 50
IDLE_WAIT_S = 2


def deliver_event(event: dict) -> bool:
    """POST one event; True only if the receiver confirms it."""
    body = json.dumps({"event_id": event["event_id"], "payload": json.loads(event["payload"])}).encode()
    request = Request(RECEIVER_URL, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=3) as response:
            return json.load(response).get("event_id") == event["event_id"]
    except (OSError, ValueError):  # network error, timeout, bad reply
        return False


def run_sync_worker(channels, state) -> None:
    while not channels.stop.is_set():
        batch = storage.get_pending_events(BATCH_SIZE) if channels.wan_online.is_set() else []

        for event in batch:
            if channels.stop.is_set() or not channels.wan_online.is_set():
                break
            if deliver_event(event):
                storage.mark_sent(event["event_id"])
            else:
                storage.mark_failed_attempt(event["event_id"])  # stays pending, retried later
        state["pending_events"] = storage.count_pending_events()

        # Offline or nothing to send: wait a bit. Backlog: go on almost at once.
        channels.stop.wait(0.1 if batch else IDLE_WAIT_S)
