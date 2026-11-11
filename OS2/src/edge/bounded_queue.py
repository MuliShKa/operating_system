"""A bounded process-safe queue for sensor readings.

When producers are faster than the controller, this queue keeps recent data
instead of allowing memory use to grow without a limit.
"""

import multiprocessing as mp
import queue
import time
from multiprocessing.queues import Queue

from edge.models import SensorReading

POLL_INTERVAL_S = 0.01  # Check again after 10 ms instead of blocking on a queue lock.


class BoundedSensorQueue:
    """Keep readings in FIFO order and drop the oldest item when full.

    The multiprocessing context lets the same queue be shared with child
    processes. A lock makes the drop-oldest-and-insert operation safe when
    several producers write at the same time.
    """

    def __init__(
        self,
        maxsize: int = 500,
        context: mp.context.BaseContext | None = None,
    ) -> None:
        """Create the queue and shared state used by its processes."""
        if maxsize < 1:
            raise ValueError("maxsize must be positive")

        context = context or mp.get_context()
        self.maxsize = maxsize
        self._queue: Queue = context.Queue(maxsize=maxsize)
        # Only one producer may perform a full-queue replacement at a time.
        self._put_lock = context.Lock()
        # Shared value keeps drop statistics visible to every process.
        self._dropped_count = context.Value("L", 0)

    def put(self, reading: SensorReading) -> None:
        """Add a reading without blocking for space; discard oldest if needed."""
        with self._put_lock:
            while True:
                try:
                    self._queue.put_nowait(reading)
                    return
                except queue.Full:
                    # Free one slot, then retry the insert while holding the producer lock.
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        # Another consumer may have changed the queue between operations.
                        time.sleep(POLL_INTERVAL_S)
                    else:
                        with self._dropped_count.get_lock():
                            self._dropped_count.value += 1

    def get(self, timeout: float | None = None) -> SensorReading | None:
        """Read the oldest item, or return None when the optional timeout ends."""
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must not be negative")

        # Use monotonic time so clock corrections do not change the wait duration.
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            try:
                return self._queue.get_nowait()
            except queue.Empty:
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return None
                    time.sleep(min(POLL_INTERVAL_S, remaining))
                else:
                    time.sleep(POLL_INTERVAL_S)

    def dropped_count(self) -> int:
        """Return the number of readings removed to make room for newer data."""
        with self._dropped_count.get_lock():
            return self._dropped_count.value