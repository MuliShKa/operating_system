"""OS1-2: an integer in shared memory that several processes add to."""

import time


class SharedCounter:
    def __init__(self, context) -> None:
        # RawValue: a plain integer in shared memory, with NO lock built in.
        self._value = context.RawValue("i", 0)
        self._lock = context.Lock()

    def get(self) -> int:
        return self._value.value

    def increment(self) -> None:
        """
        +1 with the mutex: only one process at a time does read-add-write.

            A: lock, read 5, write 6, unlock
            B:                                lock, read 6, write 7, unlock   -> +2, correct
        """
        with self._lock:
            self._value.value += 1

    def unsafe_increment(self, pause_s: float = 0.0) -> None:
        """
        +1 WITHOUT a lock: two processes can read the same old value.

            A: read 5 ........ write 6
            B:   read 5 ........ write 6                                      -> +1, one update lost

        The pause makes the gap between read and write longer, like a preemption.
        """
        old = self._value.value
        time.sleep(pause_s)
        self._value.value = old + 1
