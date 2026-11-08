"""Transparent PASS / WARN / FAIL checks. Every result says why, in plain English.

Honesty rule from the spec: these are evidence and risk signals. Nothing here may claim a file is
"authentic 320" or "verified lossless".
"""
from __future__ import annotations

from dataclasses import dataclass

from ..config import Settings
from ..media.probe import MediaFacts

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
ORDER = {PASS: 0, WARN: 1, FAIL: 2}

# Which detected containers are acceptable for each file extension
EXT_MATCH = {"mp3": {"mp3"}, "wav": {"wav"}, "flac": {"flac"}, "aiff": {"aiff"}, "aif": {"aiff"}}
SUPPORTED_CODECS = ("mp3", "pcm_", "flac")


@dataclass
class Check:
    id: str
    status: str
    title: str
    message: str

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def overall(checks: list[Check]) -> str:
    return max((c.status for c in checks), key=ORDER.get, default=PASS)


# Things that are plainly not audio, by their first bytes. Any of these is a hard stop before decoding.
NOT_AUDIO = (
    (b"MZ", "a Windows program (.exe/.dll)"),
    (b"PK\x03\x04", "a zip archive"),
    (b"Rar!", "a RAR archive"),
    (b"7z\xbc\xaf", "a 7-Zip archive"),
    (b"%PDF", "a PDF"),
    (b"\x7fELF", "a Linux program"),
    (b"<!DOCTYPE", "a web page"),
    (b"<html", "a web page"),
    (b"\x89PNG", "a PNG image"),
    (b"\xff\xd8\xff", "a JPEG image"),
    (b"GIF8", "a GIF image"),
)


def prechecks(path, ext: str, facts: MediaFacts, magic: str | None, settings: Settings) -> list[Check]:
    """Quick, silent checks before the expensive decode. Any FAIL here ends the analysis early with the
    reason; the full decode is only spent on files that could plausibly be music."""
    checks: list[Check] = []
    ext = ext.lower().lstrip(".")
    try:
        with open(path, "rb") as f:
            head = f.read(16)
        size = path.stat().st_size
    except OSError as e:
        return [Check("precheck", FAIL, "Can't read the file", str(e))]
    for sig, what in NOT_AUDIO:
        if head.startswith(sig):
            return [Check("precheck", FAIL, "Not an audio file", f"The file is {what} with a .{ext} name.")]
    if size < 64 * 1024:
        return [Check("precheck", FAIL, "Too small to be a track", f"{size // 1024} KB — a few seconds at most.")]
    if facts.readable and facts.duration_s and facts.duration_s > 5:
        implied_kbps = size * 8 / facts.duration_s / 1000
        lossy = ext in ("mp3", "aac", "m4a", "ogg", "opus")
        if lossy and implied_kbps < 24:
            checks.append(Check("precheck", FAIL, "Size doesn't match the length",
                                f"{size / 1e6:.1f} MB for {facts.duration_s / 60:.1f} min is about {implied_kbps:.0f} kbps — "
                                "far too little data for a real track; the file is probably cut short or mislabelled."))
        if lossy and implied_kbps > 2000:
            checks.append(Check("precheck", WARN, "Size doesn't match the length",
                                f"{size / 1e6:.1f} MB for {facts.duration_s / 60:.1f} min is far more data than a .{ext} "
                                "would hold; the file may carry something else inside."))
    return checks


