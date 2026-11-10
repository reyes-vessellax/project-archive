"""Upgrade finder: weak copies in the library, and a better copy someone is sharing right now.

Weak = an MP3 under 320 kbps (or VBR averaging under 256), a verdict other than Good, or not club-ready.
Better = the same track (Batch's matching: artist and title within a typo, the mix respected), lossless or MP3 at
the user's minimum, ready to send now, and a real step up from what's there (lossless beats MP3; 320 beats 192).
Searches come from the shared budget, one at a time; results are remembered for UPGRADE_HOURS.

"Get it" downloads the better copy into quarantine as a new job marked as the upgrade of the old one. It's checked
like anything else; when it's saved to the library it takes the old one's place: same crates, old file to the Trash.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..adapters.base import Candidate, parse_track
from . import batch as B
from . import jobs as J
from .discover_avail import deck_loadable
from .searching import collect

UPGRADE_HOURS = 12
LOSSLESS = {"flac", "wav", "aiff", "aif"}


@dataclass
class Weak:
    job_id: str
    artist: str
    title: str
    mix: str
    have: str                 # "MP3 192", "FLAC"
    why: str                  # the plain reason it's weak
    rank: int                 # how good what we have is (0 = poor): a better copy must beat it
    best: Candidate | None = None
    alts: list = field(default_factory=list)


def _rank_file(ext: str, kbps: int | None) -> int:
    ext = (ext or "").lower()
    if ext in LOSSLESS:
        return 3
    if ext == "mp3":
        return 2 if (kbps or 0) >= 320 else 1 if (kbps or 0) >= 256 else 0
    return 0


def weak_tracks(svc) -> list[Weak]:
    out = []
    for job in svc.db.jobs(states=(J.PROMOTED,), limit=100_000):
        a = svc.db.analysis(job["id"]) or {}
        f, me = a.get("facts") or {}, a.get("meta") or {}
        if not job.get("final_path") or not Path(job["final_path"]).is_file():
            continue
        ext = (f.get("container") or Path(job["final_path"]).suffix.lstrip(".")).lower()
        kbps = round(f["bitrate_bps"] / 1000) if f.get("bitrate_bps") else None
        rank = _rank_file(ext, kbps)
        reasons = []
        if ext == "mp3" and kbps and (kbps < 320 if f.get("bitrate_mode") != "VBR" else kbps < 256):
            reasons.append(f"only {kbps} kbps")
        if a.get("overall_status") == "FAIL":
            reasons.append("the check said Broken"); rank = 0
        elif a.get("overall_status") == "WARN":
            reasons.append("the check said Have a look"); rank = min(rank, 1)
        club = a.get("club") or {}
        if club and not club.get("error") and not club.get("ready"):
            reasons.append("not club-ready")
        if not reasons:
            continue
        pa, pt, pm = parse_track(job.get("original_name") or "")
        have = ext.upper() + (f" {kbps}" if ext == "mp3" and kbps else "")
        out.append(Weak(job["id"], me.get("artist") or pa, me.get("title") or pt, me.get("mix") or pm, have,
                        ", ".join(reasons), rank))
    return out


def better_copies(cands: list[Candidate], w: Weak, min_kbps: int) -> list[Candidate]:
    wanted = B.Wanted(w.artist, w.title, w.mix)
    out = []
    for c in B.ranked(cands, wanted, min_kbps):
        if not (deck_loadable(c) and c.free_slot and not (c.queue_length or 0)):
            continue
        if _rank_file(c.extension, c.bitrate_kbps) > w.rank:
            out.append(c)
    out.sort(key=lambda c: -_rank_file(c.extension, c.bitrate_kbps))
    return out[:6]


def find(svc, w: Weak, cancelled=lambda: False, log=None) -> Weak:
    """Fill w.best/w.alts from memory or ONE network search."""
    key = f"upgrade:{w.job_id}"
    hit = svc.db.cache_get(key)
    if hit:
        data, at = hit
        try:
            if datetime.fromisoformat(at) > datetime.now(timezone.utc) - timedelta(hours=UPGRADE_HOURS):
                w.alts = [Candidate(**c) for c in data.get("alts") or []]
                w.best = w.alts[0] if w.alts else None
                return w
        except ValueError:
            pass
    if getattr(svc, "adapter", None) is None or not w.artist or not w.title:
        return w
    res = collect(svc, B.Wanted(w.artist, w.title, w.mix).query, 12.0, budget=getattr(svc, "search_budget", None),
                  cancelled=cancelled, log=log, check_login=False)
    if res is None:
        return w
    try:
        svc.forget_search(res.search_id)
    except Exception:
        pass
    min_kbps = getattr(svc.settings, "mp3_min_kbps", 320) or 320
    w.alts = better_copies(res.candidates, w, min_kbps)
    w.best = w.alts[0] if w.alts else None
    svc.db.cache_put(key, {"alts": [asdict(c) for c in w.alts]})
    return w
