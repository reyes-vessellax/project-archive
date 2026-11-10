"""Discover's rows, each anchored on something checked rather than on a folder name.

Label rows (search the network for "Trax Records", keep what's filed under it) let in whatever someone happened
to file there. Every row here is checked against MusicBrainz / Deezer before a track makes it:

- Style rows ("Deep house"): one network search for the style, then each artist must be known for that kind of
  music (MusicBrainz tags / description). An artist MusicBrainz lists as something else is dropped; one it doesn't
  know falls back to Deezer's genres (dance/electronic) plus the path test in crates.dance_only.
- Era crates ("Chicago jack, 1984-1990"): the hand-picked artists in eras.ERAS, a couple a day, one search per
  artist keeping only tracks BY that artist; records first released inside the era (MusicBrainz) come first.
- For you: Deezer's related artists for the artists already in the library, only tracks by those artists.

Lookups go through Discover._get (polite pacing, cached for weeks), so a row is slow only the first time.
"""
from __future__ import annotations

import random
import re
import urllib.parse
from collections import Counter

from ..adapters.base import parse_track
from . import crates as C
from ..media.metadata import similar
from .fuzzy import words
from .searching import collect

MB = "https://musicbrainz.org/ws/2"
VERIFY_MAX = 20          # tracks checked per row (each new artist/track is one MusicBrainz call at 1 a second)
TAG_DAYS = 90
YEAR_DAYS = 365

# What MusicBrainz must say about an artist (tags, genres, description). A STRONG word settles it; a WEAK one
# ("dance", "electronic") only counts when nothing says pop/rock/rap: Taylor Swift is tagged "dance-pop".
HOUSE = r"house|garage|techno|acid|juke|footwork|ghetto|disco|\bdj\b|club"
DISCO = r"disco|boogie|italo|cosmic|balearic|house|\bdj\b|club|edits?\b"
WEAK = r"dance|electro|electronic|edm|synth"
OTHER = re.compile(r"\bpop\b|-pop|pop-|rock|metal|punk|country|hip[ -]?hop|\brap\b|r&b|rnb|singer|songwriter|folk|"
                   r"actor|actress|band\b|indie|k-?pop|reggaeton|trap\b", re.I)
FAMILY = {"disco edit": DISCO, "nu disco": DISCO, "italo disco": DISCO, "cosmic disco": DISCO, "balearic": DISCO}


def main_artist(artist: str) -> str:
    return re.split(r"\s*(?:,|&| feat\.? | ft\.? | vs\.? | x | and | / )\s*", artist or "", flags=re.I)[0]


def _norm(s: str) -> str:
    return " ".join(w for w in words(s or "") if w != "the")


# ------------------------------------------------------------------------------------------ MusicBrainz
def _text(a: dict) -> str:
    return " ".join([a.get("disambiguation") or "", *[t.get("name", "") for t in a.get("tags") or []],
                     *[g.get("name", "") for g in a.get("genres") or []]]).strip()


def _remembered(engine, key: str, days: int):
    db = getattr(engine, "db", None)
    if db is None:
        return None
    hit = db.cache_get(key)
    if not hit:
        return None
    from datetime import datetime, timedelta, timezone
    data, at = hit
    try:
        if datetime.fromisoformat(at) > datetime.now(timezone.utc) - timedelta(days=days):
            return data.get("v")
    except ValueError:
        pass
    return None


def _remember(engine, key: str, value) -> None:
    db = getattr(engine, "db", None)
    if db is not None:
        db.cache_put(key, {"v": value})


BATCH = 8                # names per MusicBrainz request (one request a second: 8x faster than one by one)


def prefetch_profiles(engine, artists, cancelled=lambda: False) -> None:
    """Look up many artists in a few MusicBrainz requests (artist:"A" OR artist:"B" ...), remembering each.
    A name the batch doesn't answer is left for the one-by-one lookup."""
    todo = list(dict.fromkeys(main_artist(a) for a in artists if _norm(main_artist(a))))
    todo = [a for a in todo if _remembered(engine, "rows:mbartist:" + _norm(a), TAG_DAYS) is None]
    for i in range(0, len(todo), BATCH):
        if cancelled():
            return
        chunk = todo[i:i + BATCH]
        q = urllib.parse.quote(" OR ".join(f'artist:"{a}"' for a in chunk))
        try:
            found = engine._get("mb", f"{MB}/artist?query={q}&fmt=json&limit=100", days=TAG_DAYS).get("artists") or []
        except Exception:
            continue
        for a in chunk:
            want = _norm(a)
            texts = [_text(x) for x in found
                     if any(_norm(n) == want for n in [x.get("name", ""), x.get("sort-name", ""),
                                                       *[y.get("name", "") for y in x.get("aliases") or []]] if n)]
            if texts:
                _remember(engine, "rows:mbartist:" + want, texts)


