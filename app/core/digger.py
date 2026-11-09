"""Discover's shelf: tracks dug ahead, downloaded into quarantine and fully checked, so every one is ready to take.

Only a track that passes BOTH checks goes on the shelf:
- the quality verdict is Good (it's what it claims: real bitrate, plays through, no fake 320)
- it's club-ready (decks load it, mono-safe; clipping/loudness/low end at most notes)
Anything else is deleted from quarantine automatically. The user never sees it.

Polite and bounded: one record at a time is looked for (searches come from the shared budget), at most
MAX_INFLIGHT downloads at once, and the shelf holds about TARGET tracks. Tracks left on the shelf expire with the
normal quarantine retention and are replaced. Nothing reaches the library until the user adds it.
"""
from __future__ import annotations

import json

from . import jobs as J

TARGET = 12
MAX_INFLIGHT = 2
ACTIVE = (J.QUEUED, J.STAGING, J.ANALYZING)


def _discover_jobs(svc) -> list[dict]:
    return [j for j in svc.db.jobs(include_hidden=True, limit=20_000) if j.get("origin") == "discover"]


def info_of(job: dict) -> dict:
    try:
        return json.loads(job.get("discover_json") or "{}")
    except ValueError:
        return {}


def passes(a: dict | None) -> bool:
    return bool(a) and a.get("overall_status") == "PASS" and bool((a.get("club") or {}).get("ready"))


def shelf(svc, era: str = "") -> list[tuple[dict, dict, dict]]:
    """(job, analysis, info) for every track ready to take, newest first; optionally one era's."""
    out = []
    for j in _discover_jobs(svc):
        if j["state"] != J.READY:
            continue
        a = svc.db.analysis(j["id"])
        info = info_of(j)
        if passes(a) and (not era or info.get("era") == era):
            out.append((j, a, info))
    return out


def in_flight(svc) -> list[dict]:
    return [j for j in _discover_jobs(svc) if j["state"] in ACTIVE]


def tidy(svc) -> int:
    """Delete dug tracks that didn't make it (not Good, or not club-ready). Returns how many."""
    n = 0
    for j in _discover_jobs(svc):
        if j["state"] == J.READY and not passes(svc.db.analysis(j["id"])):
            try:
                svc.reject(j["id"]); n += 1
            except Exception:
                pass
    return n


def seen_releases(svc) -> set[int]:
    return {info_of(j).get("release_id") for j in _discover_jobs(svc)} - {None}


def fill(svc, engine, labels: list[str], era: str = "", cancelled=lambda: False, log=None) -> int:
    """Dig one more track if the shelf needs it. Returns 1 when a download was started, else 0."""
    from .discover_avail import spin_found
    tidy(svc)
    flying = in_flight(svc)
    if len(flying) >= MAX_INFLIGHT or len(shelf(svc)) + len(flying) >= TARGET:
        return 0
    seen = seen_releases(svc)
    for _ in range(3):
        if cancelled():
            return 0
        f = spin_found(engine, svc, labels, cancelled=cancelled, log=log, max_records=4)
        if f is None:
            return 0
        if f.release.id in seen:
            continue
        r = f.release
        info = {"release_id": r.id, "title": r.title, "artist": r.artist, "year": r.year, "catno": r.catno,
                "label": f.label, "track": f.track, "thumb": r.thumb, "cover": f.details.get("cover", ""),
                "styles": f.details.get("styles") or [], "era": era}
        svc.request_download(f.best, origin="discover", info=info)
        return 1
    return 0


def take(svc, job_id: str):
    """Add a shelf track to the library (it already passed both checks): instant, nothing to wait for."""
    target = svc.promote(job_id)
    svc.db.update_job(job_id, hidden=0)
    return target
