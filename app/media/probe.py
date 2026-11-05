"""Read what a file really is, from its contents (never from its name)."""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from pathlib import Path

from .tools import find_tool, run

# Container names FFprobe reports -> our short names
CONTAINERS = {"mp3": "mp3", "wav": "wav", "flac": "flac", "aiff": "aiff"}
LOSSLESS_CODECS = ("pcm_", "flac")


@dataclass
class MediaFacts:
    readable: bool = False
    error: str = ""
    container: str | None = None          # mp3 / wav / flac / aiff / other name
    codec: str | None = None              # e.g. mp3, pcm_s16le, flac
    duration_s: float | None = None       # what the file claims
    bitrate_bps: int | None = None
    bitrate_mode: str = "unknown"         # CBR / VBR / unknown / lossless
    sample_rate_hz: int | None = None
    channels: int | None = None
    bit_depth: int | None = None
    encoder: str | None = None
    tags: dict = field(default_factory=dict)

    @property
    def lossless(self) -> bool:
        return bool(self.codec) and self.codec.startswith(LOSSLESS_CODECS)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["lossless"] = self.lossless
        return d


def sniff_magic(path: Path) -> str | None:
    """Identify the container from the first bytes, independent of FFprobe."""
    with open(path, "rb") as f:
        head = f.read(12)
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:4] == b"fLaC":
        return "flac"
    if head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"):
        return "aiff"
    if head[:3] == b"ID3" or (len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return "mp3"
    return None


def mp3_vbr_mode(path: Path) -> str:
    """LAME/Xing header: 'Xing' or 'VBRI' = VBR, 'Info' = CBR. Looks in the first frames only."""
    with open(path, "rb") as f:
        head = f.read(256 * 1024)
    start = 0
    if head[:3] == b"ID3" and len(head) >= 10:
        size = (head[6] << 21) | (head[7] << 14) | (head[8] << 7) | head[9]
        start = 10 + size
    window = head[start:start + 4096]
    if b"Xing" in window or b"VBRI" in window:
        return "VBR"
    if b"Info" in window:
        return "CBR"
    return "unknown"


def wav_claimed_duration(path: Path) -> float | None:
    """Duration the WAV header promises (data chunk size / byte rate). A cut-off WAV promises more than it has."""
    try:
        with open(path, "rb") as f:
            if f.read(12)[8:12] != b"WAVE":
                return None
            byte_rate = None
            for _ in range(64):
                hdr = f.read(8)
                if len(hdr) < 8:
                    return None
                cid, size = hdr[:4], struct.unpack("<I", hdr[4:])[0]
                if cid == b"fmt ":
                    fmt = f.read(size)
                    byte_rate = struct.unpack("<I", fmt[8:12])[0]
                    if size % 2:
                        f.read(1)
                elif cid == b"data":
                    if not byte_rate or size in (0, 0xFFFFFFFF):
                        return None
                    return size / byte_rate
                else:
                    f.seek(size + (size % 2), 1)
    except (OSError, struct.error):
        return None
    return None


def probe(path: Path, ffprobe_override: str = "", timeout: float = 30) -> MediaFacts:
    facts = MediaFacts()
    exe = find_tool("ffprobe", ffprobe_override)
    proc = run([exe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)], timeout)
    try:
        data = json.loads(proc.stdout.decode("utf-8", "replace") or "{}")
    except json.JSONDecodeError:
        data = {}
    streams = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    if proc.returncode != 0 or not streams:
        lines = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        facts.error = lines[-1] if lines else "No audio stream found"
        return facts

    st, fmt = streams[0], data.get("format", {})
    facts.readable = True
    names = (fmt.get("format_name") or "").split(",")
    facts.container = next((CONTAINERS[n] for n in names if n in CONTAINERS), names[0] or None)
    facts.codec = st.get("codec_name")
    facts.sample_rate_hz = _int(st.get("sample_rate"))
    facts.channels = _int(st.get("channels"))
    facts.duration_s = _float(fmt.get("duration")) or _float(st.get("duration"))
    facts.bitrate_bps = _int(st.get("bit_rate")) or _int(fmt.get("bit_rate"))
    depth = _int(st.get("bits_per_raw_sample")) or _int(st.get("bits_per_sample"))
    facts.bit_depth = depth if depth else None
    tags = {k.lower(): v for k, v in {**fmt.get("tags", {}), **st.get("tags", {})}.items()}
    facts.tags = {k: tags[k] for k in ("artist", "title", "album", "date") if k in tags}
    facts.encoder = tags.get("encoder") or st.get("codec_long_name")

    if facts.lossless:
        facts.bitrate_mode = "lossless"
    elif facts.codec == "mp3":
        facts.bitrate_mode = mp3_vbr_mode(path)
    if facts.container == "wav":
        claimed = wav_claimed_duration(path)
        if claimed:
            facts.duration_s = max(facts.duration_s or 0, claimed)
    return facts


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