def evaluate(ext: str, facts: MediaFacts, decode: dict | None, cutoff_hz: float | None,
             settings: Settings) -> list[Check]:
    checks: list[Check] = []
    ext = ext.lower().lstrip(".")

    # 1. Actual format ------------------------------------------------------------
    if not facts.readable:
        checks.append(Check("format", FAIL, "Actual format",
                            f"Not readable as audio ({facts.error or 'unknown error'})."))
        return checks
    if not (facts.codec or "").startswith(SUPPORTED_CODECS):
        checks.append(Check("format", FAIL, "Actual format",
                            f"Contains {facts.codec or 'an unknown codec'}, which isn't supported."))
        return checks
    expected = EXT_MATCH.get(ext, set())
    inner = f"{(facts.container or '?').upper()} ({facts.codec})"
    if facts.container not in expected:
        checks.append(Check("format", WARN, "Actual format",
                            f"Named .{ext} but the file is really {inner}. The extension is misleading."))
    elif facts.container == "wav" and facts.codec == "mp3":
        checks.append(Check("format", WARN, "Actual format", "WAV file that actually contains MP3 audio."))
    else:
        checks.append(Check("format", PASS, "Actual format", f"{inner}, matches the .{ext} extension."))

    # 2. Bitrate -------------------------------------------------------------------
    kbps = round(facts.bitrate_bps / 1000) if facts.bitrate_bps else None
    if facts.codec == "mp3":
        if kbps is None:
            checks.append(Check("bitrate", WARN, "Bitrate", "MP3 bitrate isn't reported by the file."))
        elif facts.bitrate_mode == "VBR":
            lim = settings.vbr_min_avg_kbps
            st = WARN if kbps < lim else PASS
            checks.append(Check("bitrate", st, "Bitrate",
                                f"VBR MP3 averaging {kbps} kbps (warning level {lim} kbps average). VBR has no "
                                f"single fixed bitrate."))
        else:
            lim = settings.mp3_min_kbps
            mode = "CBR" if facts.bitrate_mode == "CBR" else "MP3 (mode not stated)"
            if kbps < lim:
                checks.append(Check("bitrate", WARN, "Bitrate",
                                    f"{mode} reports {kbps} kbps; your threshold is {lim} kbps."))
            else:
                checks.append(Check("bitrate", PASS, "Bitrate",
                                    f"{mode} at {kbps} kbps, at your {lim} kbps target. (This describes the file "
                                    f"as encoded, not its original source.)"))
    else:
        depth = f"{facts.bit_depth}-bit, " if facts.bit_depth else ""
        sr = f"{facts.sample_rate_hz / 1000:g} kHz" if facts.sample_rate_hz else "unknown rate"
        checks.append(Check("bitrate", PASS, "Bitrate",
                            f"Uncompressed/lossless ({depth}{sr}). Note: this doesn't prove the source was lossless."))

    # 3. Decode integrity ----------------------------------------------------------
    if decode is not None:
        claimed = facts.duration_s or 0
        got = decode["decoded_s"]
        if decode["timed_out"]:
            checks.append(Check("decode", FAIL, "Plays all the way through", "Decoding took too long and was stopped."))
        elif got < 0.5:
            checks.append(Check("decode", FAIL, "Plays all the way through", "No audio could be decoded."))
        elif claimed and got < claimed - max(2.0, claimed * 0.01):
            checks.append(Check("decode", FAIL, "Plays all the way through",
                                f"File claims {fmt_time(claimed)} but only {fmt_time(got)} of audio decodes. "
                                f"It's cut off or corrupted."))
        elif not decode["ok_exit"]:
            checks.append(Check("decode", FAIL, "Plays all the way through",
                                f"Decoder stopped with an error: {first(decode['error_lines'])}"))
        elif decode["error_count"]:
            checks.append(Check("decode", WARN, "Plays all the way through",
                                f"Plays through, but the decoder reported {decode['error_count']} problem(s), "
                                f"e.g. \"{first(decode['error_lines'])}\". Listen for glitches."))
        else:
            checks.append(Check("decode", PASS, "Plays all the way through",
                                f"Full {fmt_time(got)} decoded with no errors."))
        if decode.get("peak", 1) < 1e-5 and got >= 0.5:
            checks.append(Check("silence", WARN, "Silence", "The whole file is silent."))

    # 4. Spectral cutoff (heuristic, WARN only) -----------------------------------------
    if cutoff_hz is not None and facts.sample_rate_hz:
        nyq = facts.sample_rate_hz / 2
        khz = cutoff_hz / 1000
        high_claim = facts.lossless or (facts.codec == "mp3" and (kbps or 0) >= 256)
        if high_claim and cutoff_hz < min(19000, nyq * 0.86):
            what = "a lossless file" if facts.lossless else f"a {kbps} kbps MP3"
            checks.append(Check("spectrum", WARN, "Frequency cutoff",
                                f"Energy stops near {khz:.1f} kHz, low for {what}. This is a common sign of a file "
                                f"made from a lower-quality MP3, but mastering or the original recording can cause "
                                f"it too. Check the spectrogram and use your ears."))
        else:
            checks.append(Check("spectrum", PASS, "Frequency cutoff",
                                f"Energy reaches about {khz:.1f} kHz. Nothing suspicious found (a heuristic, not proof)."))

    # 5. Duration / channels ----------------------------------------------------------
    dur = (decode or {}).get("decoded_s") or facts.duration_s or 0
    if 0.5 <= dur < 30:
        checks.append(Check("duration", WARN, "Length", f"Only {fmt_time(dur)} long. Is this a full track?"))
    if facts.channels == 1:
        checks.append(Check("channels", WARN, "Channels", "Mono file. Most club tracks are stereo."))
    return checks


def fmt_time(s: float) -> str:
    s = int(round(s))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def first(lines: list[str]) -> str:
    return lines[0] if lines else "unknown error"
