"""Search pacing shared by the Search page and the wishlist.

One network search per query, stopped by us when its flow of results dries up, and one token bucket
for the whole app so standing searches and the user's own searches draw on the same allowance. The
network throttles chatty accounts (see CHANGELOG 0.5.6); these numbers were tuned on real sessions —
change them with a log in hand (docs/SEARCH_TEST_CASES.md).
"""
from __future__ import annotations

import threading
import time
from typing import Callable

SEARCH_LADDER_S = (40,)             # deadline for a normal search
SEARCH_FALLBACK_S = (25,)           # the one retry without the shakiest word, when nothing at all came back
SEARCH_MIN_S = 3.0                  # never stop before this: the first wave is still arriving
SEARCH_QUIET_S = 2.5                # stop once nothing new has arrived for this long (after SEARCH_MIN_S)
# Client-side budget: a burst of SEARCH_BURST searches, then on average one every SEARCH_REFILL_S.
SEARCH_BURST = 4
SEARCH_REFILL_S = 6.0


def ripe(history: list[tuple[float, int]], el: float, deadline: float) -> bool:
    """Stop when the flow of results has dried up — not before SEARCH_MIN_S, never after the deadline.
    A plateau is: nothing new for SEARCH_QUIET_S, or growth under 3% over the last SEARCH_QUIET_S once
    we already hold a good number of files."""
    if el >= deadline:
        return True
    if el < SEARCH_MIN_S:
        return False
    files_now = history[-1][1]
    if files_now == 0:
        return False                                            # rare query: give the far corners time
    past = [f for (t, f) in history if t <= el - SEARCH_QUIET_S]
    if not past:
        return False
    then = past[-1]
    grew = files_now - then
    return grew == 0 or (files_now >= 200 and grew < files_now * 0.03)


class Budget:
    """Token bucket for network searches. `take()` blocks (off the UI thread) until a token is free.
    `wait_needed()` says how long a take would block, so background work can simply come back later."""

    def __init__(self, burst: int = SEARCH_BURST, refill_s: float = SEARCH_REFILL_S):
        self.burst, self.refill_s = burst, refill_s
        self._tokens = float(burst)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        self._tokens = min(float(self.burst), self._tokens + (now - self._last) / self.refill_s)
        self._last = now

    def wait_needed(self) -> float:
        with self._lock:
            self._refill()
            return 0.0 if self._tokens >= 1 else (1 - self._tokens) * self.refill_s

    def take(self, notice: Callable[[str], None] | None = None, log: Callable[[str], None] | None = None) -> None:
        with self._lock:
            self._refill()
            wait = 0.0 if self._tokens >= 1 else (1 - self._tokens) * self.refill_s
            if wait <= 0:
                self._tokens -= 1
                return
        if notice:
            notice(f"Pacing… the network limits how often we can ask. Next search in {wait:.0f} s.")
        if log:
            log(f"search budget: waiting {wait:.1f}s")
        time.sleep(wait)
        with self._lock:
            self._refill()
            self._tokens = max(0.0, self._tokens - 1)


    def take_background(self, cancelled: Callable[[], bool] | None = None, spare: int = 1) -> bool:
        """For Discover's background searches: go only while `spare` searches stay free, so the user's own
        searches (and the Wishlist) never queue behind them. False = cancelled while waiting."""
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1 + spare:
                    self._tokens -= 1
                    return True
            if cancelled and cancelled():
                return False
            time.sleep(0.5)


def collect(svc, query: str, deadline: float, budget: Budget | None = None,
            progress: Callable[[int, int], None] | None = None, cancelled: Callable[[], bool] | None = None,
            log: Callable[[str], None] | None = None, check_login: bool = True, background: bool = False):
    """Run ONE network search and return its SearchResult (None if cancelled).
    Watches the engine's live counts and stops the search the moment it is ripe, then reads everything."""
    if cancelled and cancelled():
        return None                                     # given up already: don't spend a search on it
    if budget is not None:
        if background:
            if not budget.take_background(cancelled):
                return None
        else:
            budget.take(log=log)
    if cancelled and cancelled():
        return None
    res = svc.search(query, timeout_s=deadline + 10, check_login=check_login)
    sid = res.search_id
    t0 = time.monotonic()
    history: list[tuple[float, int]] = []
    stopped = False
    delay = 0.35
    while True:
        time.sleep(delay)
        delay = min(0.8, delay * 1.25)
        if cancelled and cancelled():
            svc.stop_search(sid)
            return None
        done, n_users, n_files, err = svc.search_status(sid)
        el = time.monotonic() - t0
        history.append((el, n_files))
        if progress:
            progress(n_users, n_files)
        if not done and not stopped and ripe(history, el, deadline):
            svc.stop_search(sid); stopped = True
            if log:
                log(f"search {sid[:8]} {query!r} stopped at {el:.1f}s with {n_users} users / {n_files} files")
            continue
        if done or el > deadline + 25:
            final = svc.search_results(sid)
            final.query = query; final.search_id = sid; final.finished = True
            if err:
                final.error = err
            if log:
                log(f"search {sid[:8]} {query!r} done at {el:.1f}s: {len(final.candidates)} rows from {n_users} users")
            return final
