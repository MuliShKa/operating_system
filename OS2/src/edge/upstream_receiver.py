"""Optional local upstream receiver for offline-sync demonstrations."""

import logging
import multiprocessing as mp
import signal
import sqlite3
from multiprocessing.synchronize import Event
from pathlib import Path

from edge import storage
from edge.config import load_config
from edge.unix_socket import UnixMessageServer

log = logging.getLogger(__name__)


def run_upstream_receiver(
    stop_event: Event, socket_path: str | Path, database_path: str | Path
) -> None:
    """Receive idempotent event batches until the receiver is stopped."""
    storage.init_upstream_db(database_path)
    wan_online = True

    def handle(message: dict[str, object]) -> dict[str, object]:
        nonlocal wan_online
        if message.get("cmd") == "status":
            return {
                "received": storage.upstream_event_count(database_path),
                "wan_online": wan_online,
            }
        if message.get("cmd") == "contains":
            event_ids = message.get("event_ids")
            if not isinstance(event_ids, list) or not all(
                isinstance(event_id, str) for event_id in event_ids
            ):
                return {"error": "event_ids must be a list of strings"}
            try:
                present = storage.upstream_contains_events(database_path, event_ids)
            except sqlite3.Error as error:
                log.exception("failed to inspect upstream event IDs")
                return {"error": f"upstream storage error: {error}"}
            return {"present": present}
        if message.get("cmd") == "network":
            online = message.get("online")
            if not isinstance(online, bool):
                return {"error": "online must be a boolean"}
            wan_online = online
            return {"wan_online": wan_online}
        if message.get("cmd") != "deliver":
            return {"error": "unsupported command"}
        if not wan_online:
            return {"error": "simulated WAN is offline"}
        events = message.get("events")
        if not isinstance(events, list):
            return {"error": "events must be a list"}
        try:
            acknowledged = storage.accept_upstream_events(database_path, events)
        except ValueError as error:
            return {"error": str(error)}
        except sqlite3.Error as error:
            log.exception("failed to persist upstream event batch")
            return {"error": f"upstream storage error: {error}"}
        return {"acknowledged": acknowledged}

    with UnixMessageServer(socket_path, handle):
        log.info("upstream receiver listening at %s", socket_path)
        stop_event.wait()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(processName)s %(levelname)s %(message)s",
    )
    config = load_config()
    stop_event = mp.get_context("spawn").Event()

    def handle_signal(signum: int, _frame: object) -> None:
        log.info("received signal %s; stopping upstream receiver", signum)
        stop_event.set()

    previous_handlers = {
        signum: signal.signal(signum, handle_signal)
        for signum in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        run_upstream_receiver(
            stop_event, config.upstream_socket, config.upstream_database
        )
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
