"""Discover: dig for house music, every era, from the labels, artists and records behind it.

Where the data comes from (all public, no account):
- MusicBrainz finds a label or artist by name and links it to its Discogs page (url relations).
- Discogs gives the catalogue: every release on a label or by an artist, by year, with catalogue numbers
  and formats, plus profiles, sub-labels, parent labels, aliases and groups. House lives on Discogs.
Both are asked politely: MusicBrainz at most once a second, Discogs at most once every 2.5 s (its public
limit is 25 a minute). Every answer is cached in the app's database for a week, so a label you've opened
before opens instantly, offline too.

Nothing here hosts or plays music. Discover points at records; the user finds a copy through Search, and
every file is still checked before it reaches the library.

The library side (labels and artists you own, what you already have, what mixes with your new tracks) is
all local.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import jobs as J
from .fuzzy import words

MB = "https://musicbrainz.org/ws/2"
DISCOGS = "https://api.discogs.com"
CACHE_DAYS = 7
PER_PAGE = 100
_GAP = {"mb": 1.1, "discogs": 2.5}            # seconds between requests to each host

Fetch = Callable[[str, float], bytes]


# ------------------------------------------------------------------------------------------ names
_SUFFIX = re.compile(r"\s*\(\d+\)$")          # Discogs disambiguation: "Fast Eddie (2)"


def clean_name(name: str) -> str:
    """Discogs display name -> the name people use: drops "(2)" and the "*" that marks a name variation, in every
    part of a split credit ("Jack Master Funk* / Jack Master Funk (2)")."""
    parts = re.split(r"(\s+/\s+|,\s+|\s+&\s+|\s+And\s+|\s+Feat\.?\s+|\s+Vs\.?\s+)", (name or "").strip())
    return "".join(p if i % 2 else _SUFFIX.sub("", p.strip().rstrip("*")).strip() for i, p in enumerate(parts)).strip()


def norm(text: str) -> str:
    return " ".join(w for w in words(text or "") if w not in ("the", "records", "recordings", "music", "inc", "ltd"))


def _same(a: str, b: str) -> bool:
    return bool(a) and norm(a) == norm(b)


# ------------------------------------------------------------------------------------------ results
@dataclass
class Release:
    id: int
    title: str
    artist: str
    year: int | None
    catno: str = ""
    format: str = ""
    label: str = ""
    thumb: str = ""
    role: str = ""                            # artist pages: "Main", "Remix", "Producer"…
    owned: bool = False

    @property
    def query(self) -> str:
        """What to type into Search for it."""
        a = "" if self.artist.lower() in ("various", "unknown artist") else self.artist
        return f"{a} {self.title}".strip()


@dataclass
class Page:
    """One page of a catalogue."""
    releases: list[Release]
    page: int
    pages: int
    total: int


@dataclass
class Entity:
    """A label or an artist, as Discogs describes it."""
    kind: str                                 # "label" | "artist"
    name: str
    discogs_id: int | None
    profile: str = ""
    related: list[tuple[str, str]] = field(default_factory=list)   # (relation, name): "Sub-label", "Alias"…
    url: str = ""


# ------------------------------------------------------------------------------------------ the engine
class Discover:
    def __init__(self, db, fetch: Fetch | None = None, sleep=time.sleep, clock=time.monotonic):
        from ..media.metadata import http_get
        self.db = db
        self.fetch = fetch or (lambda url, timeout=10.0: http_get(url, timeout))
        self.sleep, self.clock = sleep, clock
        self._last = {"mb": 0.0, "discogs": 0.0}
        self._lock = threading.Lock()
        self._lib = None                       # (jobs_version, LibraryIndex)

    # ---- network, politely, with a cache --------------------------------------------------
    def _get(self, host: str, url: str, days: int = CACHE_DAYS) -> dict:
        hit = self.db.cache_get(url)
        if hit is not None:
            data, at = hit
            try:
                if datetime.fromisoformat(at) > datetime.now(timezone.utc) - timedelta(days=days):
                    return data
            except ValueError:
                pass
        data = None
        for attempt in range(6):
            with self._lock:
                wait = self._last[host] + _GAP[host] - self.clock()
                if wait > 0:
                    self.sleep(wait)
                self._last[host] = self.clock()
            try:
                data = json.loads(self.fetch(url, 10.0).decode("utf-8", "replace"))
                break
            except Exception as e:
                busy = getattr(e, "code", None) in (429, 503)          # "slow down": back off and ask again
                if busy and attempt < 5:
                    with self._lock:                                       # 3, 6, 9, 12, 15 s: Discogs' window is a minute
                        self._last[host] = self.clock() + 3.0 * (attempt + 1)
                    continue
                if hit is not None:
                    return hit[0]              # stale beats nothing when offline
                raise
        self.db.cache_put(url, data)
        return data

    # ---- MusicBrainz: name -> Discogs id ---------------------------------------------------
    def _discogs_id(self, kind: str, name: str) -> int | None:
        """kind: "label" or "artist". Exact-name matches first (so "Trax Records" never becomes "Wax Trax!")."""
        q = urllib.parse.quote(f'{kind}:"{name}"')
        found = self._get("mb", f"{MB}/{kind}?query={q}&fmt=json&limit=5", days=30).get(f"{kind}s") or []
        # Same-named acts are common ("Fast Eddie": a Chicago producer, a UK mod band, a Toronto punk band).
        # This app is for house, so a candidate tagged or described as dance music wins, then MusicBrainz's score.
        found.sort(key=lambda x: (not _scene(x), not _same(x.get("name", ""), name), -int(x.get("score") or 0)))
        for cand in found[:3]:
            if not (_same(cand.get("name", ""), name) or int(cand.get("score") or 0) >= 90):
                continue
            rels = self._get("mb", f"{MB}/{kind}/{cand['id']}?inc=url-rels&fmt=json", days=30).get("relations") or []
            for r in rels:
                m = re.search(rf"discogs\.com/{kind}/(\d+)", (r.get("url") or {}).get("resource", ""))
                if m:
                    return int(m.group(1))
        return None

    # ---- labels ----------------------------------------------------------------------------
    def label(self, name: str, discogs_id: int | None = None) -> Entity:
        lid = discogs_id or self._discogs_id("label", name)
        if lid is None:
            return Entity("label", name, None)
        d = self._get("discogs", f"{DISCOGS}/labels/{lid}")
        related = []
        if d.get("parent_label"):
            related.append(("Parent label", clean_name(d["parent_label"].get("name", ""))))
        related += [("Sub-label", clean_name(s.get("name", ""))) for s in d.get("sublabels") or []][:24]
        return Entity("label", clean_name(d.get("name") or name), lid, _profile(d.get("profile", "")), related,
                      d.get("uri", ""))

    def label_releases(self, discogs_id: int, page: int = 1) -> Page:
        d = self._get("discogs", f"{DISCOGS}/labels/{discogs_id}/releases?sort=year&sort_order=asc"
                                 f"&per_page={PER_PAGE}&page={page}")
        rels = [Release(int(r["id"]), r.get("title", ""), clean_name(r.get("artist", "")), r.get("year") or None,
                        r.get("catno", ""), r.get("format", ""), "", r.get("thumb", ""))
                for r in d.get("releases") or [] if r.get("id")]
        return self._page(_dedupe(rels), d.get("pagination") or {}, page)

    # ---- artists ---------------------------------------------------------------------------
    def artist(self, name: str, discogs_id: int | None = None) -> Entity:
        aid = discogs_id or self._discogs_id("artist", name)
        if aid is None:
            return Entity("artist", name, None)
        d = self._get("discogs", f"{DISCOGS}/artists/{aid}")
        related = [("Also known as", clean_name(a.get("name", ""))) for a in d.get("aliases") or []][:12]
        related += [("Member of", clean_name(g.get("name", ""))) for g in d.get("groups") or []][:12]
        related += [("Members", clean_name(m.get("name", ""))) for m in d.get("members") or []][:12]
        return Entity("artist", clean_name(d.get("name") or name), aid, _profile(d.get("profile", "")), related,
                      d.get("uri", ""))

    def artist_releases(self, discogs_id: int, page: int = 1) -> Page:
        d = self._get("discogs", f"{DISCOGS}/artists/{discogs_id}/releases?sort=year&sort_order=asc"
                                 f"&per_page={PER_PAGE}&page={page}")
        rels = []
        for r in d.get("releases") or []:
            if not r.get("id"):
                continue
            rels.append(Release(int(r["id"]), r.get("title", ""), clean_name(r.get("artist", "")),
                                r.get("year") or None, "", r.get("format", ""), clean_name(r.get("label", "")),
                                r.get("thumb", ""), r.get("role", "")))
        return self._page(_dedupe(rels), d.get("pagination") or {}, page)

    # ---- one record, and a random one ----------------------------------------------------------
    def release(self, release_id: int) -> dict:
        """Details for a Spin: YouTube clips Discogs lists for it, tracklist, styles, a bigger cover."""
        d = self._get("discogs", f"{DISCOGS}/releases/{int(release_id)}")
        videos = [(v.get("title", ""), v["uri"]) for v in d.get("videos") or []
                  if str(v.get("uri", "")).startswith(("https://www.youtube.com/", "https://youtu.be/"))]
        tracks = [(t.get("position", ""), t.get("title", ""), t.get("duration", "")) for t in d.get("tracklist") or []
                  if t.get("type_", "track") == "track"]
        imgs = d.get("images") or []
        cover = next((i.get("uri") or i.get("uri150") for i in imgs if i.get("type") == "primary"), "") or \
            (imgs[0].get("uri") or imgs[0].get("uri150") if imgs else "")
        return {"videos": videos, "tracks": tracks, "styles": d.get("styles") or [], "genres": d.get("genres") or [],
                "cover": cover if str(cover).startswith("https://") else "", "url": d.get("uri", ""),
                "country": d.get("country", "")}

    def spin(self, labels: list[str], rng=None) -> tuple[Release, dict, str] | None:
        """A random record from a random one of `labels`: (release, details, label name). Prefers records that
        have a clip to listen to. A handful of requests the first time a label is used; cached after."""
        import random
        rng = rng or random.Random()
        order = list(labels); rng.shuffle(order)
        for name in order[:4]:
            ent = self.label(name)
            if not ent.discogs_id:
                continue
            first = self.label_releases(ent.discogs_id, 1)
            page = first if first.pages <= 1 else self.label_releases(ent.discogs_id, rng.randint(1, min(first.pages, 30)))
            pool = [r for r in page.releases if r.year and r.artist.lower() not in ("various", "unknown artist")]
            rng.shuffle(pool)
            fallback = None
            for r in pool[:4]:
                det = self.release(r.id)
                if det["videos"]:
                    return r, det, ent.name
                fallback = fallback or (r, det, ent.name)
            if fallback:
                return fallback
        return None

    def _page(self, rels: list[Release], pg: dict, page: int) -> Page:
        rels.sort(key=lambda r: (r.year is None, r.year or 0))   # undated pressings after the dated ones
        lib = self.library()
        for r in rels:
            r.owned = lib.owns(r.artist, r.title)
        return Page(rels, int(pg.get("page") or page), int(pg.get("pages") or 1), int(pg.get("items") or len(rels)))

    # ---- the library side (local only) ------------------------------------------------------
    def library(self) -> "LibraryIndex":
        version = self.db.library_version()
        if self._lib is None or self._lib[0] != version:
            self._lib = (version, LibraryIndex.build(self.db))
        return self._lib[1]


_SCENE = re.compile(r"house|techno|disco|garage|acid|electronic|dance|\bdj\b|producer|club|juke|footwork", re.I)


def _scene(cand: dict) -> bool:
    text = " ".join([cand.get("disambiguation") or "", *[t.get("name", "") for t in cand.get("tags") or []],
                     *[g.get("name", "") for g in cand.get("genres") or []]])
    return bool(_SCENE.search(text))


def _profile(text: str) -> str:
    """Discogs markup -> plain text: [a=Name] / [l=Name] / [url=...]text[/url] / [b] etc."""
    t = re.sub(r"\[(?:a|l)=([^\]]+)\]", lambda m: clean_name(m.group(1)), text or "")
    t = re.sub(r"\[(?:a|l|r|m)\d+\]", "", t)
    t = re.sub(r"\[url=[^\]]*\](.*?)\[/url\]", r"\1", t, flags=re.S)
    t = re.sub(r"\[/?[biu]\]", "", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _dedupe(rels: list[Release]) -> list[Release]:
    """Discogs lists every pressing; one row per artist+title+year reads like a crate, not a database."""
    seen, out = set(), []
    for r in rels:
        k = (norm(r.artist), norm(r.title), r.year)
        if k in seen:
            continue
        seen.add(k); out.append(r)
    return out


# ------------------------------------------------------------------------------------------ the library
@dataclass
class Track:
    job_id: str
    artist: str
    title: str
    label: str
    year: str
    bpm: float | None
    camelot: str
    added: str


@dataclass
class LibraryIndex:
    tracks: list[Track]
    _titles: dict[str, set[str]] = field(default_factory=dict)    # norm(artist) -> {norm(title)}

    @classmethod
    def build(cls, db) -> "LibraryIndex":
        from ..adapters.base import parse_track
        from ..media.metadata import clean_label, is_site_name
        tracks = []
        for j in db.jobs(states=(J.PROMOTED,), limit=100_000):
            a = db.analysis(j["id"]) or {}
            me, mu = a.get("meta") or {}, a.get("music") or {}
            p_artist, p_title, _ = parse_track(j.get("original_name") or "")
            artist = me.get("artist") or p_artist
            if is_site_name(artist):
                artist = p_artist if not is_site_name(p_artist) else ""
            tracks.append(Track(j["id"], artist, me.get("title") or p_title, clean_label(me.get("label") or ""),
                                str(me.get("year") or ""), mu.get("bpm"), mu.get("camelot") or "",
                                (j.get("updated_at") or "")[:19]))
        idx = cls(tracks)
        for t in tracks:
            for a in _artist_parts(t.artist):
                idx._titles.setdefault(a, set()).add(norm(t.title))
        return idx

    def owns(self, artist: str, title: str) -> bool:
        """A release counts as owned when a library track by that artist has its title (or the release title
        is the track's, e.g. a 12" named after its A-side)."""
        nt = norm(title)
        if not nt:
            return False
        for a in _artist_parts(artist):
            for have in self._titles.get(a, ()):
                if have and (have == nt or have in nt or nt in have):
                    return True
        return False

    def labels(self, limit: int = 12) -> list[tuple[str, int]]:
        counts: dict[str, tuple[str, int]] = {}
        for t in self.tracks:
            if t.label:
                k = norm(t.label)
                name, n = counts.get(k, (t.label, 0))
                counts[k] = (name, n + 1)
        return sorted(counts.values(), key=lambda x: (-x[1], x[0].lower()))[:limit]

    def artists(self, limit: int = 12) -> list[tuple[str, int]]:
        counts: dict[str, tuple[str, int]] = {}
        for t in self.tracks:
            for part in re.split(r"\s*(?:,|&| feat\.? | ft\.? | vs\.? | x | and )\s*", t.artist or "", flags=re.I):
                if part.strip():
                    k = norm(part)
                    name, n = counts.get(k, (part.strip(), 0))
                    counts[k] = (name, n + 1)
        return sorted(counts.values(), key=lambda x: (-x[1], x[0].lower()))[:limit]

    def recent(self, n: int = 5) -> list[Track]:
        return sorted(self.tracks, key=lambda t: t.added, reverse=True)[:n]

    def mixes_with(self, track: Track, limit: int = 4, bpm_tol: float = 0.04) -> list[Track]:
        """Library tracks that mix with `track`: a compatible key on the Camelot wheel and a tempo within
        about 4 % (half/double time counts). Same key first, then closest tempo."""
        from ..media.musical import compatible_keys
        if not (track.camelot and track.bpm):
            return []
        keys = compatible_keys(track.camelot)
        out = []
        for t in self.tracks:
            if t.job_id == track.job_id or not (t.camelot and t.bpm) or t.camelot not in keys:
                continue
            ratio = min(abs(t.bpm / track.bpm - f) for f in (0.5, 1.0, 2.0))
            if ratio <= bpm_tol:
                out.append((t.camelot != track.camelot, ratio, t))
        out.sort(key=lambda x: (x[0], x[1]))
        return [t for *_, t in out[:limit]]


def _artist_parts(artist: str) -> list[str]:
    parts = re.split(r"\s*(?:,|&| feat\.? | ft\.? | vs\.? | x | and )\s*", artist or "", flags=re.I)
    return [p for p in (norm(x) for x in parts) if p] or ([norm(artist)] if norm(artist) else [])
