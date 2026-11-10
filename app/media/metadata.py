"""Track metadata: read what the file already says, look up what's missing, write Rekordbox-ready tags.

Lookup order (first confident match wins; the cover comes from the first source that has one):
  1. the file's own tags and embedded artwork
  2. Deezer          - strong on electronic releases: label, date, genre, 1000 px covers
  3. MusicBrainz     - open database; cover from the Cover Art Archive
  4. iTunes Search   - broad catalogue; artwork up to 1000 px
Only the artist and title are sent, never audio or anything about the user. A weak match is treated as
no match: a wrong cover is worse than none.

Tags written for Rekordbox (and Serato/Traktor/Finder):
  MP3/AIFF/WAV (ID3v2.3): TIT2 title (mix in brackets), TPE1 artist, TALB album, TPUB label, TCON genre,
  TYER year, TBPM bpm, TKEY key (classic notation, e.g. "Am"; Rekordbox can display it as 8A), COMM, APIC.
  FLAC (Vorbis): TITLE, ARTIST, ALBUM, LABEL, ORGANIZATION, GENRE, DATE, BPM, INITIALKEY, COMMENT, picture.
Existing tags are kept; we only fill gaps (and BPM/key, which we measured).
"""
from __future__ import annotations

from ..core import net as _netmod

import json
import re
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

from ..config import APP_NAME, APP_VERSION

USER_AGENT = f"{APP_NAME.replace(' ', '')}/{APP_VERSION} ( https://github.com/reyes-vessellax/project-archive )"
MATCH = 0.86            # minimum similarity for artist and title


@dataclass
class Meta:
    title: str = ""            # without the mix
    mix: str = ""              # "Extended Mix"
    artist: str = ""
    album: str = ""
    label: str = ""
    catalog: str = ""
    year: str = ""
    genre: str = ""
    cover_url: str = ""
    source: str = ""           # "file", "Deezer", "MusicBrainz", "iTunes"
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def full_title(self) -> str:
        return f"{self.title} ({self.mix})" if self.mix and self.mix.lower() not in self.title.lower() else self.title


