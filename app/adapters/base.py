"""Connector contract (spec section 7.4).

The rest of the app never knows which network a candidate came from. A source adapter searches,
hands back normalized Candidate objects, downloads one on request into a folder it owns, and
reports progress. The analysis engine only ever sees a local file.

No adapter in this package speaks the Soulseek protocol itself. The first real adapter drives an
existing, separately installed client (slskd) through its local API; that client owns the login.
"""
from __future__ import annotations

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

    @property
    def key(self) -> str:
        return f"{self.user}\n{self.remote_path}"


@dataclass
class SearchResult:
    query: str
    search_id: str
    finished: bool
    candidates: list[Candidate] = field(default_factory=list)


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

    def request_download(self, candidate: Candidate) -> Transfer:
        """Ask the client to download the file into the client's own downloads folder."""
        raise NotImplementedError

    def transfer_status(self, transfer: Transfer) -> Transfer:
        raise NotImplementedError

    def cancel(self, transfer: Transfer) -> bool:
        raise NotImplementedError