def artist_profiles(engine, artist: str) -> list[str]:
    """MusicBrainz's description + tags + genres for every artist with exactly this name (there are often
    several: "Fast Eddie" is a Chicago producer, a UK band and a punk band). [] = not known; "" = one of
    that name MusicBrainz doesn't describe."""
    hit = _remembered(engine, "rows:mbartist:" + _norm(artist), TAG_DAYS)
    if hit is not None:
        return hit
    q = urllib.parse.quote(f'artist:"{artist}"')
    try:
        found = engine._get("mb", f"{MB}/artist?query={q}&fmt=json&limit=10", days=TAG_DAYS).get("artists") or []
    except Exception:
        return []
    out = [_text(a) for a in found if _named(a, artist)]   # "" = this one isn't described
    _remember(engine, "rows:mbartist:" + _norm(artist), out)
    return out


def _named(a: dict, artist: str) -> bool:
    """This MusicBrainz artist goes by this name: the name itself, an alias, or a top match that contains it
    ("Fast" Eddie Smith is Chicago's Fast Eddie)."""
    want = _norm(artist)
    names = [a.get("name", ""), a.get("sort-name", ""), *[x.get("name", "") for x in a.get("aliases") or []]]
    if any(_norm(n) == want for n in names if n) and int(a.get("score") or 0) >= 80:
        return True
    got = set(words(a.get("name", "")))
    return int(a.get("score") or 0) >= 95 and bool(want) and set(want.split()) <= got


def _fits(text: str, style: str) -> bool:
    strong = len(re.findall(FAMILY.get(style.lower(), HOUSE), text, re.I))
    other = len(OTHER.findall(text))
    if strong:
        return strong >= other                     # Dua Lipa: one "house" tag among eight pop ones
    return bool(re.search(WEAK, text, re.I)) and not other


def artist_fits(engine, artist: str, style: str) -> bool | None:
    """True: an artist of that name is known for this kind of music. False: known, only for something else.
    None: MusicBrainz doesn't say (Deezer decides)."""
    texts = artist_profiles(engine, main_artist(artist))
    if any(t and _fits(t, style) for t in texts):
        return True
    if not texts or "" in texts:
        return None                                # someone of that name it can't describe (FISHER): Deezer decides
    return False


def _year_key(artist: str, title: str) -> str:
    return "rows:mbyear:" + _norm(main_artist(artist)) + "|" + _norm(title)


def _q(s: str) -> str:
    return (s or "").replace('"', " ").replace("\\", " ")


def prefetch_years(engine, tracks, cancelled=lambda: False) -> None:
    """First release years for many tracks in a few requests: (artist:"A" AND recording:"T") OR (...)."""
    todo = [(main_artist(t.artist), t.title) for t in tracks]
    todo = [x for x in dict.fromkeys(todo) if _remembered(engine, _year_key(*x), YEAR_DAYS) is None]
    for i in range(0, len(todo), 5):
        if cancelled():
            return
        chunk = todo[i:i + 5]
        q = urllib.parse.quote(" OR ".join(f'(artist:"{_q(a)}" AND recording:"{_q(t)}")' for a, t in chunk))
        try:
            recs = engine._get("mb", f"{MB}/recording?query={q}&fmt=json&limit=100", days=YEAR_DAYS).get("recordings") or []
        except Exception:
            continue
        for a, t in chunk:
            years = []
            for r in recs:
                credit = " ".join(c.get("name", "") + " " + ((c.get("artist") or {}).get("name", ""))
                                  for c in r.get("artist-credit") or [])
                m = re.match(r"(\d{4})", r.get("first-release-date") or "")
                if m and similar(t, r.get("title", "")) >= 0.85 and _norm(a) in _norm(credit):
                    years.append(int(m.group(1)))
            if years:
                _remember(engine, _year_key(a, t), min(years))


def first_year(engine, artist: str, title: str) -> int | None:
    """The earliest release year MusicBrainz has for this recording by this artist."""
    hit = _remembered(engine, _year_key(artist, title), YEAR_DAYS)
    if hit is not None:
        return hit
    q = urllib.parse.quote(f'artist:"{main_artist(artist)}" AND recording:"{title}"')
    try:
        recs = engine._get("mb", f"{MB}/recording?query={q}&fmt=json&limit=10", days=YEAR_DAYS).get("recordings") or []
    except Exception:
        return None
    years = []
    for r in recs:
        m = re.match(r"(\d{4})", r.get("first-release-date") or "")
        if m and similar(title, r.get("title", "")) >= 0.85:
            years.append(int(m.group(1)))
    if years:
        _remember(engine, _year_key(artist, title), min(years))
    return min(years) if years else None


