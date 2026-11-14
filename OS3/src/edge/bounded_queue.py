import multiprocessing as mp
import queue
import time
from multiprocessing.queues import Queue

from edge.shared_counter import SharedCounter

# How often get() looks at the queue while it is empty.
POLL_S = 0.01

# Shutdown sentinel: the last message a producer puts in a queue.
# The consumer handles everything that came before it, then leaves its loop.
STOP = "STOP"


class BoundedQueue:
    """
    FIFO queue with the "drop oldest" policy (scenarios OS3-2 and OS3-3).

    When the queue is full, put() throws away the oldest item to make room.
    The producer never blocks, and the newest data is always kept.
    Memory stays bounded, so the Linux OOM killer is never triggered by a
    slow consumer.
    """

    def __init__(
        self,
        maxsize: int = 500,
        context: mp.context.BaseContext | None = None,
    ) -> None:
        context = context or mp.get_context()

        # Maximum number of items. When full, the oldest item is dropped.
        self.maxsize = maxsize

        # A multiprocessing Queue: safe to share between processes.
        self._queue: Queue = context.Queue(maxsize)

        # Two producers dropping at the same time would throw away two items
        # for one new item, so the "drop + put" step is protected by a lock.
        self._put_lock = context.Lock()

        # Number of items put into the queue.
        self.put_count = SharedCounter(context)

        # Number of items dropped because the queue was full.
        self.dropped_count = SharedCounter(context)

    def put(self, item: object) -> None:
        """
        Put an item into the queue, dropping the oldest one if it is full.

            before:   oldest -> [ A | B | C ] <- newest      (maxsize = 3)
            drop A:             [ B | C ]                    dropped_count + 1
            put D:              [ B | C | D ]
        """
        with self._put_lock:
            while not self.try_put(item):
                self.drop_oldest()
        self.put_count.increment()

    def get(self, timeout: float | None = None) -> object | None:
        """
        Get an item, waiting up to `timeout` seconds. Return None on timeout.
        If timeout is None, wait indefinitely.

        The waiting is done WITHOUT holding any lock. If the supervisor kills
        the consumer with SIGKILL while it waits inside the queue, the queue's
        internal read lock would stay taken forever. Here the consumer only
        takes the lock for a few microseconds once an item is available, so a
        SIGKILL almost always lands outside the lock (smaller risk, not zero).
        """
        if timeout is None:
            end = None
        else:
            # Monotonic time is immune to system clock changes.
            end = time.monotonic() + timeout

        while True:
            if self.size() > 0:
                item = self.take()
                if item is not None:
                    return item
            if end is not None and time.monotonic() >= end:
                return None
            time.sleep(POLL_S)

    def size(self) -> int:
        """Return the number of items in the queue."""
        return self._queue.qsize()

    def stats(self) -> dict[str, int]:
        """Return size, maxsize, put_count and dropped_count."""
        return {
            "size": self.size(),
            "maxsize": self.maxsize,
            "put_count": self.put_count.get_value(),
            "dropped_count": self.dropped_count.get_value(),
        }

    def take(self) -> object | None:
        """Take one item. Return None if the queue is empty."""
        try:
            return self._queue.get(timeout=0.1)
        except queue.Empty:
            return None

    def try_put(self, item: object) -> bool:
        """Try to put an item without blocking. Return False if the queue is full."""
        try:
            self._queue.put_nowait(item)
            return True
        except queue.Full:
            return False

    def drop_oldest(self) -> None:
        """Drop the oldest item and count it."""
        if self.take() is not None:
            self.dropped_count.increment()