# ------------------------------------------------------------------------------------------ matching
def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\((feat|ft)\.?[^)]*\)|\b(feat|ft|featuring)\.?\s.*$", " ", s)
    s = re.sub(r"[\(\[].*?[\)\]]", " ", s)                       # drop (Extended Mix), [Label]
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def similar(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def artist_ok(want: str, got: str) -> bool:
    if similar(want, got) >= MATCH:
        return True
    # "A & B" vs "A": accept when the wanted main artist is one of the credited names
    parts = [norm(p) for p in re.split(r",|&| x | and |feat\.?|ft\.?", got or "", flags=re.I) if norm(p)]
    return norm(want) in parts or any(similar(want, p) >= 0.93 for p in parts)


# ------------------------------------------------------------------------------------------ network
Fetch = Callable[[str, float], bytes]


def http_get(url: str, timeout: float = 6.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with _net_urlopen(req, timeout=timeout) as r:            # noqa: S310 - fixed https hosts only
        return r.read(8 * 1024 * 1024)


def _json(fetch: Fetch, url: str) -> dict:
    try:
        return json.loads(fetch(url, 6.0).decode("utf-8", "replace"))
    except Exception:
        return {}


def from_deezer(artist: str, title: str, fetch: Fetch) -> Meta | None:
    q = urllib.parse.quote(f"{norm(artist)} {norm(title)}")   # plain search: Deezer stopped answering artist:/track:
    data = _json(fetch, f"https://api.deezer.com/search?q={q}&limit=10").get("data") or []
    for t in data:
        if similar(title, t.get("title_short") or t.get("title", "")) >= MATCH and \
                artist_ok(artist, (t.get("artist") or {}).get("name", "")):
            alb = t.get("album") or {}
            m = Meta(artist=(t.get("artist") or {}).get("name", ""), album=alb.get("title", ""),
                     cover_url=alb.get("cover_xl") or alb.get("cover_big") or "", source="Deezer")
            if alb.get("id"):
                a = _json(fetch, f"https://api.deezer.com/album/{int(alb['id'])}")
                m.label = a.get("label", "") or ""
                m.year = (a.get("release_date") or "")[:4]
                genres = (a.get("genres") or {}).get("data") or []
                m.genre = genres[0].get("name", "") if genres else ""
            return m
    return None


def deezer_artist_genres(artist: str, fetch: Fetch = None) -> list[str]:
    """Genres of an artist's top releases on Deezer (most common first); [] when the artist isn't found.
    Only an exact-name match counts, so a house producer isn't judged by someone else's records."""
    fetch = fetch or http_get
    hits = _json(fetch, f"https://api.deezer.com/search/artist?q={urllib.parse.quote(norm(artist))}&limit=5").get("data") or []
    a = next((h for h in hits if norm(h.get("name", "")) == norm(artist)), None)
    if not a:
        return []
    top = _json(fetch, f"https://api.deezer.com/artist/{int(a['id'])}/top?limit=5").get("data") or []
    counts: dict[str, int] = {}
    for alb_id in list(dict.fromkeys((t.get("album") or {}).get("id") for t in top))[:3]:
        if not alb_id:
            continue
        for g in ((_json(fetch, f"https://api.deezer.com/album/{int(alb_id)}").get("genres") or {}).get("data") or []):
            counts[g.get("name", "")] = counts.get(g.get("name", ""), 0) + 1
    return [g for g, _ in sorted(counts.items(), key=lambda x: -x[1]) if g]


def deezer_cover(artist: str, title: str, fetch: Fetch = None) -> str:
    """Just a cover image URL for a track (one Deezer search, no album call); "" when nothing matches."""
    fetch = fetch or http_get
    q = urllib.parse.quote(f"{norm(artist)} {norm(title)}")   # plain search: Deezer stopped answering artist:/track:
    for t in _json(fetch, f"https://api.deezer.com/search?q={q}&limit=5").get("data") or []:
        if similar(title, t.get("title_short") or t.get("title", "")) >= MATCH and \
                artist_ok(artist, (t.get("artist") or {}).get("name", "")):
            alb = t.get("album") or {}
            return alb.get("cover_medium") or alb.get("cover_big") or ""
    return ""


def from_musicbrainz(artist: str, title: str, fetch: Fetch) -> Meta | None:
    q = urllib.parse.quote(f'recording:"{norm(title)}" AND artist:"{norm(artist)}"')
    recs = _json(fetch, f"https://musicbrainz.org/ws/2/recording?query={q}&fmt=json&limit=8").get("recordings") or []
    for r in recs:
        credit = " & ".join(c.get("name", "") for c in r.get("artist-credit") or [])
        if r.get("score", 0) < 85 or similar(title, r.get("title", "")) < MATCH or not artist_ok(artist, credit):
            continue
        rels = sorted(r.get("releases") or [], key=lambda x: x.get("date") or "9999")
        for rel in rels:
            m = Meta(artist=credit, album=rel.get("title", ""), year=(rel.get("date") or "")[:4], source="MusicBrainz")
            info = _json(fetch, f"https://musicbrainz.org/ws/2/release/{rel['id']}?inc=labels+genres&fmt=json")
            li = (info.get("label-info") or [{}])[0] if info.get("label-info") else {}
            m.label = clean_label((li.get("label") or {}).get("name") or "")
            m.catalog = li.get("catalog-number") or ""
            g = info.get("genres") or []
            m.genre = g[0]["name"].title() if g else ""
            if (info.get("cover-art-archive") or {}).get("front"):
                m.cover_url = f"https://coverartarchive.org/release/{rel['id']}/front-1200"
            return m
    return None


def from_itunes(artist: str, title: str, fetch: Fetch) -> Meta | None:
    term = urllib.parse.quote(f"{norm(artist)} {norm(title)}")
    for t in _json(fetch, f"https://itunes.apple.com/search?term={term}&entity=song&limit=10").get("results") or []:
        if similar(title, t.get("trackName", "")) >= MATCH and artist_ok(artist, t.get("artistName", "")):
            art = (t.get("artworkUrl100") or "").replace("100x100bb", "1000x1000bb")
            return Meta(artist=t.get("artistName", ""), album=t.get("collectionName", ""),
                        year=(t.get("releaseDate") or "")[:4], genre=t.get("primaryGenreName", ""),
                        cover_url=art, source="iTunes")
    return None


PROVIDERS = (from_deezer, from_musicbrainz, from_itunes)


def lookup(artist: str, title: str, fetch: Fetch = http_get, providers=PROVIDERS) -> Meta | None:
    """Merge confident matches: the first match fills most fields; later ones only fill gaps (cover too)."""
    if not artist or not title:
        return None
    merged: Meta | None = None
    for p in providers:
        try:
            m = p(artist, title, fetch)
        except Exception:
            m = None
        if not m:
            continue
        if merged is None:
            merged = m
            merged.sources = [m.source]
        else:
            for k in ("album", "label", "catalog", "year", "genre", "cover_url"):
                if not getattr(merged, k) and getattr(m, k):
                    setattr(merged, k, getattr(m, k))
                    if m.source not in merged.sources:
                        merged.sources.append(m.source)
        if merged.cover_url and merged.label and merged.genre and merged.year:
            break
    return merged


def download_cover(url: str, dest: Path, fetch: Fetch = http_get) -> Path | None:
    if not url.startswith("https://"):
        return None
    try:
        data = fetch(url, 10.0)
    except Exception:
        return None
    if data[:3] == b"\xff\xd8\xff":
        dest = dest.with_suffix(".jpg")
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        dest = dest.with_suffix(".png")
    else:
        return None                                        # not an image: never write it
    dest.write_bytes(data)
    return dest


# ------------------------------------------------------------------------------------------ junk in tags
# Download sites, record pools and rippers stamp their name where the label (or artist) should be:
# "DJDownloadMe.com", "www.xyz.ru", "Promo Only", "320kbps". None of that is a label you can dig.
_URL = re.compile(r"(https?://|www\.|\b[a-z0-9-]+\.(com|net|org|info|ru|to|cc|me|io|biz|co|us|uk|de|fm|club|xyz|pw|top|site|online|store)\b)", re.I)
_JUNK = re.compile(r"\b(download|downloads|mp3|kbps|320|flac|free\s*dl|zippy|promo\s*only|record\s*pool|dj\s*pool|"
                   r"beatport|traxsource|juno\s*download|bandcamp|soundcloud|youtube|spotify|deezer|telegram|vk\.com|"
                   r"ripped|vinyl\s*rip|unknown|not\s+on\s+label|no\s+label|n/?a)\b", re.I)


def clean_label(text: str) -> str:
    """A label as found in tags or a lookup, or "" when it's a download site, URL or placeholder."""
    t = (text or "").strip().strip("[]()").strip()
    if (not t or len(t) > 80 or _URL.search(t) or _JUNK.search(t) or re.search(r"\d\s*kbps", t, re.I)
            or t.lower() in ("none", "null", "label", "records", "untitled", "white label", "self released", "self-released")
            or not re.search(r"[A-Za-z]", t)):
        return ""
    return t


def is_site_name(text: str) -> bool:
    """For artists: only an obvious web address is thrown out (artist names legitimately contain any word)."""
    return bool(_URL.search(text or ""))


# ------------------------------------------------------------------------------------------ the file
def read_tags(path: Path) -> dict:
    """Title/artist/album/label/genre/year/bpm/key + whether there's embedded art, from any supported file."""
    out = {"title": "", "artist": "", "album": "", "label": "", "genre": "", "year": "", "bpm": "", "key": "",
           "has_cover": False}
    try:
        import mutagen
        f = mutagen.File(str(path))
    except Exception:
        return out
    if f is None or f.tags is None:
        return out
    tags = f.tags
    if hasattr(tags, "getall"):                                    # ID3 (mp3, aiff, wav)
        def one(fid):
            fr = tags.get(fid)
            return str(fr.text[0]) if fr is not None and getattr(fr, "text", None) else ""
        out.update(title=one("TIT2"), artist=one("TPE1"), album=one("TALB"), label=one("TPUB"), genre=one("TCON"),
                   year=(one("TDRC") or one("TYER"))[:4], bpm=one("TBPM"), key=one("TKEY"),
                   has_cover=bool(tags.getall("APIC")))
    else:                                                          # Vorbis comments (flac)
        def one(k):
            v = tags.get(k) or tags.get(k.upper()) or tags.get(k.lower())
            return str(v[0]) if v else ""
        out.update(title=one("TITLE"), artist=one("ARTIST"), album=one("ALBUM"),
                   label=one("LABEL") or one("ORGANIZATION"), genre=one("GENRE"), year=one("DATE")[:4],
                   bpm=one("BPM"), key=one("INITIALKEY"), has_cover=bool(getattr(f, "pictures", None)))
    return out


def classic_key(key_name: str) -> str:
    """"A minor" -> "Am", "Eb major" -> "Eb" (what Rekordbox and most DJ software read from TKEY)."""
    if not key_name:
        return ""
    note, _, mode = key_name.partition(" ")
    return note + ("m" if mode == "minor" else "")


def write_tags(path: Path, meta: Meta | None, musical: dict | None, cover: Path | None, ext: str = "") -> list[str]:
    """Fill missing tags (never overwrite what the file already has, except BPM/key which we measured).
    Returns the names of the fields written."""
    from mutagen.flac import FLAC, Picture
    from mutagen.id3 import APIC, COMM, ID3, TALB, TBPM, TCON, TIT2, TKEY, TPE1, TPUB, TYER, ID3NoHeaderError

    have = read_tags(path)
    m = meta or Meta()
    want = {
        "title": m.full_title, "artist": m.artist, "album": m.album, "label": m.label,
        "genre": m.genre, "year": m.year,
    }
    fill = {k: v for k, v in want.items() if v and not have.get(k)}
    mu = musical or {}
    if mu.get("bpm"):
        fill["bpm"] = str(int(round(float(mu["bpm"]))))           # integer: what DJ software reads reliably
    if mu.get("key"):
        fill["key"] = classic_key(mu["key"])
    comment = " · ".join(x for x in (mu.get("camelot") or "", fill.get("bpm", ""),
                                     f"preview {int(mu['drop_s']) // 60}:{int(mu['drop_s']) % 60:02d}" if mu.get("drop_s") else "")
                         if x)
    art = cover.read_bytes() if cover and cover.is_file() and not have["has_cover"] else None
    mime = "image/png" if cover and cover.suffix == ".png" else "image/jpeg"
    written = list(fill)

    ext = (ext or path.suffix).lower()          # the save works on a .part copy: the caller passes the real type
    if ext == ".flac":
        f = FLAC(str(path))
        names = {"title": "TITLE", "artist": "ARTIST", "album": "ALBUM", "genre": "GENRE", "year": "DATE",
                 "bpm": "BPM", "key": "INITIALKEY"}
        for k, v in fill.items():
            if k == "label":
                f["LABEL"] = v; f["ORGANIZATION"] = v
            else:
                f[names[k]] = v
        if comment and not f.get("COMMENT"):
            f["COMMENT"] = comment; written.append("comment")
        if art:
            pic = Picture(); pic.type = 3; pic.mime = mime; pic.desc = "Cover"; pic.data = art
            f.add_picture(pic); written.append("cover")
        f.save()
        return written

    if ext in (".aiff", ".aif"):
        from mutagen.aiff import AIFF
        f = AIFF(str(path))
        if f.tags is None:
            f.add_tags()
        tags, saver = f.tags, (lambda: f.save(v2_version=3))
    elif ext == ".wav":
        from mutagen.wave import WAVE
        f = WAVE(str(path))
        if f.tags is None:
            f.add_tags()
        tags, saver = f.tags, (lambda: f.save(v2_version=3))
    else:                                                          # mp3
        try:
            tags = ID3(str(path))
        except ID3NoHeaderError:
            tags = ID3()
        saver = (lambda: tags.save(str(path), v2_version=3))
    frames = {"title": TIT2, "artist": TPE1, "album": TALB, "label": TPUB, "genre": TCON, "year": TYER,
              "bpm": TBPM, "key": TKEY}
    for k, v in fill.items():
        tags.setall(frames[k].__name__, [frames[k](encoding=3, text=v)])
    if comment and not tags.getall("COMM"):
        tags.add(COMM(encoding=3, lang="eng", desc="", text=comment)); written.append("comment")
    if art:
        tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=art)); written.append("cover")
    saver()
    return written


def cover_from_file(path: Path, dest: Path) -> Path | None:
    """Pull embedded artwork out (for showing it in the app)."""
    try:
        import mutagen
        f = mutagen.File(str(path))
    except Exception:
        return None
    data = None
    if f is not None and getattr(f, "pictures", None):
        data = f.pictures[0].data
    elif f is not None and f.tags is not None and hasattr(f.tags, "getall") and f.tags.getall("APIC"):
        data = f.tags.getall("APIC")[0].data
    if not data:
        return None
    dest = dest.with_suffix(".png" if data[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg")
    dest.write_bytes(data)
    return dest


def _net_urlopen(req, timeout=15.0):
    return _netmod.urlopen(req, timeout=timeout)
