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
GENRE_DAYS = 90          # an artist's genres are looked up once and remembered this long

# Dance and electronic genres as Deezer names them. An artist with none of these on their top releases is left out.
DANCE_GENRES = {"Dance", "Electro", "Techno/House", "Disco", "Soul & Funk", "Electronic", "House", "Techno",
                "Deep House", "Electro Pop/Electro Rock"}
# Words in a file's path that mean it isn't dance music (searches match words anywhere in the path:
# "Chicago" + "House" finds a metal band's "Live in Chicago / House of Blues" too).
NOT_DANCE = re.compile(r"\b(metal|metalcore|deathcore|thrash|grunge|punk rock|post[- ]punk|pop[- ]punk|"
                       r"(hard|classic|indie|alt|alternative|prog|progressive|soft|folk|southern|garage|glam|stoner|"
                       r"psychedelic|blues) rock|rock (and|n|&) roll|rockabilly|emo|screamo|country|bluegrass|americana|"
                       r"folk|singer[- ]songwriter|acoustic|unplugged|blues|hymns?|worship|classical|orchestra|orchestral|"
                       r"symphon\w*|sonatas?|concertos?|opera|choir|piano solo|baroque|bach|mozart|beethoven|chopin|"
                       r"audiobook|podcast|soundtrack|karaoke|nightcore|christmas|xmas|lullab\w*|meditation|"
                       r"relaxation|hip[- ]?hop|reggaeton|k-?pop|j-?pop|anime|bollywood|polka|mariachi|schlager)\b", re.I)
# Positive signs of dance music in a path: an artist Deezer doesn't know needs one of these to stay.
DANCE_CUE = re.compile(r"\b(house|techno|disco|garage|acid|club|dance|electro\w*|edits?|remix\w*|rmx|dub|"
                       r"12[\"']?\s?(inch|in)|12in|maxi|white label|dj|jack\w*|minimal)\b", re.I)
MIN_SECONDS = 240        # club length: DJs need the intro and outro; radio edits and short versions never make it
SHORT_VERSION = re.compile(r"\b(radio|short|single|intro|7\"|7 inch|tv)\s*(edit|mix|version|cut)\b|[(\[]\s*radio\s*[)\]]", re.I)
# (a bare "radio" isn't enough: Radio Slave, Radio 4, "Pirate Radio" are all club records)


def length_s(c: Candidate) -> float | None:
    """The track length the source reports, or a fair estimate from the file size: WAV/AIFF are 10.1 MB a minute at
    CD quality, an MP3 is size / bitrate, FLAC roughly 6 MB a minute."""
    if c.length_s:
        return float(c.length_s)
    ext = (c.extension or "").lower()
    if not c.size:
        return None
    if ext in ("wav", "aiff", "aif"):
        sr, bits = c.sample_rate_hz or 44100, c.bit_depth or 16
        return c.size / (sr * bits / 8 * 2)
    if ext == "mp3" and c.bitrate_kbps:
        return c.size * 8 / (c.bitrate_kbps * 1000)
    if ext == "flac":
        return c.size / (6_000_000 / 60)
    return None


def club_length(c: Candidate) -> bool:
    """4 minutes or longer, and not a radio/short/intro edit by name. Unknown length: kept unless it's named as an edit."""
    if SHORT_VERSION.search(f"{c.mix} {c.title} {c.display_name}"):
        return False
    secs = length_s(c)
    return secs is None or secs >= MIN_SECONDS


_NOISE = {"records", "recordings", "music", "label", "the", "inc", "ltd", "presents"}
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


def phrase(query: str) -> list[str]:
    """The words that must appear TOGETHER in a path: "Trax Records" -> ["trax"], "Chicago house" -> ["chicago", "house"]."""
    ws = [w for w in words(query) if w not in _NOISE]
    return ws or words(query)


