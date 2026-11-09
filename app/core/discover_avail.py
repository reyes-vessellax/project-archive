"""Discover only shows records someone is sharing right now, in a quality worth having.

For a record (from Discogs): search the network for its A-side (then the next track), using the same polite
search as everywhere else (one search at a time, from the shared budget, stopped as soon as results dry up).
It counts as available only with a copy that:
- is the right track (Batch's matching: artist and title within a typo, the mix respected)
- passes the quality bar (lossless, or MP3 at the user's minimum, normally 320)
- can be previewed and downloaded straight away: a free slot and nobody queued ahead
- isn't already in the library
That copy is what Play the drop previews and Check this file downloads: no second search.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from ..adapters.base import Candidate
from . import batch as B
from .discover import Release
from .searching import collect

PREVIEWABLE = {"mp3", "flac", "wav", "aiff", "aif"}      # the snippet preview reads these straight from the source
SEARCH_S = 20.0


class NotConnected(RuntimeError):
    pass


@dataclass
class Found:
    release: Release
    details: dict
    label: str
    track: str                         # the track that was searched for (and found)
    best: Candidate
    alts: list = field(default_factory=list)   # other ready copies, best first (for a busy source)


def first_artist(artist: str) -> str:
    a = re.split(r"\s+/\s+|,\s+|\s+&\s+|\s+Feat\.?\s+|\s+Vs\.?\s+", artist or "", flags=re.I)[0]
    return a.strip().rstrip("*")


def titles_to_try(rel: Release, details: dict) -> list[str]:
    """The A-side first, then the next track; the record title when Discogs lists no tracks."""
    out = []
    for _pos, t, _dur in details.get("tracks") or []:
        t = re.sub(r"\s*\((?:original|vocal|club|main)\s*mix\)\s*$", "", t or "", flags=re.I).strip()
        if t and t.lower() not in (x.lower() for x in out) and t.lower() not in ("untitled", "intro"):
            out.append(t)
        if len(out) == 2:
            break
    return out or [rel.title]


def ready_copies(cands: list[Candidate], w: B.Wanted, min_kbps: int) -> list[Candidate]:
    return [c for c in B.ranked(cands, w, min_kbps)
            if (c.extension or "").lower() in PREVIEWABLE and c.free_slot and not (c.queue_length or 0)]


def find_copy(svc, artist: str, titles: list[str], cancelled=lambda: False, log=None):
    """(track, best, alts) for the first title with a ready, good copy, else None."""
    if getattr(svc, "adapter", None) is None:
        raise NotConnected("not connected to the network")
    min_kbps = getattr(getattr(svc, "settings", None), "mp3_min_kbps", 320) or 320
    for t in titles[:2]:
        w = B.Wanted(artist, t)
        res = collect(svc, w.query, SEARCH_S, budget=getattr(svc, "search_budget", None), cancelled=cancelled,
                      log=log, check_login=False)
        if res is None:
            return None
        try:
            svc.forget_search(res.search_id)
        except Exception:
            pass
        ready = ready_copies(res.candidates, w, min_kbps)
        if ready:
            return t, ready[0], ready[:6]
    return None


def verify(engine, svc, rel: Release, label: str, details: dict | None = None, cancelled=lambda: False, log=None):
    artist = first_artist(rel.artist)
    if not artist or artist.lower() in ("various", "unknown artist"):
        return None
    details = details if details is not None else engine.release(rel.id)
    titles = titles_to_try(rel, details)
    lib = engine.library()
    if any(lib.owns(artist, t) for t in titles):
        return None                                            # you already have it
    got = find_copy(svc, artist, titles, cancelled, log)
    if not got:
        return None
    track, best, alts = got
    return Found(rel, details, label, track, best, alts)


def spin_found(engine, svc, labels: list[str], rng=None, cancelled=lambda: False, log=None, max_records: int = 6):
    """A random record from `labels` that someone is sharing right now (None after max_records misses)."""
    rng = rng or random.Random()
    tried = 0
    order = list(labels); rng.shuffle(order)
    for name in order:
        if tried >= max_records or cancelled():
            return None
        ent = engine.label(name)
        if not ent.discogs_id:
            continue
        first = engine.label_releases(ent.discogs_id, 1)
        page = first if first.pages <= 1 else engine.label_releases(ent.discogs_id, rng.randint(1, min(first.pages, 30)))
        pool = [r for r in page.releases if r.year and first_artist(r.artist).lower() not in ("", "various", "unknown artist")]
        rng.shuffle(pool)
        for r in pool[:2]:
            tried += 1
            f = verify(engine, svc, r, ent.name, cancelled=cancelled, log=log)
            if f:
                return f
            if tried >= max_records or cancelled():
                return None
    return None
