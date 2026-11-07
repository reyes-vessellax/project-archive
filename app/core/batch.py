"""Batch: turn a playlist link, a pasted list, a CSV/M3U or a folder of files into a list of tracks to find.

Only track NAMES are read. Nothing is ever downloaded from YouTube, SoundCloud, Spotify or Apple Music:
- YouTube / SoundCloud: yt-dlp in "flat" mode (titles only, no media).
- Spotify: the public embed page of the playlist (up to ~100 tracks, the same data the embed widget shows).
- Apple Music: the public playlist page's embedded data.
Spotify and Apple Music pages change now and then; when a link can't be read the user is told to paste
the track list instead (always works). Then each track is searched once, with spacing, like a normal search.
"""
from __future__ import annotations

from . import net as _netmod

import csv
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..adapters.base import Candidate, parse_track
from ..media import metadata as md
from . import availability as av


@dataclass
class Wanted:
    artist: str
    title: str          # without the mix
    mix: str = ""
    source: str = ""    # "YouTube", "Spotify", "list", "folder: name.mp3"

    @property
    def query(self) -> str:
        return " ".join(x for x in (self.artist, self.title, self.mix if self.mix.lower() not in ("original mix", "") else "") if x)

    @property
    def label(self) -> str:
        t = f"{self.title} ({self.mix})" if self.mix else self.title
        return f"{self.artist} - {t}" if self.artist else t


# ------------------------------------------------------------------------------------- tidy titles
_NOISE = re.compile(
    r"[\(\[](?:official\s*(?:music\s*)?(?:video|audio|visuali[sz]er|lyric(?:s)?\s*video)|lyrics?|audio|video|hd|hq|4k|"
    r"visuali[sz]er|free\s*(?:download|dl)|out\s*now|premiere|explicit|clean|full\s*version)[^\)\]]*[\)\]]", re.I)
_PREFIX = re.compile(r"^\s*(?:premiere|free\s*download|free\s*dl|exclusive|out\s*now)\s*[:|\-–]\s*", re.I)
_SUFFIX = re.compile(r"\s*(?:\||//|•)\s*[^|]*$")          # "Title | Label Records" -> "Title"


def tidy(text: str) -> str:
    t = _NOISE.sub(" ", text or "")
    t = _PREFIX.sub("", t)
    t = _SUFFIX.sub("", t)
    return re.sub(r"\s+", " ", t).strip(" -–")


def wanted_from_title(title: str, uploader: str = "", source: str = "") -> Wanted | None:
    t = tidy(title)
    if not t:
        return None
    artist, name, mix = parse_track(t + ".x")
    if not artist and uploader:                          # "Track Name" uploaded by "Artist - Topic"
        artist = re.sub(r"\s*-\s*Topic$", "", uploader).strip()
    return Wanted(artist=artist, title=name, mix=mix, source=source)


# ------------------------------------------------------------------------------------- text inputs
def parse_text(text: str) -> list[Wanted]:
    """One track per line ("Artist - Title (Mix)"), a CSV export (Exportify, TuneMyMusic...), or an M3U."""
    text = (text or "").strip()
    if not text:
        return []
    first = text.splitlines()[0].lower()
    if ("," in first or ";" in first) and any(k in first for k in ("artist", "track", "title")):
        return _parse_csv(text)
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#EXTM3U"):
            continue
        if line.startswith("#EXTINF"):
            line = line.split(",", 1)[1] if "," in line else ""
        elif line.startswith("#") or re.match(r"^(?:[a-z]:\\|/|https?://)", line, re.I):
            continue                                     # M3U file paths and comments: the #EXTINF line has the name
        line = re.sub(r"^\s*\d{1,3}[.)]\s+", "", line)   # "1. Artist - Title"
        w = wanted_from_title(line, source="list")
        if w:
            out.append(w)
    return _dedupe(out)