def era_span(years: str) -> tuple[int, int]:
    """"1984–1990" -> (1984, 1990); "2010–now" -> (2010, 9999)."""
    nums = [int(x) for x in re.findall(r"\d{4}", years or "")]
    if not nums:
        return (0, 9999)
    return (nums[0], nums[1] if len(nums) > 1 else 9999)


# ------------------------------------------------------------------------------------------ rows
def style_row(svc, engine, style: str, owns=lambda a, t: False, cancelled=lambda: False, log=None,
              use_cache: bool = True, deezer=None):
    """A style crate whose artists are checked: MusicBrainz first, Deezer for artists it doesn't know."""
    key = f"style {style}"
    if use_cache:
        hit = C.remembered(svc.db, key)
        if hit is not None:
            return hit
    if getattr(svc, "adapter", None) is None:
        return None
    res = collect(svc, style, C.SEARCH_S, budget=getattr(svc, "search_budget", None), cancelled=cancelled, log=log,
                  check_login=False)
    if res is None:
        return None
    _forget(svc, res)
    min_kbps = getattr(getattr(svc, "settings", None), "mp3_min_kbps", 320) or 320
    tracks = C.build(res.candidates, owns, min_kbps, style, "style")
    out = check_style(svc.db, engine, tracks, style, cancelled, deezer)
    C.remember(svc.db, key, out)
    return out


def check_style(db, engine, tracks, style: str, cancelled=lambda: False, deezer=None):
    """MusicBrainz yes: in. MusicBrainz doesn't know: Deezer's genres (or a dance word in the path, for artists
    Deezer doesn't know either). MusicBrainz no: in only if Deezer positively files them under dance, because
    MusicBrainz sometimes lists only namesakes (the tech house FISHER isn't in its top ten "Fisher"s)."""
    confirmed, unknown, disputed = [], [], []
    prefetch_profiles(engine, [t.artist for t in tracks[:VERIFY_MAX]], cancelled)
    for t in tracks[:VERIFY_MAX]:
        if cancelled():
            break
        fit = artist_fits(engine, t.artist, style)
        if fit is True:
            confirmed.append(t)
        elif fit is None:
            unknown.append(t)
        else:
            disputed.append(t)
    prefetch_genres(db, [t.artist for t in confirmed + unknown + disputed], deezer)
    # a MusicBrainz yes can be an obscure namesake ("Drake" the house DJ): Deezer names the famous one, and if
    # it files them firmly outside dance, they're out
    confirmed = [t for t in confirmed if not _deezer_says_other(db, t.artist, deezer)]
    unknown += [t for t in disputed                         # disputed, but Deezer says dance: same rules as unknown
                if set(C.artist_genres(db, main_artist(t.artist), deezer)) & C.DANCE_GENRES]
    return confirmed + C.dance_only(db, unknown, cancelled, deezer)


def _deezer_says_other(db, artist: str, lookup=None) -> bool:
    g = set(C.artist_genres(db, main_artist(artist), lookup))
    return bool(g) and not (g & C.DANCE_GENRES)


def prefetch_genres(db, artists, lookup=None) -> None:
    """Deezer genres for several artists at once (4 at a time; each is 2-4 small requests, remembered 90 days)."""
    names = list(dict.fromkeys(main_artist(a) for a in artists if main_artist(a)))
    if len(names) < 2:
        return
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(lambda a: C.artist_genres(db, a, lookup), names))


def artist_crate(svc, artist: str, owns=lambda a, t: False, cancelled=lambda: False, log=None,
                 use_cache: bool = True):
    """Tracks BY this artist that are ready now (one network search, remembered like any crate)."""
    key = f"by {artist}"
    if use_cache:
        hit = C.remembered(svc.db, key)
        if hit is not None:
            return hit
    if getattr(svc, "adapter", None) is None:
        return None
    res = collect(svc, artist, C.SEARCH_S, budget=getattr(svc, "search_budget", None), cancelled=cancelled, log=log,
                  check_login=False)
    if res is None:
        return None
    _forget(svc, res)
    min_kbps = getattr(getattr(svc, "settings", None), "mp3_min_kbps", 320) or 320
    out = by_artist(C.build(res.candidates, owns, min_kbps), artist)
    C.remember(svc.db, key, out)
    return out


def by_artist(tracks, artist: str):
    """Only tracks whose main artist IS this artist (a search for "Blaze" also finds "Blaze Ya Dead Homie")."""
    want = _norm(artist)
    return [t for t in tracks if want and (_norm(main_artist(t.artist)) == want or
                                           similar(main_artist(t.artist), artist) >= 0.93)]


