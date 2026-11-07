"""Batch downloads go out a few at a time, not all at once.

Pressing "Download and check" on an 18-track playlist used to request all 18 files in the same second. That
looks like a bot to the people sharing (some auto-ban for it), splits the bandwidth 18 ways so everything
crawls, and lands 18 files on the checker together. The pacer lets at most MAX_ACTIVE downloads run, never two
from the same person at once, with a short random gap between starts. The rest wait their turn.
"""
from __future__ import annotations

import random
import time
from typing import Callable, Iterable

MAX_ACTIVE = 3
GAP_S = (5.0, 11.0)


class DownloadPacer:
    def __init__(self, active_users: Callable[[], Iterable[str]], clock=time.monotonic, sleep=time.sleep,
                 rng: random.Random | None = None, max_active: int = MAX_ACTIVE, gap_s=GAP_S):
        self.active_users, self.clock, self.sleep = active_users, clock, sleep
        self.rng = rng or random.Random()
        self.max_active, self.gap_s = max_active, gap_s
        self.next_at = 0.0

    def pick(self, users: list[str]) -> int | None:
        """Index of the first waiting track that may start now, or None (wait a bit and ask again)."""
        if self.clock() < self.next_at:
            return None
        busy = list(self.active_users())
        if len(busy) >= self.max_active:
            return None
        return next((i for i, u in enumerate(users) if u not in busy), None)

    def started(self) -> None:
        self.next_at = self.clock() + self.rng.uniform(*self.gap_s)

    def run(self, items: list, user_of: Callable[[object], str], start: Callable[[object], None],
            should_stop: Callable[[], bool] = lambda: False, poll_s: float = 1.0) -> list:
        """Start every item, paced. Returns the items never started (stopped early)."""
        waiting = list(items)
        while waiting:
            if should_stop():
                return waiting
            i = self.pick([user_of(it) for it in waiting])
            if i is None:
                self.sleep(poll_s)
                continue
            it = waiting.pop(i)
            start(it)
            self.started()
        return []