def _parse_csv(text: str) -> list[Wanted]:
    dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;\t")
    rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    out = []
    for r in rows:
        low = {k.lower().strip(): (v or "").strip() for k, v in r.items() if k}
        title = next((low[k] for k in ("track name", "title", "track", "name", "song") if low.get(k)), "")
        artist = next((low[k] for k in ("artist name(s)", "artist name", "artists", "artist") if low.get(k)), "")
        artist = re.split(r"[;,]", artist)[0].strip()
        if title:
            a, t, m = parse_track(f"{artist} - {tidy(title)}.x" if artist else tidy(title) + ".x")
            out.append(Wanted(artist=a or artist, title=t, mix=m, source="CSV"))
    return _dedupe(out)


def from_folder(folder: Path, extensions=("mp3", "wav", "flac", "aiff", "aif", "m4a", "aac", "ogg")) -> list[Wanted]:
    """A folder of low-quality files you already have: find better copies. Tags first, else the file name."""
    out = []
    for p in sorted(folder.rglob("*")):
        if p.is_file() and p.suffix.lower().lstrip(".") in extensions and not p.is_symlink():
            tags = md.read_tags(p)
            fa, ft, fm = parse_track(p.name)
            if tags["title"] and tags["artist"]:
                a, t, m = parse_track(f"{tags['artist']} - {tags['title']}.x")
            else:
                a, t, m = fa, ft, fm
            out.append(Wanted(artist=a, title=t, mix=m, source=f"folder: {p.name}"))
    return _dedupe(out)


def _dedupe(items: list[Wanted]) -> list[Wanted]:
    seen, out = set(), []
    for w in items:
        k = (md.norm(w.artist), md.norm(w.title), w.mix.lower())
        if k not in seen and w.title:
            seen.add(k); out.append(w)
    return out


# ------------------------------------------------------------------------------------- playlist links
def service_of(url: str) -> str:
    u = url.lower()
    if "youtube.com" in u or "youtu.be" in u:
        return "YouTube"
    if "soundcloud.com" in u:
        return "SoundCloud"
    if "open.spotify.com" in u:
        return "Spotify"
    if "music.apple.com" in u:
        return "Apple Music"
    return ""


class LinkUnreadable(RuntimeError):
    """Plain-English reason; the UI suggests pasting the track list instead."""


def from_link(url: str, fetch: Callable[[str, float], bytes] | None = None) -> tuple[str, list[Wanted]]:
    """(playlist name, tracks)."""
    url = url.strip()
    if not url.lower().startswith("https://"):
        raise LinkUnreadable("Paste the full https:// link to the playlist.")
    svc = service_of(url)
    if svc in ("YouTube", "SoundCloud"):
        return _via_ytdlp(url, svc)
    fetch = fetch or _get_page
    if svc == "Spotify":
        return _spotify(url, fetch)
    if svc == "Apple Music":
        return _apple(url, fetch)
    raise LinkUnreadable("That link isn't from YouTube, SoundCloud, Spotify or Apple Music.")


def _get_page(url: str, timeout: float = 10.0) -> bytes:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/130 Safari/537.36",
                                               "Accept-Language": "en"})
    with _net_urlopen(req, timeout=timeout) as r:            # noqa: S310 - https, known hosts
        return r.read(16 * 1024 * 1024)


def _via_ytdlp(url: str, svc: str) -> tuple[str, list[Wanted]]:
    try:
        import yt_dlp
    except ImportError as e:
        raise LinkUnreadable(f"{svc} links need the yt-dlp component, which isn't in this build.") from e
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": False,
            "extract_flat": "in_playlist" if svc == "YouTube" else False, "playlistend": 500,
            "socket_timeout": 15}
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(url, download=False)
    except Exception as e:                                           # noqa: BLE001
        raise LinkUnreadable(f"Couldn't read that {svc} playlist. Is it public?") from e
    entries = info.get("entries") or [info]
    out = []
    for e in entries:
        if not e:
            continue
        w = wanted_from_title(e.get("track") and f"{e.get('artist', '')} - {e['track']}" or e.get("title", ""),
                              e.get("uploader") or e.get("channel") or "", svc)
        if w:
            out.append(w)
    return info.get("title") or f"{svc} playlist", _dedupe(out)


