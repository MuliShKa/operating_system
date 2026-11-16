"""Sensor channel health (scenario OS4-6): is this channel alive and trustworthy?

A mist cannon must never be driven by a sensor that is silent or frozen:
  STALE : nothing received for `stale_after_s` (a hung device sends no EOF and
          no error; silence is the ONLY symptom, so we measure silence)
  STUCK : the same value N times in a row (a frozen device keeps talking)
Both are computed with the monotonic clock.
"""

from __future__ import annotations

OK = "OK"
NO_DATA = "NO_DATA"
STALE = "STALE"
STUCK = "STUCK"


class ChannelGuard:
    def __init__(self, stale_after_s: float, stuck_check: bool, stuck_repeat: int) -> None:
        self.stale_after_s = stale_after_s
        self.stuck_check = stuck_check
        self.stuck_repeat = stuck_repeat
        self.last_heard_mono: float | None = None
        self._last_value: float | None = None
        self.repeat = 0

    def heard(self, received_mono: float) -> None:
        """Any datagram, even a late or out-of-order one, proves the device is alive."""
        if self.last_heard_mono is None or received_mono > self.last_heard_mono:
            self.last_heard_mono = received_mono

    def value_seen(self, value: float) -> None:
        """Feed readings in EVENT-time order only (a late reading says nothing about freezing)."""
        self.repeat = self.repeat + 1 if value == self._last_value else 1
        self._last_value = value

    def status(self, now_mono: float) -> str:
        if self.last_heard_mono is None:
            return NO_DATA
        if now_mono - self.last_heard_mono > self.stale_after_s:
            return STALE
        if self.stuck_check and self.repeat >= self.stuck_repeat:
            return STUCK
        return OK

    def silence_s(self, now_mono: float) -> float | None:
        return None if self.last_heard_mono is None else max(0.0, now_mono - self.last_heard_mono)
