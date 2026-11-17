"""A lock-free stop flag shared by the OS2 worker processes."""

import ctypes
import multiprocessing as mp
from multiprocessing.context import BaseContext
from time import monotonic, sleep
from typing import Protocol

POLL_INTERVAL_S = 0.01


class StopSignal(Protocol):
    """Operations required by worker loops to observe a shutdown request."""

    def is_set(self) -> bool: ...

    def set(self) -> None: ...

    def wait(self, timeout: float | None = None) -> bool: ...


class SharedStopEvent:
    """Share a one-way stop flag without a process-shared lock."""

    def __init__(self, context: BaseContext | None = None) -> None:
        context = context or mp.get_context()
        self._flag: ctypes.c_byte = context.RawValue("b", 0)

    def is_set(self) -> bool:
        """Return whether shutdown has been requested."""
        return self._flag.value != 0

    def set(self) -> None:
        """Request shutdown; the flag is never reset."""
        self._flag.value = 1

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for shutdown, polling so an abrupt worker exit cannot lock it."""
        deadline = None if timeout is None else monotonic() + max(timeout, 0)
        while True:
            if self.is_set():
                return True
            if deadline is not None:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return self.is_set()
                sleep(min(POLL_INTERVAL_S, remaining))
            else:
                sleep(POLL_INTERVAL_S)