def _spotify(url: str, fetch) -> tuple[str, list[Wanted]]:
    m = re.search(r"open\.spotify\.com/(?:intl-\w+/)?(playlist|album)/([A-Za-z0-9]+)", url)
    if not m:
        raise LinkUnreadable("That doesn't look like a Spotify playlist or album link.")
    html = fetch(f"https://open.spotify.com/embed/{m.group(1)}/{m.group(2)}", 10.0).decode("utf-8", "replace")
    data = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    try:
        ent = json.loads(data.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
        items = ent.get("trackList") or []
    except Exception as e:                                           # noqa: BLE001
        raise LinkUnreadable("Spotify didn't share that playlist's track list. Paste the tracks instead.") from e
    out = []
    for t in items:
        artist = re.split(r",\s*", t.get("subtitle", ""))[0]
        a, ti, mx = parse_track(f"{artist} - {tidy(t.get('title', ''))}.x")
        out.append(Wanted(artist=a or artist, title=ti, mix=mx, source="Spotify"))
    return ent.get("name") or ent.get("title") or "Spotify playlist", _dedupe(out)


def _apple(url: str, fetch) -> tuple[str, list[Wanted]]:
    html = fetch(url, 10.0).decode("utf-8", "replace")
    out, name = [], "Apple Music playlist"
    blob = re.search(r'<script[^>]*id="serialized-server-data"[^>]*>(.*?)</script>', html, re.S)
    if blob:
        try:
            text = blob.group(1)
            for mt in re.finditer(r'"title":"((?:[^"\\]|\\.)*)","artistName":"((?:[^"\\]|\\.)*)"', text):
                t, a = json.loads(f'"{mt.group(1)}"'), json.loads(f'"{mt.group(2)}"')
                aa, ti, mx = parse_track(f"{a} - {tidy(t)}.x")
                out.append(Wanted(artist=aa or a, title=ti, mix=mx, source="Apple Music"))
            nm = re.search(r'<meta property="og:title" content="([^"]+)"', html)
            name = nm.group(1) if nm else name
        except Exception:                                            # noqa: BLE001
            out = []
    if not out:
        raise LinkUnreadable("Apple Music didn't share that playlist's track list. Paste the tracks instead.")
    return name, _dedupe(out)


# ------------------------------------------------------------------------------------- matching
def already_have(w: Wanted, library: list[tuple[str, str]]) -> bool:
    """library: (artist, title-with-mix) of tracks already saved."""
    for a, t in library:
        if md.similar(w.artist, a) >= 0.9 and md.similar(w.title, t) >= 0.9:
            want_mix = w.mix.lower()
            if not want_mix or want_mix in t.lower():
                return True
    return False


def score(c: Candidate, w: Wanted) -> float:
    """Higher is better: right track first, then right mix, then quality, then how soon it can start."""
    if c.locked or c.note:
        return -1.0
    name_ok = md.similar(w.title, c.title or c.display_name)
    art_ok = 1.0 if not w.artist else max(md.similar(w.artist, c.artist), 1.0 if md.norm(w.artist) in md.norm(c.display_name) else 0.0)
    if name_ok < 0.8 or art_ok < 0.8:
        return -1.0
    s = name_ok * 4 + art_ok * 3
    if w.mix:
        s += 2 if md.norm(w.mix) and md.norm(w.mix) in md.norm(f"{c.mix} {c.display_name}") else -2
    elif c.mix and not av.mix_kind_matches(c, "original"):
        s -= 1                                            # asked for the plain track, this is a remix
    ext = (c.extension or "").lower()
    s += 2 if ext in ("flac", "aiff", "aif", "wav") else (1 if (c.bitrate_kbps or 0) >= 320 else -3)
    s -= av.availability(c).rank * 0.8
    return s


def best(cands: list[Candidate], w: Wanted) -> Candidate | None:
    scored = [(score(c, w), c) for c in cands]
    scored = [x for x in scored if x[0] > 0]
    return max(scored, key=lambda x: x[0])[1] if scored else None


def _net_urlopen(req, timeout=15.0):
    return _netmod.urlopen(req, timeout=timeout)
