"""Ingest process: ONE process listens to all sensors without blocking (scenario OS4-1).

The three devices send datagrams to three Unix domain sockets. This process owns
the receiving ends and watches them all with a single `selectors` object, which
on Linux is the kernel's epoll:

    sel.select(timeout)  ->  "these sockets have data"  ->  read each until
                              it would block (BlockingIOError)  ->  select again

Why this and not one thread per sensor or a loop that polls each socket in turn:
  - nothing blocks on a quiet sensor, so a silent device cannot stall the others;
  - the process sleeps inside epoll_wait while idle (about 0% CPU), no busy loop;
  - one process, one fd table: easy to inspect (ls -l /proc/<pid>/fd, ss -xlp).

Fairness: at most MAX_PER_WAKEUP datagrams are read from one socket per wakeup,
so a chatty sensor cannot starve the others.

This process only does I/O and validation. It stamps the receipt time on every
datagram and passes it on; the meaning (ordering, rules) is the Processor's job.
"""

from __future__ import annotations

import os
import selectors
import socket
import time
from typing import Any

from edge.config import SOCKET_DIR
from edge.models import SensorEvent
from edge.sensors import RejectedReading, SensorSpec, load_specs

MAX_PER_WAKEUP = 64
RECV_BYTES = 4096
PUBLISH_EVERY_S = 1.0


def make_event(spec: SensorSpec, raw: bytes, received_at: float, received_mono: float) -> SensorEvent:
    """
    Turn one raw datagram into a SensorEvent, or raise.

    ValueError          - the bytes are not a valid message of this device
    RejectedReading     - valid message, physically impossible value (NaN, -5 ug/m3, 5000 ug/m3 ...)

    Event time -> monotonic: the reading says "I was measured at wall time T".
    We convert that ONCE, now, into our monotonic clock:
        observed_mono = received_mono - (received_at - observed_at)
    After this, nothing downstream looks at a wall clock again. A device clock
    ahead of ours (negative age) is clamped to "measured just now".
    """
    value, observed_at = spec.parse(raw)
    spec.check_range(value)
    age = max(0.0, received_at - observed_at)
    return SensorEvent(
        sensor_id=spec.sensor_id,
        value=value,
        unit=spec.unit,
        observed_at=observed_at,
        received_at=received_at,
        observed_mono=received_mono - age,
        received_mono=received_mono,
    )


def _bind(spec: SensorSpec) -> socket.socket:
    path = spec.socket_path
    SOCKET_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(SOCKET_DIR, 0o700)       # only this user's processes may talk to the sensors
    try:
        os.unlink(path)               # a crashed run may have left the file behind
    except FileNotFoundError:
        pass
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(str(path))
    sock.setblocking(False)           # recv() raises BlockingIOError instead of waiting
    return sock


def run_ingest(channels: Any, state: Any) -> None:
    specs = load_specs()
    selector = selectors.DefaultSelector()
    sockets: dict[str, socket.socket] = {}
    stats = {sid: {"received": 0, "parse_errors": 0, "rejected": 0, "last_error": None} for sid in specs}

    for sid, spec in specs.items():
        sockets[sid] = _bind(spec)
        selector.register(sockets[sid], selectors.EVENT_READ, data=spec)

    def drain(sock: socket.socket, spec: SensorSpec) -> None:
        for _ in range(MAX_PER_WAKEUP):
            try:
                raw = sock.recv(RECV_BYTES)
            except BlockingIOError:
                return                         # nothing more to read right now
            received_at, received_mono = time.time(), time.monotonic()
            counters = stats[spec.sensor_id]
            try:
                event = make_event(spec, raw, received_at, received_mono)
            except RejectedReading as error:
                counters["rejected"] += 1
                counters["last_error"] = str(error)
                continue
            except (ValueError, KeyError, UnicodeDecodeError) as error:
                counters["parse_errors"] += 1
                counters["last_error"] = f"malformed datagram: {error}"[:120]
                continue
            counters["received"] += 1
            channels.sensor_events.put(event)   # bounded, drop-oldest: never blocks

    def publish() -> None:
        state["ingest"] = {
            "sockets": {sid: str(spec.socket_path) for sid, spec in specs.items()},
            "channels": {sid: dict(values) for sid, values in stats.items()},
        }

    print(f"[Ingest] Listening on {len(sockets)} Unix sockets in {SOCKET_DIR} (epoll).", flush=True)
    publish()
    last_publish = time.monotonic()
    try:
        while not channels.stop.is_set():
            for key, _ in selector.select(timeout=0.2):
                drain(key.fileobj, key.data)
            if time.monotonic() - last_publish >= PUBLISH_EVERY_S:
                publish()
                last_publish = time.monotonic()
        # Stop requested: read whatever is still waiting in the socket buffers.
        for sid, sock in sockets.items():
            drain(sock, specs[sid])
        publish()
    finally:
        channels.ingest_done.set()             # tell the Processor nothing more will arrive
        for sid, sock in sockets.items():
            selector.unregister(sock)
            sock.close()
            try:
                os.unlink(specs[sid].socket_path)
            except FileNotFoundError:
                pass
        selector.close()
        print("[Ingest] Stopped; sockets closed and unlinked.", flush=True)
