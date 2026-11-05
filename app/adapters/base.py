"""Connector contract (spec section 7.4).

The rest of the app never knows which network a candidate came from. A source adapter searches,
hands back normalized Candidate objects, downloads one on request into a folder it owns, and
reports progress. The analysis engine only ever sees a local file.

No adapter in this package speaks the Soulseek protocol itself. The first real adapter drives an
existing, separately installed client (slskd) through its local API; that client owns the login.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


class ConnectorError(RuntimeError):
    """The client could not be reached or refused the request. The message is shown to the user."""


@dataclass
class ConnectorStatus:
    available: bool                 # the local client answered at all
    logged_in: bool = False         # ...and it is connected to the network
    username: str = ""              # account the client is logged in as
    message: str = ""               # plain-English state, e.g. "Client not running"


@dataclass
class Candidate:
    """One file offered by one peer. Everything here is untrusted remote metadata."""
    source_kind: str                # "soulseek"
    user: str                       # peer that offers the file
    remote_path: str                # full path on the peer's machine, as the peer reports it
    size: int                       # bytes, as reported
    display_name: str = ""          # last path component, for the UI
    folder: str = ""                # remote parent folder name, for the UI
    artist: str = ""                # from "Artist - Title.ext" naming; empty when the name doesn't follow it
    title: str = ""                 # the title part without the mix, or the whole file name without extension
    mix: str = ""                   # "Extended Mix", "Dom Dolla Remix"… from trailing (…) / […]; empty if none
    extension: str = ""
    bitrate_kbps: int | None = None # what the peer's client claims; verified later by our analysis
    vbr: bool | None = None
    length_s: int | None = None
    sample_rate_hz: int | None = None
    bit_depth: int | None = None
    free_slot: bool | None = None   # peer has a free upload slot right now
    queue_length: int | None = None # files already waiting on that peer
    upload_speed: int | None = None # bytes/s the peer reported
    locked: bool = False            # peer restricts this file; can't be requested
    note: str = ""                  # why it can't be picked here, e.g. "Extension mismatch" (shown greyed, not hidden)

    @property
    def key(self) -> str:
        return f"{self.user}\n{self.remote_path}"


@dataclass
class SearchResult:
    query: str
    search_id: str
    finished: bool
    candidates: list[Candidate] = field(default_factory=list)
    state: str = ""                 # the client's own state string, e.g. "Completed, TimedOut"
    error: str = ""                 # plain-English reason when the search ended badly, else ""
    sent: str = ""                  # what actually went to the network (differs from query on a fallback)
    dropped: str = ""               # the word left out on a fallback search, "" otherwise


@dataclass
class Transfer:
    """Progress of one requested download inside the client."""
    transfer_id: str
    user: str
    remote_path: str
    size: int
    state: str                      # client's own state string, shown to the user
    percent: float = 0.0
    bytes_done: int = 0
    done: bool = False              # finished successfully
    failed: bool = False            # finished unsuccessfully (cancelled, errored, rejected...)
    local_path: Path | None = None  # set once the completed file has been located on disk


class SourceAdapter:
    """Interface every source adapter implements."""

    source_kind = "unknown"

    def health_check(self) -> ConnectorStatus:
        raise NotImplementedError

    def search(self, query: str, timeout_s: float = 15.0) -> SearchResult:
        """Start a search and return it (possibly still running)."""
        raise NotImplementedError

    def search_results(self, search_id: str) -> SearchResult:
        """Latest results for a search started earlier."""
        raise NotImplementedError

    def forget_search(self, search_id: str) -> None:
        """Drop a finished search from the engine."""

    def search_status(self, search_id: str) -> tuple[bool, int, int, str]:
        """(finished, responses_so_far, files_so_far, error) without fetching the results themselves."""
        r = self.search_results(search_id)
        return r.finished, len({c.user for c in r.candidates}), len(r.candidates), r.error

    def request_download(self, candidate: Candidate) -> Transfer:
        """Ask the client to download the file into the client's own downloads folder."""
        raise NotImplementedError

    def transfer_status(self, transfer: Transfer) -> Transfer:
        raise NotImplementedError

    def cancel(self, transfer: Transfer) -> bool:
        raise NotImplementedError

    def forget(self, transfer: Transfer) -> None:
        """Drop a finished transfer from the client's list so it stops tracking it."""

    def housekeeping(self) -> None:
        """Clear completed transfers and old searches the client still holds."""


_TRACK_NO = re.compile(r"^\s*(?:[A-Da-d]?\d{1,3})(?:[\s.\-_)]+)")
_DASHES = re.compile(r"\s*[\u2013\u2014\u2012-]\s*")           # -, –, —, ‒ with any spacing
_FEAT = re.compile(r"^(feat|ft|featuring|with)\b", re.I)
_TRAIL = re.compile(r"\s*[\(\[]([^()\[\]]*)[\)\]]\s*$")


def split_artist_title(filename: str) -> tuple[str, str]:
    """"Artist - Title (Mix).mp3" -> ("Artist", "Title (Mix)"). Handles underscores, en/em dashes and
    leading track numbers. Anything else -> ("", name without extension)."""
    return parse_track(filename)[:2]


def parse_track(filename: str) -> tuple[str, str, str]:
    """(artist, title, mix). `mix` is the trailing "(Extended Mix)" / "[Remix]" part, "" if none, and the
    title is returned WITHOUT it; "(feat. X)" stays in the title."""
    from ..core.safety import clean_text
    stem = Path(clean_text(filename)).stem
    stem = stem.replace("_", " ")
    stem = re.sub(r"\s+", " ", stem).strip()
    # split only on a dash that has space on both sides (so "Hip-Hop" and "Re-Edit" survive)
    parts = [p.strip() for p in re.split(r"\s+[\u2013\u2014\u2012-]\s+", stem) if p.strip()]
    if len(parts) >= 2 and re.fullmatch(r"[A-Da-d]?\d{1,3}\.?", parts[0]):
        parts = parts[1:]                                   # "01 - …" / "A1 - …": a track number on its own
    elif parts:
        parts[0] = _TRACK_NO.sub("", parts[0], count=1) or parts[0]
    if len(parts) >= 2:
        artist, title = parts[0], " - ".join(parts[1:])     # Soulseek convention; "Title - Artist" is rare
    elif parts:
        artist, title = "", parts[0]
    else:
        artist, title = "", stem
    mix = ""
    m = _TRAIL.search(title)
    while m and not _FEAT.match(m.group(1).strip()):
        mix = (m.group(1).strip() + (" " + mix if mix else "")).strip()
        title = title[:m.start()].rstrip()
        m = _TRAIL.search(title)
    return artist, title.strip(), mix