def on_topic(c: Candidate, query: str, kind: str = "") -> bool:
    """The query's words side by side within one folder or file name, nothing in the path saying "not dance", and
    for a label: its name next to "Records"/"Recordings" or a catalogue number (so "Prelude" isn't Bach)."""
    path = c.remote_path or f"{c.folder} {c.display_name}"
    if NOT_DANCE.search(path):
        return False
    if kind == "label" and not (re.search(r"\b(records|recordings|rec)\b", path, re.I) or _CATNO.search(path)):
        return False
    stem = lambda ws_: [w[:-1] if len(w) > 3 and w.endswith("s") else w for w in ws_]   # "edits" counts for "edit"
    ws = stem(phrase(query)); n = len(ws)
    for seg in re.split(r"[\\/]", path):                  # within ONE folder or file name, not across two
        p = stem(words(seg))
        if any(p[i:i + n] == ws for i in range(len(p) - n + 1)):
            return True
    return False


def build(cands: list[Candidate], owns=lambda a, t: False, min_kbps: int = 320, query: str = "",
          kind: str = "") -> list[CrateTrack]:
    """Search results -> one entry per track, best copy first, ready-now only, on topic."""
    groups: dict[str, CrateTrack] = {}
    for c in cands:
        if not (_good(c, min_kbps) and c.free_slot and not (c.queue_length or 0)):
            continue
        if not club_length(c):
            continue
        if query and not on_topic(c, query, kind):
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
    return "discover:crate4:" + " ".join(words(query))        # crate4: + club length (4 min+, no radio edits)


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


def crate(svc, query: str, owns=lambda a, t: False, cancelled=lambda: False, log=None, use_cache: bool = True,
          kind: str = ""):
    """The crate for a label or artist name: from memory when fresh, else one network search."""
    if use_cache:
        hit = remembered(svc.db, query)
        if hit is not None:
            return hit
    if getattr(svc, "adapter", None) is None:
        return None
    res = collect(svc, query, SEARCH_S, budget=getattr(svc, "search_budget", None), cancelled=cancelled, log=log,
                  check_login=False, background=True)
    if res is None:
        return None
    try:
        svc.forget_search(res.search_id)
    except Exception:
        pass
    min_kbps = getattr(getattr(svc, "settings", None), "mp3_min_kbps", 320) or 320
    tracks = dance_only(svc.db, build(res.candidates, owns, min_kbps, query, kind), cancelled)
    remember(svc.db, query, tracks)
    return tracks


def artist_genres(db, artist: str, lookup=None) -> list[str]:
    """Deezer genres for an artist, remembered for GENRE_DAYS. [] = unknown."""
    from ..media.metadata import deezer_artist_genres
    key = "discover:genre:" + " ".join(words(artist))
    hit = db.cache_get(key)
    if hit:
        data, at = hit
        try:
            if datetime.fromisoformat(at) > datetime.now(timezone.utc) - timedelta(days=GENRE_DAYS):
                return data.get("genres") or []
        except ValueError:
            pass
    try:
        g = (lookup or deezer_artist_genres)(artist)
    except Exception:
        return []
    db.cache_put(key, {"genres": g})
    return g


def dance_only(db, tracks: list[CrateTrack], cancelled=lambda: False, lookup=None) -> list[CrateTrack]:
    """Drop tracks by artists whose releases are known to be something other than dance/electronic music.
    Artists Deezer doesn't know stay (they already passed the path checks)."""
    out = []
    for t in tracks:
        if cancelled():
            break
        main = re.split(r"\s*(?:,|&| feat\.? | ft\.? | vs\.? | x | and | / )\s*", t.artist, flags=re.I)[0]
        g = artist_genres(db, main, lookup)
        if g and not (set(g) & DANCE_GENRES):
            continue                                       # known, and not dance/electronic
        if not g and not DANCE_CUE.search(f"{t.best.remote_path} {t.folder} {t.title} {t.mix}"):
            continue                                       # unknown artist and nothing in the path says dance
        out.append(t)
    return out
