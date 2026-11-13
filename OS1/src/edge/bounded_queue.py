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
    FIFO queue with the "drop oldest" policy.

    When the queue is full, put() throws away the oldest item to make room.
    The producer never blocks, and the newest data is always kept.
    """

    def __init__(
        self,
        maxsize: int = 500,
        context: mp.context.BaseContext | None = None,
    ) -> None:
        context = context or mp.get_context()

        # The maxsize is the maximum number of items in the queue. If the queue is full, the oldest item will be dropped to make room for a new item.
        self.maxsize = maxsize

        # The queue is a multiprocessing Queue, which is a thread-safe queue that can be shared between processes.
        self._queue: Queue = context.Queue(maxsize)

        # Two producers dropping at the same time would throw away two items
        # instead of one, so the "drop + put" step is protected by a lock.
        self._put_lock = context.Lock()

        # The put_count is a shared counter that counts the number of items put into the queue.
        self.put_count = SharedCounter(context)

        # The dropped_count is a shared counter that counts the number of items dropped from the queue.
        self.dropped_count = SharedCounter(context)

    def put(self, item: object) -> None:
        """
        Put an item into the queue, dropping the oldest if full.

        Queue full (maxsize = 3), put(D):

            before:   oldest -> [ A | B | C ] <- newest
            drop A:             [ B | C ]           dropped_count + 1
            put D:              [ B | C | D ]

        Why the lock: without it, two producers can see "full" at the same time.

            Producer 1              Producer 2              queue
            ----------              ----------              -----
            try_put(D): full                                [ A | B | C ]
                                    try_put(E): full        [ A | B | C ]
            drop A                                          [ B | C ]
                                    drop B                  [ C ]          <- B lost for nothing
            put D                                           [ C | D ]
                                    put E                   [ C | D | E ]

        With the lock, Producer 2 waits until Producer 1 has finished "drop + put",
        so only ONE item is dropped for each new item.
        """

        with self._put_lock:
            while not self.try_put(item):
                self.drop_oldest()
        self.put_count.increment()

    def get(self, timeout: float | None = None) -> object | None:
        """
        Get an item from the queue, waiting up to timeout seconds if necessary.
        If timeout is None, wait indefinitely. If the queue is empty and the timeout expires, return None.

        The waiting is done here, WITHOUT holding any lock:

            loop:  queue empty?  --yes-->  sleep POLL_S, look again (no lock held)
                        |
                        no
                        v
                   take()  -->  holds the queue's read lock for a very short time

        Why: the supervisor may kill the consumer with SIGKILL. A killed process
        never gives back the locks it holds. If it was waiting INSIDE the queue
        (holding its read lock), the lock stays taken forever:

            Old consumer            Supervisor              New consumer
            ------------            ----------              ------------
            holds read lock,
            waits for an item
                                    SIGKILL old consumer
            (dead, lock still taken)
                                    start new consumer
                                                            wants the read lock:
                                                            waits forever, reads 0 items

        Here the consumer spends almost all its time sleeping with no lock,
        so a SIGKILL almost always lands outside the lock (the risk is smaller, not zero).
        """

        if timeout is None:
            end = None
        else:
            # The end time is the current time plus the timeout, so we can check if we've exceeded the timeout while waiting for an item.
            # Monotonic time is used to avoid issues with system clock changes.
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
        """
        Return the number of items in the queue.
        """
        return self._queue.qsize()

    def stats(self) -> dict[str, int]:
        """
        Return a dictionary of statistics about the queue, including the current size, maximum size, number of items put, and number of items dropped.
        """

        return {
            "size": self.size(),
            "maxsize": self.maxsize,
            "put_count": self.put_count.get_value(),
            "dropped_count": self.dropped_count.get_value(),
        }

    def take(self) -> object | None:
        """
        Take an item from the queue.
        Return None if the queue is empty.
        """

        try:
            return self._queue.get(timeout=0.1)
        except queue.Empty:
            return None

    def try_put(self, item: object) -> bool:
        """
        Try to put an item into the queue.
        """

        try:
            self._queue.put_nowait(item)
            return True
        except queue.Full:
            return False

    def drop_oldest(self) -> None:
        """
        Drop the oldest item from the queue.
        """

        if self.take() is not None:
            self.dropped_count.increment()
