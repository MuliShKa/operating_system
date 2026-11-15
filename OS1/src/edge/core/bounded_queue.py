"""A queue between processes that can never grow past a fixed size."""

import queue


class BoundedQueue:
    """
    Wraps a multiprocessing.Queue with a maximum size.

    When the queue is full, put() drops the OLDEST item to make room:
    the producer never blocks and the newest readings are always kept.

        full (maxsize 3):  [ A | B | C ]
        put(D):            drop A -> [ B | C | D ]

    The "drop + put" step holds a lock, otherwise two producers that both see
    "full" would each drop one item for a single new one.
    """

    def __init__(self, maxsize: int, context) -> None:
        self._queue = context.Queue(maxsize)
        self._lock = context.Lock()

    def put(self, item: object) -> None:
        with self._lock:
            while True:
                try:
                    self._queue.put_nowait(item)
                    return
                except queue.Full:
                    try:
                        self._queue.get_nowait()  # drop the oldest
                    except queue.Empty:
                        pass

    def get(self, timeout: float) -> object | None:
        """Wait up to `timeout` seconds for an item; return None if none came."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def size(self) -> int:
        return self._queue.qsize()
