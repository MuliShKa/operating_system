"""Drain the durable local outbox to the configured upstream receiver."""

import logging
from multiprocessing.synchronize import Event

from edge import storage
from edge.config import NodeConfig
from edge.unix_socket import UnixMessageClient

SYNC_RETRY_INTERVAL_S = 0.5
UPSTREAM_REQUEST_TIMEOUT_S = 2.0

log = logging.getLogger(__name__)


def _acknowledged_ids(response: dict[str, object], batch_ids: set[str]) -> list[str]:
    if "error" in response:
        raise ValueError(f"upstream rejected batch: {response['error']}")
    acknowledged = response.get("acknowledged")
    if not isinstance(acknowledged, list) or not all(
        isinstance(event_id, str) for event_id in acknowledged
    ):
        raise ValueError("upstream response must contain an acknowledged ID list")
    if len(set(acknowledged)) != len(acknowledged):
        raise ValueError("upstream response contains duplicate event IDs")
    if not set(acknowledged).issubset(batch_ids):
        raise ValueError("upstream acknowledged an event outside the sent batch")
    return acknowledged


def run_sync_worker(stop_event: Event, config: NodeConfig) -> None:
    """Retry batches until stopped; mark events sent only after receiver ACKs."""
    client = UnixMessageClient(
        config.upstream_socket, timeout=UPSTREAM_REQUEST_TIMEOUT_S
    )
    receiver_unavailable = False

    while not stop_event.is_set():
        events = storage.pending_events(config.database, config.sync_batch_size)
        if events:
            batch_ids = {event["event_id"] for event in events}
            try:
                response = client.request({"cmd": "deliver", "events": events})
                acknowledged = _acknowledged_ids(response, batch_ids)
            except (OSError, ValueError) as error:
                if not receiver_unavailable:
                    log.warning("upstream unavailable; outbox retained: %s", error)
                receiver_unavailable = True
            else:
                sent_count = storage.mark_sent(config.database, acknowledged)
                receiver_unavailable = False
                log.info(
                    "upstream acknowledged %d of %d outbox events",
                    sent_count,
                    len(events),
                )
        stop_event.wait(SYNC_RETRY_INTERVAL_S)
