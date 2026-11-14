import multiprocessing as mp
import time

from edge.bounded_queue import POLL_S, BoundedQueue


class PriorityQueue:
    """
    A queue with two lanes: urgent items always come out before normal ones.

    Scenario OS3-2: a pedestrian surge alarm must never wait behind a pile of
    background sensor logs. Each lane is a BoundedQueue with the "drop oldest"
    policy, so memory stays bounded.

    The cost: as long as urgent items keep coming, normal items wait
    (starvation, the same problem as priority CPU scheduling; the known fix
    is aging).
    """

    def __init__(
        self,
        maxsize: int = 500,
        context: mp.context.BaseContext | None = None,
    ) -> None:

        # Maximum number of items in EACH lane.
        self.maxsize = maxsize

        # The urgent lane holds the alarms.
        self.urgent = BoundedQueue(maxsize, context)

        # The normal lane holds everything else (logs, background data).
        self.normal = BoundedQueue(maxsize, context)

    def put(self, item: object, urgent: bool = False) -> None:
        """Put an item in the urgent lane if `urgent` is True, otherwise in the normal lane."""
        if urgent:
            self.urgent.put(item)
        else:
            self.normal.put(item)

    def get(self, timeout: float = 1.0) -> object | None:
        """
        Get the next item, urgent lane first, waiting up to `timeout` seconds.
        Return None if both lanes are still empty when the timeout expires.
        """
        end = time.monotonic() + timeout

        while True:
            item = self.urgent.get(timeout=0)
            if item is not None:
                return item
            item = self.normal.get(timeout=0)
            if item is not None:
                return item
            if time.monotonic() >= end:
                return None
            time.sleep(POLL_S)

    def size(self) -> int:
        """Return the number of items in both lanes."""
        return self.urgent.size() + self.normal.size()

    def stats(self) -> dict[str, dict[str, int]]:
        """Return the statistics of each lane (see BoundedQueue.stats())."""
        return {"urgent": self.urgent.stats(), "normal": self.normal.stats()}
