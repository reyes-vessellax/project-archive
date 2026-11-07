"""How accurate are DigMart's BPM and key readings? Compare them with a reference you trust.

  python -m tools.accuracy <folder>                    reference = the BPM/key tags in the files
  python -m tools.accuracy <folder> --xml rekordbox.xml reference = a Rekordbox collection export

Rekordbox: File > Export Collection in xml format. Beatport files already carry BPM and key tags.
Writes accuracy.csv next to the folder and prints a summary:
  BPM  exact (within 0.5) · off by double/half · wrong
  key  exact · a neighbour on the Camelot wheel (±1) · relative major/minor · wrong
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

from app.media.musical import CAMELOT_MAJOR, CAMELOT_MINOR, NOTES, analyze_music

AUDIO = {".mp3", ".flac", ".wav", ".aif", ".aiff", ".m4a", ".ogg"}
_NAMES = {n.lower(): i for i, n in enumerate(NOTES)}
_NAMES.update({"db": 1, "d#": 3, "gb": 6, "g#": 8, "a#": 10, "cb": 11, "fb": 4, "e#": 5, "b#": 0})


def to_camelot(text: str | None) -> str | None:
    """'8A', '08A', 'Am', 'A minor', 'Abm', 'F#', 'C maj'... -> Camelot code."""
    if not text:
        return None
    t = text.strip().replace("♯", "#").replace("♭", "b")
    m = re.fullmatch(r"0?(\d{1,2})\s*([ABab])", t)
    if m and 1 <= int(m.group(1)) <= 12:
        return f"{int(m.group(1))}{m.group(2).upper()}"
    m = re.fullmatch(r"([A-Ga-g][#b]?)\s*(m|min|minor|maj|major|)\.?", t)
    if not m:
        return None
    pc = _NAMES.get(m.group(1)[0].upper().lower() + m.group(1)[1:].lower())
    if pc is None:
        return None
    minor = m.group(2).lower() in ("m", "min", "minor")
    return f"{CAMELOT_MINOR[pc]}A" if minor else f"{CAMELOT_MAJOR[pc]}B"


def key_relation(got: str | None, want: str | None) -> str:
    if not got or not want:
        return "n/a"
    if got == want:
        return "exact"
    gn, gl, wn, wl = int(got[:-1]), got[-1], int(want[:-1]), want[-1]
    if gl == wl and (gn - wn) % 12 in (1, 11):
        return "neighbour"
    if gn == wn:
        return "relative"
    if gl == wl and (gn - wn) % 12 in (5, 7) or (gl != wl and (gn - wn) % 12 in (3, 9)):
        return "fifth/parallel"
    return "wrong"


def bpm_relation(got: float | None, want: float | None) -> str:
    if not got or not want:
        return "n/a"
    if abs(got - want) <= 0.5:
        return "exact"
    for f in (2.0, 0.5, 1.5, 2 / 3):
        if abs(got - want * f) <= 1.0:
            return "double/half" if f in (2.0, 0.5) else "3:2"
    return "wrong"


def tag_reference(path: Path) -> tuple[float | None, str | None]:
    from mutagen import File
    try:
        f = File(str(path))
    except Exception:
        return None, None
    if f is None or not f.tags:
        return None, None
    tags = f.tags
    bpm = key = None
    for k in ("TBPM", "bpm", "BPM", "tmpo"):
        if k in tags:
            v = tags[k]
            v = v.text[0] if hasattr(v, "text") else (v[0] if isinstance(v, list) else v)
            try:
                bpm = float(str(v).replace(",", "."))
            except ValueError:
                pass
            break
    for k in ("TKEY", "initialkey", "INITIALKEY", "key", "----:com.apple.iTunes:initialkey"):
        if k in tags:
            v = tags[k]
            v = v.text[0] if hasattr(v, "text") else (v[0] if isinstance(v, list) else v)
            key = to_camelot(v.decode() if isinstance(v, bytes) else str(v))
            break
    return bpm, key


def xml_reference(xml: Path) -> dict[str, tuple[float | None, str | None]]:
    out = {}
    for t in ET.parse(xml).getroot().iter("TRACK"):
        loc = t.get("Location")
        if not loc:
            continue
        name = Path(urllib.parse.unquote(urllib.parse.urlparse(loc).path)).name.lower()
        bpm = float(t.get("AverageBpm") or 0) or None
        out[name] = (bpm, to_camelot(t.get("Tonality")))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--xml", type=Path)
    a = ap.parse_args(argv)
    ref = xml_reference(a.xml) if a.xml else {}
    rows = []
    files = sorted(p for p in a.folder.rglob("*") if p.suffix.lower() in AUDIO)
    for i, p in enumerate(files, 1):
        want_bpm, want_key = ref.get(p.name.lower(), (None, None)) if ref else tag_reference(p)
        if not want_bpm and not want_key:
            continue
        m = analyze_music(p)
        rows.append({"file": p.name, "ref_bpm": want_bpm, "got_bpm": m.bpm, "bpm": bpm_relation(m.bpm, want_bpm),
                     "ref_key": want_key, "got_key": m.camelot, "key": key_relation(m.camelot, want_key),
                     "key_conf": m.key_confidence})
        print(f"[{i}/{len(files)}] {p.name[:60]:60s} bpm {m.bpm} vs {want_bpm}  key {m.camelot} vs {want_key}",
              file=sys.stderr)
    out = a.folder / "accuracy.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["file"]); w.writeheader(); w.writerows(rows)
    for field in ("bpm", "key"):
        got = [r[field] for r in rows if r[field] != "n/a"]
        if got:
            parts = {k: got.count(k) for k in dict.fromkeys(got)}
            print(f"{field.upper():4s} n={len(got)}  " + "  ".join(f"{k} {v} ({100 * v / len(got):.0f}%)" for k, v in parts.items()))
    print(f"details: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
