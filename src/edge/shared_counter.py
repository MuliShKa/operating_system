import multiprocessing as mp
import time


class SharedCounter:
    """
    A number stored in shared memory, readable and writable by several processes.
    """

    def __init__(self, context: mp.context.BaseContext | None = None) -> None:
        context = context or mp.get_context()

        # The value is a RawValue: a raw integer in shared memory, with NO lock built in.
        self._value = context.RawValue("i", 0)

        # The lock lets only one process at a time change the value.
        self._lock = context.Lock()

    def get_value(self) -> int:
        """
        Return the current value of the counter.
        """

        return self._value.value

    def increment(self) -> None:
        """
        Add 1 to the counter, safely.
        Only one process at a time can do the read-modify-write.

            Process A               Process B               value
            ---------               ---------               -----
            take the lock                                     5
            read 5                  wants the lock: waits     5
            write 6                 ...waits                  6
            give back the lock      ...waits                  6
                                    take the lock             6
                                    read 6                    6
                                    write 7                   7
                                    give back the lock        7   <- 2 updates, +2: correct
        """

        with self._lock:
            self._value.value += 1

    def unsafe_increment(self, pause_s: float = 0.0) -> None:
        """
        Add 1 to the counter, without the lock.
        Two processes can read the same old value and lose an update.

            Process A               Process B               value
            ---------               ---------               -----
            old = 5                                           5
                                    old = 5                   5
            (pause)                 (pause)                   5
            value = old + 1                                   6
                                    value = old + 1           6   <- 2 updates, only +1: one is lost
        """

        old = self._value.value

        # The pause makes the gap between the read and the write longer,
        # so the problem shows up every time in the demo.
        time.sleep(pause_s)

        self._value.value = old + 1
