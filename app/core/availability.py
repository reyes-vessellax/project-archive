"""Plain-English availability and the search filters.

What the network actually tells us about a result: whether the sharer has a free upload slot, how many
requests are already waiting in their line, and their upload speed. It does NOT tell us how many people
they send to at once, how big the files ahead of ours are, or whether those people are still online.
So: the download time once it starts can be estimated (size / speed); a wait in someone's line can't,
and is shown only as a broad range. Never fake precision.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..adapters.base import Candidate

LOSSLESS = ("flac", "wav", "aiff", "aif")


@dataclass(frozen=True)
class Availability:
    word: str        # "Ready now", "Short wait", "Long wait", "Very long wait", "Busy", "Private"
    detail: str      # "~25 sec", "few min", "10+ min", "try later", "can't download"
    tone: str        # theme key: pass_ / warn / fail / faint
    rank: int        # 0 = best; used for sorting

    @property
    def label(self) -> str:
        return f"{self.word} · {self.detail}" if self.detail else self.word


def download_seconds(size: int | None, speed: int | None) -> float | None:
    """How long the transfer itself takes once it starts. The peer's reported speed is often optimistic,
    so pad it a little."""
    if not size or not speed or speed <= 0:
        return None
    return size / speed * 1.25 + 2


def say_duration(s: float) -> str:
    if s < 60:
        return f"~{max(5, int(round(s / 5.0)) * 5)} sec"
    m = s / 60
    return f"~{int(round(m))} min" if m < 10 else "10+ min"


def availability(c: Candidate) -> Availability:
    if c.locked:
        return Availability("Private", "can't download", "faint", 9)
    if c.free_slot:
        t = download_seconds(c.size, c.upload_speed)
        return Availability("Ready now", say_duration(t) if t else "", "pass_", 0)
    q = c.queue_length
    if q is None:
        return Availability("Unknown wait", "", "faint", 5)
    if q >= 999:
        return Availability("Busy", "try later", "faint", 8)
    if q <= 5:
        return Availability("Short wait", "few min", "warn", 1)
    if q <= 30:
        return Availability("Long wait", "10+ min", "warn", 2)
    return Availability("Very long wait", "could be hours", "fail", 3)


# ------------------------------------------------------------------------------------------- filters
@dataclass
class Filters:
    formats: list = field(default_factory=list)   # the file-type drop-down: [] = any, or one of "mp3", "flac", "wav", "aiff", "m4a"
    mp3_320: bool = False         # MP3s must claim 320 (the check confirms it later); other formats unaffected
    ready_now: bool = False       # only sharers with a free slot
    club_length: bool = False     # 4 minutes or longer, no radio/short edits
    show_private: bool = False
    lossless: bool = False        # FLAC / WAV / AIFF only
    mix: str = ""                 # older sessions only: the mix filter was removed (file names don't say it reliably)

    def wanted(self) -> set[str]:
        """The file types that may show: the drop-down's type, narrowed by Lossless (both = their overlap)."""
        f = {fmt_key(x) for x in self.formats}
        if self.lossless:
            f = (f & {"flac", "wav", "aiff"}) if f else {"flac", "wav", "aiff"}
            return f or {"none"}                            # e.g. MP3 + Lossless: nothing can match
        return f

    def any_format(self) -> bool:
        return not self.wanted()


FORMATS = (("mp3", "MP3"), ("flac", "FLAC"), ("wav", "WAV"), ("aiff", "AIFF"))


def fmt_key(ext: str) -> str:
    """File extension -> the format chip it belongs to."""
    e = (ext or "").lower().lstrip(".")
    return {"aif": "aiff", "aac": "m4a", "alac": "m4a", "mp4": "m4a"}.get(e, e)


MIX_WORDS = {
    "extended": ("extended", "club mix", "12\""),
    "original": ("original mix", "original"),
    "radio": ("radio edit", "radio mix", "radio"),
    "dub": ("dub",),
    "remix": ("remix", "rmx", "rework", "re-work"),
    "edit": ("edit", "re-edit", "reedit"),
}


def mix_kind_matches(c: Candidate, kind: str) -> bool:
    if not kind:
        return True
    text = f"{c.mix} {c.title}".lower()
    words = MIX_WORDS.get(kind, (kind,))
    if kind == "edit" and "radio edit" in text:
        return False
    if kind == "original" and not c.mix:
        return True                                    # no mix named = usually the original
    return any(w in text for w in words)


def passes(c: Candidate, f: Filters) -> bool:
    ext = fmt_key(c.extension)
    want = f.wanted()
    if want and ext not in want:
        return False
    if f.mp3_320 and ext == "mp3" and (c.bitrate_kbps or 0) < 320:
        return False
    if f.ready_now and not c.free_slot:
        return False
    if f.club_length:
        from .crates import club_length
        if not club_length(c):
            return False
    if c.locked and not f.show_private:
        return False
    return True


def apply(cands: list[Candidate], f: Filters) -> tuple[list[Candidate], int, int]:
    """(kept, hidden_by_filters, private_hidden)."""
    kept, hidden, private = [], 0, 0
    for c in cands:
        if passes(c, f):
            kept.append(c)
        elif c.locked and not f.show_private:
            private += 1
        else:
            hidden += 1
    return kept, hidden, private
