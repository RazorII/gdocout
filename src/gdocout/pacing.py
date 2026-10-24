"""How many downloads run at once, and when to pause.

Google publishes no limit for its download links, so gdocout finds a safe pace
as it goes:

- It starts with a few downloads at once and adds one after every run of clean
  answers, up to a ceiling (8 by default, which measured clean at about 220
  files a minute).
- Any sign of throttling (HTTP 429, Google's "unusual traffic" page, a 5xx
  storm) halves the number running at once and pauses everyone: 30 seconds,
  doubling each time it happens again, up to 15 minutes, or longer if Google
  says how long with Retry-After.
- Requests that were already running when a pause began don't count again, so a
  burst of parallel 429s halves once, not eight times.
- After a run of pauses with no success in between (about half an hour of
  Google saying no), it stops. Everything finished so far is saved, and running
  the same command later continues where it left off.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

OK = "ok"
THROTTLE = "throttle"
TRANSIENT = "transient"


@dataclass
class PaceStats:
    peak_workers: int = 0
    pauses: int = 0
    paused_seconds: float = 0.0
    events: List[str] = field(default_factory=list)  # human-readable, for the report


class Pacer:
    def __init__(
        self,
        start: int = 2,
        maximum: int = 8,
        ramp_every: int = 12,
        first_pause: float = 30.0,
        max_pause: float = 900.0,
        give_up_after: int = 6,
        min_gap: float = 0.1,
        clock: Callable[[], float] = time.monotonic,
        sleep_cap: float = 1.0,
    ):
        self.allowed = max(1, min(start, maximum))
        self.maximum = max(1, maximum)
        self.ramp_every = ramp_every
        self.first_pause = first_pause
        self.max_pause = max_pause
        self.give_up_after = give_up_after
        self.min_gap = min_gap
        self.clock = clock
        self.sleep_cap = sleep_cap

        self.active = 0
        self.clean = 0  # clean answers since the last change
        self.no_success_pauses = 0
        self.next_pause = first_pause
        self.paused_until = 0.0
        self.pause_started = -1.0
        self.last_start = -1e9
        self.stopped = False
        self.stop_reason = ""
        self.stats = PaceStats(peak_workers=self.allowed)
        self._cond = threading.Condition()

    # -- used by worker threads ------------------------------------------
    def acquire(self) -> Optional[float]:
        """Wait for a slot. Returns the start time to hand back to release(), or None once stopped."""
        with self._cond:
            while True:
                if self.stopped:
                    return None
                now = self.clock()
                wait = 0.0
                if now < self.paused_until:
                    wait = self.paused_until - now
                elif self.active >= self.allowed:
                    wait = self.sleep_cap
                elif now - self.last_start < self.min_gap:
                    wait = self.min_gap - (now - self.last_start)
                else:
                    self.active += 1
                    self.last_start = now
                    return now
                self._cond.wait(min(wait, self.sleep_cap))

    def release(self, started: float, signal: str, retry_after: Optional[float] = None) -> None:
        with self._cond:
            self.active = max(0, self.active - 1)
            now = self.clock()
            if signal == OK:
                self.no_success_pauses = 0
                self.next_pause = self.first_pause
                self.clean += 1
                if self.clean >= self.ramp_every and self.allowed < self.maximum:
                    self.allowed += 1
                    self.clean = 0
                    self.stats.peak_workers = max(self.stats.peak_workers, self.allowed)
            elif signal == THROTTLE and started > self.pause_started:
                self._pause(now, retry_after)
            elif signal == TRANSIENT:
                self.clean = 0
            self._cond.notify_all()

    def stop(self, reason: str = "") -> None:
        with self._cond:
            if not self.stopped:
                self.stopped = True
                self.stop_reason = reason
            self._cond.notify_all()

    # -- internals ---------------------------------------------------------
    def _pause(self, now: float, retry_after: Optional[float]) -> None:
        self.clean = 0
        self.allowed = max(1, self.allowed // 2)
        self.no_success_pauses += 1
        if self.no_success_pauses > self.give_up_after:
            self.stopped = True
            self.stop_reason = (
                "Google kept refusing downloads from this connection for about half an hour. "
                "Everything finished so far is saved; run the same command later to continue."
            )
            self.stats.events.append(self.stop_reason)
            return
        pause = max(self.next_pause, retry_after or 0.0)
        self.next_pause = min(self.next_pause * 2, self.max_pause)
        self.pause_started = now
        self.paused_until = max(self.paused_until, now + pause)
        self.stats.pauses += 1
        self.stats.paused_seconds += pause
        self.stats.events.append(
            f"Google slowed things down: paused {int(pause)} s, then continued with {self.allowed} at once."
        )

    @property
    def paused(self) -> bool:
        return self.clock() < self.paused_until
