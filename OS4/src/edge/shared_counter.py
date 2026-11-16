import multiprocessing as mp
import time


class SharedCounter:
    """
    A number stored in shared memory, readable and writable by several processes.
    """

    def __init__(self, context: mp.context.BaseContext | None = None) -> None:
        context = context or mp.get_context()

        # A RawValue is a raw integer in shared memory with NO lock built in.
        self._value = context.RawValue("i", 0)

        # The lock lets only one process at a time change the value.
        self._lock = context.Lock()

    def get_value(self) -> int:
        """Return the current value of the counter."""
        return self._value.value

    def increment(self) -> None:
        """
        Add 1 to the counter, safely.
        Only one process at a time can do the read-modify-write.
        """
        with self._lock:
            self._value.value += 1

    def unsafe_increment(self, pause_s: float = 0.0) -> None:
        """
        Add 1 to the counter WITHOUT the lock (used to demonstrate a race condition).
        Two processes can read the same old value and one update is lost.
        """
        old = self._value.value

        # The pause widens the gap between the read and the write,
        # so the lost update shows up every time in the demo.
        time.sleep(pause_s)

        self._value.value = old + 1
