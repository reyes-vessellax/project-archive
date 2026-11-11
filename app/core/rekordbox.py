"""Rekordbox export: a playlist as rekordbox.xml (the format Rekordbox imports under Preferences > Advanced >
rekordbox xml), with BPM, key, label, year, bitrate and cues from DigMart's own analysis.

Cues: hot cue A at the start of the audio, hot cue B at the drop (where the preview starts), plus a memory cue at
the drop, so it's on the CDJ's waveform too. No beat grid is written: Rekordbox analyses the grid itself (a wrong
grid is worse than none).

Optionally the files are copied (not moved) to a folder, e.g. a USB stick, and the XML points at the copies.
"""
from __future__ import annotations

import shutil
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

KIND = {"mp3": "MP3 File", "wav": "WAV File", "aiff": "AIFF File", "aif": "AIFF File", "flac": "FLAC File",
        "m4a": "M4A File"}


@dataclass
class RbTrack:
    path: Path
    title: str
    artist: str
    album: str = ""
    genre: str = ""
    label: str = ""
    year: str = ""
    bpm: float | None = None
    key: str = ""             # classic notation, e.g. "Am", "F#"
    seconds: float | None = None
    kbps: int | None = None
    sample_rate: int | None = None
    drop_s: float | None = None


def location(p: Path) -> str:
    """Rekordbox's file URL: file://localhost/<absolute path, percent-encoded>."""
    s = str(Path(p).resolve()).replace("\\", "/")
    if sys.platform == "win32" or (len(s) > 1 and s[1] == ":"):
        s = "/" + s                                        # C:/Music/x.mp3 -> /C:/Music/x.mp3
    return "file://localhost" + urllib.parse.quote(s, safe="/:")


def export(tracks: list[RbTrack], xml_path: Path, playlist: str, copy_to: Path | None = None, version: str = "") -> Path:
    if copy_to is not None:
        dest = Path(copy_to) / "DigMart" / _safe(playlist)
        dest.mkdir(parents=True, exist_ok=True)
        copied, used = [], set()
        for t in tracks:
            target = dest / t.path.name
            n = 2
            while target.name.lower() in used or (target.exists() and not _same_content(target, t.path)):
                target = dest / f"{t.path.stem} ({n}){t.path.suffix}"; n += 1    # same name, different file: keep both
            used.add(target.name.lower())
            if not target.exists():
                shutil.copy2(t.path, target)
            copied.append(RbTrack(**{**t.__dict__, "path": target}))
        tracks = copied
    root = ET.Element("DJ_PLAYLISTS", Version="1.0.0")
    ET.SubElement(root, "PRODUCT", Name="DigMart", Version=version or "1", Company="DigMart")
    coll = ET.SubElement(root, "COLLECTION", Entries=str(len(tracks)))
    for i, t in enumerate(tracks, 1):
        ext = t.path.suffix.lower().lstrip(".")
        attrs = {"TrackID": str(i), "Name": t.title, "Artist": t.artist, "Album": t.album, "Genre": t.genre,
                 "Label": t.label, "Year": t.year, "Kind": KIND.get(ext, "File"), "Location": location(t.path),
                 "Size": str(t.path.stat().st_size) if t.path.exists() else "0"}
        if t.seconds:
            attrs["TotalTime"] = str(int(round(t.seconds)))
        if t.bpm:
            attrs["AverageBpm"] = f"{t.bpm:.2f}"
        if t.key:
            attrs["Tonality"] = t.key
        if t.kbps:
            attrs["BitRate"] = str(t.kbps)
        if t.sample_rate:
            attrs["SampleRate"] = str(t.sample_rate)
        el = ET.SubElement(coll, "TRACK", {k: v for k, v in attrs.items() if v != ""})
        # hot cue A: the start; hot cue B + a memory cue: the drop (colours: DigMart yellow, crimson)
        ET.SubElement(el, "POSITION_MARK", Name="Start", Type="0", Start="0.000", Num="0", Red="255", Green="215", Blue="0")
        if t.drop_s and (not t.seconds or t.drop_s < t.seconds - 1):
            ET.SubElement(el, "POSITION_MARK", Name="Preview", Type="0", Start=f"{t.drop_s:.3f}", Num="1",
                          Red="220", Green="20", Blue="60")
            ET.SubElement(el, "POSITION_MARK", Name="Preview", Type="0", Start=f"{t.drop_s:.3f}", Num="-1")
    pls = ET.SubElement(root, "PLAYLISTS")
    top = ET.SubElement(pls, "NODE", Type="0", Name="ROOT", Count="1")
    node = ET.SubElement(top, "NODE", Name=playlist, Type="1", KeyType="0", Entries=str(len(tracks)))
    for i in range(1, len(tracks) + 1):
        ET.SubElement(node, "TRACK", Key=str(i))
    ET.indent(root)
    xml_path = Path(xml_path)
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(xml_path, encoding="UTF-8", xml_declaration=True)
    return xml_path


def _same_content(a: Path, b: Path) -> bool:
    """Reuse a copy already on the stick only if it IS this track: same size AND the same bytes (a same-name,
    same-size file can be a different track)."""
    import filecmp
    try:
        return a.stat().st_size == b.stat().st_size and filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


def _safe(name: str) -> str:
    out = "".join(ch if ch.isalnum() or ch in " -_()&'." else "_" for ch in name).strip(" .")
    return out or "Playlist"


def from_library(svc, job_ids: list[str]) -> list[RbTrack]:
    """Library jobs -> export rows, from DigMart's analysis (only files that still exist)."""
    from ..media.metadata import classic_key
    out = []
    for jid in job_ids:
        job = svc.db.job(jid)
        a = svc.db.analysis(jid) or {}
        p = Path((job or {}).get("final_path") or "")
        if not job or not p.is_file():
            continue
        me, mu, f = a.get("meta") or {}, a.get("music") or {}, a.get("facts") or {}
        tags = f.get("tags") or {}
        from ..adapters.base import parse_track
        pa, pt, _ = parse_track(job.get("original_name") or p.name)
        from ..media.metadata import clean_label
        out.append(RbTrack(p, me.get("title") or tags.get("title") or pt, me.get("artist") or tags.get("artist") or pa,
                           me.get("album") or "", me.get("genre") or "", clean_label(me.get("label") or ""),
                           str(me.get("year") or ""), mu.get("bpm"), classic_key(mu.get("key") or ""),
                           f.get("duration_s"), round(f["bitrate_bps"] / 1000) if f.get("bitrate_bps") else None,
                           f.get("sample_rate_hz"), mu.get("drop_s") or mu.get("preview_start_s")))
    return out
