import time

from edge.bounded_queue import POLL_S, BoundedQueue


class PriorityQueue:
    """
    A queue with two lanes: urgent items always come out before normal ones.

    Each lane is a BoundedQueue with the "drop oldest" policy.
    get() always empties the urgent lane first, so a pedestrian surge alarm
    never waits behind a pile of background logs (scenario OS3-2).

    The cost: as long as urgent items keep coming, normal items wait
    (starvation, the same problem as priority CPU scheduling).
    """

    def __init__(self, maxsize: int = 500) -> None:

        # The maxsize is the maximum number of items in EACH lane, so memory stays bounded.
        self.maxsize = maxsize

        # The urgent lane holds the alarms.
        self.urgent = BoundedQueue(maxsize)

        # The normal lane holds everything else (logs, background data).
        self.normal = BoundedQueue(maxsize)

    def put(self, item: object, urgent: bool = False) -> None:
        """
        Put an item into the urgent lane if urgent is True, otherwise into the normal lane.
        """

        if urgent:
            self.urgent.put(item)
        else:
            self.normal.put(item)

    def get(self, timeout: float = 1.0) -> object | None:
        """
        Get the next item, urgent lane first, waiting up to timeout seconds if necessary.
        If both lanes are still empty when the timeout expires, return None.

            urgent lane:  [ alarm1 | alarm2 ]
            normal lane:  [ log1 | log2 | log3 ]

            get() -> alarm1     urgent lane not empty: take from it
            get() -> alarm2
            get() -> log1       urgent lane empty: take from the normal lane
            get() -> log2

        Each loop looks at the urgent lane FIRST, so an alarm that arrives
        while logs are waiting comes out at the very next get().
        """

        # Monotonic time is used to avoid issues with system clock changes.
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
        """
        Return the number of items in both lanes.
        """

        return self.urgent.size() + self.normal.size()

    def stats(self) -> dict[str, dict[str, int]]:
        """
        Return the statistics of each lane (see BoundedQueue.stats()).
        """

        return {"urgent": self.urgent.stats(), "normal": self.normal.stats()}
