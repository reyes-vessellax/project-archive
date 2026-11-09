"""Crates for Discover: what people are sharing right now from a label (or by an artist), from ONE network search.

Searching the network for "Dance Mania" returns the files whose folders and names carry it: label rips are
usually filed by label and catalogue number. One search (about 5-10 s, from the shared budget) fills a whole
crate with tracks that are genuinely available, instead of one search per record.

A track makes the crate when its best copy is:
- a format decks load (MP3/FLAC/WAV/AIFF; nothing reported over 48 kHz or 24-bit) and good quality
  (lossless, or MP3 at the user's minimum, normally 320)
- ready now: a free slot and nobody queued ahead, so Play the drop starts straight away
- not an ad bot, not private, not already in the library
Duplicates (the same track from many people) collapse to one entry with the other copies kept as fallbacks.
Crates are remembered for CRATE_HOURS, so Discover reopens instantly.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

from ..adapters.base import Candidate, parse_track
from .discover_avail import deck_loadable
from .fuzzy import words
from .searching import collect

CRATE_HOURS = 3
SEARCH_S = 12.0
MAX_TRACKS = 30
LOSSLESS = {"flac", "wav", "aiff", "aif"}


@dataclass
class CrateTrack:
    artist: str
    title: str
    mix: str
    best: Candidate
    alts: list = field(default_factory=list)
    folder: str = ""
    catno: str = ""
    thumb: str = ""          # filled in later from Discogs when the record is matched

    @property
    def key(self) -> str:
        return f"{' '.join(words(self.artist))}|{' '.join(words(self.title))}|{' '.join(words(self.mix))}"


_CATNO = re.compile(r"\b([A-Z]{1,6}[ -]?\d{2,5}[A-Z]?)\b")


def _good(c: Candidate, min_kbps: int) -> bool:
    ext = (c.extension or "").lower()
    if c.locked or c.note or not deck_loadable(c):
        return False
    if ext in LOSSLESS:
        return True
    return ext == "mp3" and (c.bitrate_kbps or 0) >= min_kbps


def _quality(c: Candidate) -> tuple:
    ext = (c.extension or "").lower()
    return (0 if ext in LOSSLESS else 1, -(c.bitrate_kbps or 0), -(c.upload_speed or 0))


def build(cands: list[Candidate], owns=lambda a, t: False, min_kbps: int = 320) -> list[CrateTrack]:
    """Search results -> one entry per track, best copy first, ready-now only."""
    groups: dict[str, CrateTrack] = {}
    for c in cands:
        if not (_good(c, min_kbps) and c.free_slot and not (c.queue_length or 0)):
            continue
        artist, title, mix = (c.artist, c.title, c.mix) if c.artist else parse_track(c.display_name or "")
        if not artist or not title or owns(artist, title):
            continue
        cat = _CATNO.search(c.folder or "")
        t = CrateTrack(artist, title, mix, c, [c], c.folder or "", cat.group(1) if cat else "")
        g = groups.get(t.key)
        if g is None:
            groups[t.key] = t
        else:
            g.alts.append(c)
    out = []
    for g in groups.values():
        g.alts.sort(key=_quality)
        g.best = g.alts[0]
        g.alts = g.alts[:6]
        out.append(g)
    # lossless first, then the order the network returned them (closest matches tend to come first)
    out.sort(key=lambda t: _quality(t.best)[0])
    return out[:MAX_TRACKS]


def _key(query: str) -> str:
    return "discover:crate:" + " ".join(words(query))


def remembered(db, query: str) -> list[CrateTrack] | None:
    hit = db.cache_get(_key(query))
    if not hit:
        return None
    data, at = hit
    try:
        if datetime.fromisoformat(at) < datetime.now(timezone.utc) - timedelta(hours=CRATE_HOURS):
            return None
    except ValueError:
        return None
    out = []
    for d in data.get("tracks") or []:
        best = Candidate(**d["best"])
        alts = [Candidate(**a) for a in d.get("alts") or []] or [best]
        out.append(CrateTrack(d["artist"], d["title"], d.get("mix", ""), best, alts, d.get("folder", ""),
                              d.get("catno", ""), d.get("thumb", "")))
    return out


def remember(db, query: str, tracks: list[CrateTrack]) -> None:
    db.cache_put(_key(query), {"tracks": [{"artist": t.artist, "title": t.title, "mix": t.mix, "best": asdict(t.best),
                                           "alts": [asdict(a) for a in t.alts], "folder": t.folder, "catno": t.catno,
                                           "thumb": t.thumb} for t in tracks]})


def crate(svc, query: str, owns=lambda a, t: False, cancelled=lambda: False, log=None, use_cache: bool = True):
    """The crate for a label or artist name: from memory when fresh, else one network search."""
    if use_cache:
        hit = remembered(svc.db, query)
        if hit is not None:
            return hit
    if getattr(svc, "adapter", None) is None:
        return None
    res = collect(svc, query, SEARCH_S, budget=getattr(svc, "search_budget", None), cancelled=cancelled, log=log,
                  check_login=False)
    if res is None:
        return None
    try:
        svc.forget_search(res.search_id)
    except Exception:
        pass
    min_kbps = getattr(getattr(svc, "settings", None), "mp3_min_kbps", 320) or 320
    tracks = build(res.candidates, owns, min_kbps)
    remember(svc.db, query, tracks)
    return tracks
