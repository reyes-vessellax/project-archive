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
SEARCH_S = 10.0          # a verification search: stopped early once results stop arriving (most finish in 4-8 s)
FOUND_HOURS = 3          # "someone's sharing it" is remembered this long (a miss too), so Discover reopens instantly


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


def deck_loadable(c: Candidate) -> bool:
    """What a search result already tells us about playing it on CDJs: the type, and the rate/depth when reported."""
    return ((c.extension or "").lower() in PREVIEWABLE and not (c.sample_rate_hz and c.sample_rate_hz > 48000)
            and not (c.bit_depth and c.bit_depth > 24))


def ready_copies(cands: list[Candidate], w: B.Wanted, min_kbps: int) -> list[Candidate]:
    return [c for c in B.ranked(cands, w, min_kbps)
            if deck_loadable(c) and c.free_slot and not (c.queue_length or 0)]


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


def _cache_key(rel_id: int) -> str:
    return f"discover:found:{rel_id}"


def _remembered(engine, rel: Release, label: str):
    """(hit, Found-or-None) from the cache: a found record or a known miss, younger than FOUND_HOURS."""
    from datetime import datetime, timedelta, timezone
    hit = engine.db.cache_get(_cache_key(rel.id))
    if not hit:
        return False, None
    data, at = hit
    try:
        if datetime.fromisoformat(at) < datetime.now(timezone.utc) - timedelta(hours=FOUND_HOURS):
            return False, None
    except ValueError:
        return False, None
    if not data.get("found"):
        return True, None
    best = Candidate(**data["best"])
    alts = [Candidate(**c) for c in data.get("alts") or []]
    return True, Found(rel, data.get("details") or {}, label, data["track"], best, alts or [best])


def _remember(engine, rel: Release, f) -> None:
    from dataclasses import asdict
    data = {"found": False} if f is None else {"found": True, "track": f.track, "details": f.details,
                                               "best": asdict(f.best), "alts": [asdict(c) for c in f.alts]}
    engine.db.cache_put(_cache_key(rel.id), data)


def verify(engine, svc, rel: Release, label: str, details: dict | None = None, cancelled=lambda: False, log=None):
    """Found when someone's sharing a good, ready copy right now. The record's own title is searched first (no
    Discogs call); only if that misses is the tracklist fetched and its A-side tried. Results are remembered."""
    artist = first_artist(rel.artist)
    if not artist or artist.lower() in ("various", "unknown artist"):
        return None
    hit, f = _remembered(engine, rel, label)
    if hit:
        return f
    lib = engine.library()
    if lib.owns(artist, rel.title):
        return None                                            # you already have it
    got = find_copy(svc, artist, [rel.title], cancelled, log)
    if got is None and not cancelled():
        details = details if details is not None else engine.release(rel.id)
        titles = [t for t in titles_to_try(rel, details) if t.lower() != rel.title.lower()]
        if titles and not any(lib.owns(artist, t) for t in titles):
            got = find_copy(svc, artist, titles[:1], cancelled, log)
    if cancelled():
        return None
    f = None
    if got:
        track, best, alts = got
        f = Found(rel, details or {}, label, track, best, alts)
    _remember(engine, rel, f)
    return f


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