def _forget(svc, res):
    try:
        svc.forget_search(res.search_id)
    except Exception:
        pass


def todays(items: list, n: int, day: int, salt: str = "") -> list:
    pool = list(items)
    random.Random(f"{day}:{salt}").shuffle(pool)
    return pool[:n]


def era_row(svc, engine, era: dict, day: int, owns=lambda a, t: False, cancelled=lambda: False, log=None,
            per_day: int = 2, check_year: bool = True):
    """An era crate: today's artists from the era's list, their tracks only, first released inside the era."""
    if getattr(svc, "adapter", None) is None and not any(C.remembered(svc.db, f"by {a}") for a in era["artists"]):
        return None
    lo, hi = era_span(era.get("years", ""))
    picked = todays(era["artists"], per_day, day, era["key"])
    lists = []
    for a in picked:
        if cancelled():
            break
        lists.append(artist_crate(svc, a, owns, cancelled, log) or [])
    tracks = interleave(lists)
    if not check_year:
        return tracks
    # The year only ORDERS the row (records from the era first): MusicBrainz's dates are too patchy to drop on
    # ("Can You Feel It" shows 2014, because the 1986 original is credited to Mr. Fingers). The artists are
    # already the era's own.
    prefetch_years(engine, tracks[:VERIFY_MAX], cancelled)
    def in_era(t):
        y = _remembered(engine, _year_key(t.artist, t.title), YEAR_DAYS)
        return 0 if y is not None and lo - 1 <= y <= hi + 1 else 1
    return sorted(tracks, key=in_era)


def interleave(lists):
    out, seen = [], set()
    for i in range(max((len(x) for x in lists), default=0)):
        for x in lists:
            if i < len(x) and x[i].key not in seen:
                seen.add(x[i].key); out.append(x[i])
    return out


# ------------------------------------------------------------------------------------------ for you
def library_artists(db, limit: int = 8) -> list[str]:
    """The artists the user has most of, most first."""
    from . import jobs as J
    n: Counter = Counter()
    names: dict[str, str] = {}
    for job in db.jobs(states=(J.PROMOTED,), limit=100_000):
        me = (db.analysis(job["id"]) or {}).get("meta") or {}
        a = main_artist(me.get("artist") or parse_track(job.get("original_name") or "")[0] or "")
        k = _norm(a)
        if k and k not in ("various", "various artists", "unknown", "unknown artist"):
            n[k] += 1; names.setdefault(k, a)
    return [names[k] for k, _ in n.most_common(limit)]


def related(db, artist: str, fetch=None) -> list[str]:
    """Deezer's related artists (remembered 30 days); [] when Deezer doesn't know the artist."""
    from datetime import datetime, timedelta, timezone
    from ..media.metadata import _json, http_get
    key = "discover:related:" + _norm(artist)
    hit = db.cache_get(key)
    if hit:
        data, at = hit
        try:
            if datetime.fromisoformat(at) > datetime.now(timezone.utc) - timedelta(days=30):
                return data.get("names") or []
        except ValueError:
            pass
    fetch = fetch or http_get
    try:
        hits = _json(fetch, f"https://api.deezer.com/search/artist?q={urllib.parse.quote(_norm(artist))}&limit=5").get("data") or []
        a = next((h for h in hits if _norm(h.get("name", "")) == _norm(artist)), None)
        names = [x.get("name", "") for x in (_json(fetch, f"https://api.deezer.com/artist/{int(a['id'])}/related?limit=20")
                                            .get("data") or [])] if a else []
    except Exception:
        return []
    names = [x for x in names if x]
    db.cache_put(key, {"names": names})
    return names


def for_you_artists(db, day: int, n: int = 3, fetch=None) -> tuple[list[str], list[str]]:
    """(today's related artists to dig, the library artists they came from)."""
    have = library_artists(db)
    if not have:
        return [], []
    mine = {_norm(a) for a in library_artists(db, 10_000)}
    seeds = todays(have[:6], 2, day, "seeds")
    pool, because = [], []
    for s in seeds:
        rel = [r for r in related(db, s, fetch) if _norm(r) not in mine]
        if rel:
            because.append(s)
            pool += [r for r in todays(rel[:12], n, day, s) if r not in pool]
    return pool[:n], because


def for_you_row(svc, day: int, owns=lambda a, t: False, cancelled=lambda: False, log=None, fetch=None):
    artists, because = for_you_artists(svc.db, day, fetch=fetch)
    if not artists:
        return [], because
    lists = []
    for a in artists:
        if cancelled():
            break
        lists.append(artist_crate(svc, a, owns, cancelled, log) or [])
    return interleave(lists), because
