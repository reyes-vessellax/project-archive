"""Works through a batch list: one network search per track, spaced out, best copy picked for each.

The network rate-limits accounts that search too often (see CHANGELOG 0.5.6), so a batch never fires
searches back to back: at least GAP_S seconds between starts. Nothing is downloaded here; the user
presses "Download and check" and each pick goes through the normal quarantine + check.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from . import batch as B
from .availability import availability

GAP_S = 8.0          # between search starts
SEARCH_S = 25.0      # per-track deadline
QUIET_S = 3.0        # stop early once results stop growing for this long (after MIN_S)
MIN_S = 4.0


@dataclass
class Item:
    wanted: B.Wanted
    status: str = "waiting"      # waiting | searching | found | not_found | have | queued | error
    pick: object = None          # Candidate
    detail: str = ""             # "FLAC · 48 MB" / "No good copy found" / error text
    avail: str = ""              # "Ready now · ~25 sec"
    alts: list = None            # other acceptable copies, best first (the row's drop-down); pick is alts[0]

    def to_dict(self) -> dict:
        w = self.wanted
        return {"artist": w.artist, "title": w.title, "mix": w.mix, "source": w.source, "status": self.status,
                "detail": self.detail, "avail": self.avail}


def describe_pick(c) -> str:
    ext = (c.extension or "").upper()
    fmt = f"MP3 {c.bitrate_kbps}" if ext == "MP3" and c.bitrate_kbps else ext
    return f"{fmt} · {c.size / 1e6:.0f} MB"


def choose(it: Item, c) -> None:
    """Swap the item's pick for another copy from its drop-down."""
    it.pick, it.detail, it.avail = c, describe_pick(c), availability(c).label


def run(items: list[Item], svc, library: list[tuple[str, str]], on_update: Callable[[int, Item], None],
        should_stop: Callable[[], bool] = lambda: False, sleep=time.sleep, clock=time.monotonic) -> None:
    last_start = -1e9
    for i, it in enumerate(items):
        if should_stop():
            return
        if it.status not in ("waiting", "error"):
            continue
        if B.already_have(it.wanted, library):
            it.status, it.detail = "have", "Already in your library"
            on_update(i, it)
            continue
        wait = GAP_S - (clock() - last_start)
        while wait > 0:
            if should_stop():
                return
            sleep(min(wait, 0.5))
            wait = GAP_S - (clock() - last_start)
        budget = getattr(svc, "search_budget", None)      # shared with the user's searches and the Wishlist
        while budget is not None and budget.wait_needed() > 0:
            if should_stop():
                return
            sleep(0.5)
        if budget is not None:
            budget.take()
        it.status = "searching"; on_update(i, it)
        last_start = clock()
        try:
            res = svc.search(it.wanted.query, timeout_s=SEARCH_S + 5)
            sid = res.search_id
            t0, seen, still_since = clock(), -1, clock()
            while not should_stop():
                finished, _resp, files, _state = svc.search_status(sid)
                if files != seen:
                    seen, still_since = files, clock()
                el = clock() - t0
                if finished or el >= SEARCH_S or (el >= MIN_S and files > 0 and clock() - still_since >= QUIET_S):
                    break
                sleep(0.5)
            svc.stop_search(sid)
            cands = svc.search_results(sid).candidates
            svc.forget_search(sid)
        except Exception as e:                                       # noqa: BLE001
            it.status, it.detail = "error", str(e)[:120]
            on_update(i, it)
            continue
        min_kbps = getattr(getattr(svc, "settings", None), "mp3_min_kbps", 320) or 320
        alts = B.ranked(cands, it.wanted, min_kbps)
        if not alts:
            low = [c for c in cands if B.score(c, it.wanted) > 0 and B.too_low(c, min_kbps)]
            it.status = "not_found"
            it.detail = (f"Only low-quality copies ({max(c.bitrate_kbps for c in low)} kbps)" if low
                         else "No good copy found")
        else:
            it.status, it.alts = "found", alts[:8]
            choose(it, alts[0])
        on_update(i, it)
