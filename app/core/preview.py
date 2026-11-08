"""Pieces of the search preview that don't need the engine: read a file's header, and turn a chunk of bytes from
the middle of a track into something FFmpeg can decode.

Why this works: the engine resumes a partial download from wherever the partial file ends. So the preview
fetches the first few KB (the header), stops, pads the partial file out to the middle of the track, and asks
again. The sharer then sends from the middle, and ~20 seconds of audio costs ~20 seconds' worth of bytes,
not a third of the file.

  MP3   any run of frames decodes on its own; the chunk alone is enough.
  FLAC  frames carry a sync code; "fLaC" + the 34-byte STREAMINFO block in front of the chunk is enough.
  WAV / AIFF  plain samples; the header says the sample format, so the chunk is decoded as raw PCM.
Anything else (M4A, OGG, ...) is fetched from the start, the slow way.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

MIDDLE = {"mp3", "flac", "wav", "aif", "aiff"}
HEAD_BYTES = {"mp3": 1, "flac": 42, "wav": 8192, "aif": 8192, "aiff": 8192}   # what to wait for before stopping


@dataclass
class Pcm:
    fmt: str            # FFmpeg raw format name, e.g. s16le
    channels: int
    rate: int
    align: int          # bytes per sample frame (all channels)
    data_start: int
    data_len: int


def flac_header(head: bytes) -> bytes | None:
    """'fLaC' + STREAMINFO marked as the last metadata block, with the total length and MD5 blanked
    (the chunk is only a slice, so both would be wrong). None if this isn't a FLAC header."""
    if len(head) < 42 or head[:4] != b"fLaC" or (head[4] & 0x7F) != 0 or int.from_bytes(head[5:8], "big") != 34:
        return None
    si = bytearray(head[8:42])
    si[13] &= 0xF0                      # high 4 bits of the 36-bit sample count
    si[14:18] = b"\0\0\0\0"
    si[18:34] = b"\0" * 16              # MD5
    return b"fLaC" + bytes([0x80, 0, 0, 34]) + bytes(si)


def wav_info(head: bytes) -> Pcm | None:
    if len(head) < 12 or head[:4] not in (b"RIFF", b"RF64") or head[8:12] != b"WAVE":
        return None
    pos, fmt = 12, None
    while pos + 8 <= len(head):
        cid, size = head[pos:pos + 4], struct.unpack("<I", head[pos + 4:pos + 8])[0]
        body = pos + 8
        if cid == b"fmt " and body + 16 <= len(head):
            tag, ch, rate, _, align, bits = struct.unpack("<HHIIHH", head[body:body + 16])
            if tag == 0xFFFE and body + 26 <= len(head):          # WAVE_FORMAT_EXTENSIBLE: real tag in the GUID
                tag = struct.unpack("<H", head[body + 24:body + 26])[0]
            fmt = (tag, ch, rate, align, bits)
        elif cid == b"data":
            if fmt is None:
                return None
            tag, ch, rate, align, bits = fmt
            name = {(1, 8): "u8", (1, 16): "s16le", (1, 24): "s24le", (1, 32): "s32le",
                    (3, 32): "f32le", (3, 64): "f64le"}.get((tag, bits))
            if not name or not ch or not rate or not align:
                return None
            return Pcm(name, ch, rate, align, body, size if size not in (0, 0xFFFFFFFF) else 1 << 62)
        pos = body + size + (size & 1)
    return None


def _ext80(b: bytes) -> int:
    exp = ((b[0] & 0x7F) << 8) | b[1]
    mant = int.from_bytes(b[2:10], "big")
    return int(round(mant * 2.0 ** (exp - 16383 - 63))) if mant else 0


def aiff_info(head: bytes) -> Pcm | None:
    if len(head) < 12 or head[:4] != b"FORM" or head[8:12] not in (b"AIFF", b"AIFC"):
        return None
    aifc = head[8:12] == b"AIFC"
    pos, comm = 12, None
    while pos + 8 <= len(head):
        cid, size = head[pos:pos + 4], struct.unpack(">I", head[pos + 4:pos + 8])[0]
        body = pos + 8
        if cid == b"COMM" and body + 18 <= len(head):
            ch, _, bits = struct.unpack(">HIH", head[body:body + 8])
            rate = _ext80(head[body + 8:body + 18])
            comp = head[body + 18:body + 22] if aifc and body + 22 <= len(head) else b"NONE"
            comm = (ch, bits, rate, comp)
        elif cid == b"SSND" and body + 8 <= len(head):
            if comm is None:
                return None
            ch, bits, rate, comp = comm
            offset = struct.unpack(">I", head[body:body + 4])[0]
            if comp in (b"NONE", b"twos"):
                name = {8: "s8", 16: "s16be", 24: "s24be", 32: "s32be"}.get(bits)
            elif comp == b"sowt":
                name = {16: "s16le", 24: "s24le", 32: "s32le"}.get(bits)
            elif comp in (b"fl32", b"FL32"):
                name = "f32be"
            else:
                name = None
            if not name or not ch or not rate:
                return None
            start = body + 8 + offset
            return Pcm(name, ch, rate, ch * ((bits + 7) // 8), start, max(0, size - 8 - offset))
        pos = body + size + (size & 1)
    return None


def pcm_info(ext: str, head: bytes) -> Pcm | None:
    return wav_info(head) if ext == "wav" else aiff_info(head) if ext in ("aif", "aiff") else None


def plan_offset(ext: str, head: bytes, size: int, length_s: float, start_s: float, seconds: float):
    """Where to start fetching and how many bytes, for a clip at start_s. Returns (offset, nbytes, extra) or
    None when the header can't be read (then the slow way is used). `extra` is what decoding needs:
    the FLAC header bytes or the Pcm description."""
    length_s = max(length_s, seconds + 1)
    if ext == "mp3":
        rate = size / length_s
        return int(start_s * rate), int((seconds + 1.5) * rate) + 4096, None
    if ext == "flac":
        hdr = flac_header(head)
        if hdr is None:
            return None
        rate = size / length_s
        return max(len(head), int(start_s * rate)), int((seconds + 1.5) * rate) + 65536, hdr
    pcm = pcm_info(ext, head)
    if pcm is None:
        return None
    frames = int(start_s * pcm.rate)
    offset = pcm.data_start + frames * pcm.align
    nbytes = int(seconds * pcm.rate) * pcm.align
    end = min(size, pcm.data_start + pcm.data_len)
    if offset + nbytes > end:                               # short file: back up so the clip fits
        offset = max(pcm.data_start, pcm.data_start + ((end - nbytes - pcm.data_start) // pcm.align) * pcm.align)
    return offset, nbytes, pcm


def decode_args(ext: str, extra, chunk_path: str) -> list[str]:
    """FFmpeg input arguments for a chunk written by `chunk_bytes`."""
    if ext == "mp3":
        return ["-f", "mp3", "-i", chunk_path]
    if ext == "flac":
        return ["-f", "flac", "-i", chunk_path]
    pcm: Pcm = extra
    return ["-f", pcm.fmt, "-ar", str(pcm.rate), "-ac", str(pcm.channels), "-i", chunk_path]


def chunk_bytes(ext: str, extra, data: bytes) -> bytes:
    if ext == "flac":
        return extra + data
    if ext in ("wav", "aif", "aiff"):
        pcm: Pcm = extra
        return data[: len(data) - len(data) % pcm.align]
    return data
