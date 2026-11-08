"""Wishlist: standing searches that run on a slow cadence and land a match in quarantine.

Roadmap item 2. The rules that keep it inside the product's non-negotiables:
- it uses the SAME search budget as the user's own searches (one bucket, `svc.search_budget`), runs
  one wish at a time, never while the user is searching, and never more often than every
  WISH_EVERY_S (jittered) per wish — the network punishes chatty clients;
- it never decides anything: a match goes to quarantine and is checked like any other file, and only a
  Good / Have-a-look result is announced (the bell). Broken means try the next candidate, up to
  WISH_MAX_TRIES per search, then wait for the next run.
"""
from __future__ import annotations

import json
import random
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Callable

from ..adapters.base import Candidate, parse_track
from . import jobs as J
from .fuzzy import edit_distance, words
from .searching import collect
from .service import ActionBlocked, looks_like_ad_bot

WISH_EVERY_S = (20 * 60, 30 * 60)        # a wish is re-run every 20–30 min (jittered)
WISH_FIRST_S = (60, 150)                 # first run after start: give the engine time to settle in
WISH_DEADLINE_S = 30.0                   # the standing search's deadline (shorter than a user's 40 s)
WISH_DAYS = 30                           # a wish is a standing order for this long, renewable with one click
WISH_MAX_TRIES = 3                       # candidates sent to quarantine per search before giving up
WISH_MAX_QUEUE = 5                       # a source with more than this many ahead isn't worth the wait
LOSSLESS = {"flac", "wav", "aiff", "aif"}
VERSION_WORDS = {"remix", "edit", "bootleg", "mashup", "rework", "flip", "vip", "dub", "instrumental",
                 "acapella", "acappella", "live", "cover", "karaoke"}


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _within_typo(word: str, haystack: list[str], tol: int | None = None) -> bool:
    if tol is None:
        tol = 1 if len(word) <= 4 else 2
    if tol == 0:
        return word in haystack
    return any(w == word or (abs(len(w) - len(word)) <= tol and edit_distance(w, word, tol) <= tol) for w in haystack)


WISH_LENGTH_TOL_S = 4                    # a playlist's length is the strongest "same track" signal there is


def gate(query: str, c: Candidate, settings, already_have: Callable[[Candidate], dict | None] | None = None,
         expect_s: int | None = None, artist: str = "", title: str = "", mix: str = "") -> str:
    """Why this candidate is NOT good enough for an automatic request — "" when it passes every rule.
    Every rule is a plain sentence so the wishlist page can show why nothing qualified."""
    name = c.display_name or c.remote_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    name_words = words(name) + words(c.folder or "")
    if c.locked:
        return "locked"
    if c.note:
        return c.note.lower()
    if looks_like_ad_bot(c.user):
        return "ad bot"
    ext = (c.extension or "").lower()
    if ext not in {e.lower().lstrip(".") for e in settings.extensions}:
        return f".{ext or '?'} not accepted"
    for w in words(query):
        if not _within_typo(w, name_words):
            return f"missing “{w}”"
    lossless = ext in LOSSLESS
    if not lossless:
        floor = getattr(settings, "wish_min_kbps", None) or settings.mp3_min_kbps
        if not c.bitrate_kbps:
            return "bitrate unknown"
        if c.bitrate_kbps < floor:
            return f"{c.bitrate_kbps} kbps is under your {floor} floor"
    if c.length_s and c.size:
        implied = c.size * 8 / c.length_s / 1000
        if not lossless and (implied < 48 or implied > 400):
            return "size doesn't fit the length"
        if lossless and implied < 300:
            return "too small for lossless"
    if c.size and c.size > settings.max_file_mb * 1024 * 1024:
        return "over the size limit"
    if expect_s and c.length_s and abs(c.length_s - expect_s) > WISH_LENGTH_TOL_S:
        return f"length {c.length_s // 60}:{c.length_s % 60:02d} isn't the playlist's {expect_s // 60}:{expect_s % 60:02d}"
    if not c.free_slot and (c.queue_length is None or c.queue_length > WISH_MAX_QUEUE):
        return "source is busy"
    wished = set(words(query))
    p_artist, p_title, p_mix = parse_track(name)
    if artist or title or mix:
        # the structured wish: each part is matched where it belongs
        tw, aw, mw = words(p_title), words(p_artist), words(p_mix)
        for w in words(title):                                 # typed on purpose: exact, or one slip on a long word
            if not _within_typo(w, tw or name_words, tol=0 if len(w) <= 7 else 1):
                return f"title is missing “{w}”"
        for w in words(artist):
            if not _within_typo(w, aw + name_words + words(c.user or "")):
                return f"artist is missing “{w}”"
        if mix:
            for w in words(mix):
                if w not in VERSION_WORDS and not _within_typo(w, mw + name_words):
                    return f"mix is missing “{w}”"
            if VERSION_WORDS & set(words(mix)) and not (VERSION_WORDS & set(mw + name_words)):
                return "not the version you asked for"
        elif VERSION_WORDS & set(name_words):
            return "a remix/edit you didn't ask for"
    else:
        if VERSION_WORDS & set(name_words) and not (VERSION_WORDS & wished):
            return "a remix/edit you didn't ask for"
        tw = words(p_title)
        if tw and not all(_within_typo(w, tw + name_words) for w in wished if w not in VERSION_WORDS):
            return "title doesn't match"
    if already_have is not None:
        have = already_have(c)
        if have:
            return "you already have it"
    return ""


def rank(c: Candidate):
    """Best first: free slot, shortest queue, fastest source, lossless, highest bitrate."""
    return (0 if c.free_slot else 1, c.queue_length if c.queue_length is not None else 1_000_000,
            -(c.upload_speed or 0), 0 if (c.extension or "").lower() in LOSSLESS else 1, -(c.bitrate_kbps or 0))


class Wishlist:
    """Owns the `wishes` table. `tick()` is called from the window's poll (off the UI thread), one at a
    time; it advances whichever wish needs it: run a due search, or follow a candidate through the check."""

    def __init__(self, svc, log: Callable[[str], None] = lambda s: None):
        self.svc = svc
        self.log = log
        self._started = time.monotonic()
        self._first_delay = random.uniform(*WISH_FIRST_S)
        self.on_found: Callable[[dict], None] | None = None      # window hook: ring the bell

    # ---- CRUD --------------------------------------------------------------
    def add(self, query: str = "", playlist: str | None = None, position: int | None = None, expect_s: int | None = None,
            artist: str = "", title: str = "", mix: str = "") -> dict:
        """A wish from free text, or from the form (any of artist / title / mix). The network is asked
        for all the words together; the gate matches each part where it belongs."""
        artist, title, mix = (" ".join(x.split()) for x in (artist or "", title or "", mix or ""))
        if not query:
            if not (artist or title):
                raise ValueError("A wish needs at least a title or an artist.")
            query = " ".join(x for x in (artist, title, mix) if x)
        query = " ".join(query.split())
        for w in self.svc.db.wishes():
            if w["query"].lower() == query.lower() and w["status"] != "found" and w.get("playlist") == playlist:
                return w
        wish = dict(id=str(uuid.uuid4()), query=query, status="watching", next_run_at=_iso(_now()), runs=0, tries=0, seen=1,
                    playlist=playlist, position=position, expect_s=expect_s, artist=artist, title=title, mix=mix,
                    expires_at=_iso(_now() + timedelta(days=WISH_DAYS)))
        self.svc.db.insert_wish(**wish)
        self.log(f"wish added: {query!r}")
        return self.svc.db.wish(wish["id"])

    def all(self) -> list[dict]:
        return self.svc.db.wishes()

    def remove(self, wish_id: str) -> None:
        self.svc.db.delete_wish(wish_id)

    def pause(self, wish_id: str, on: bool) -> None:
        w = self.svc.db.wish(wish_id)
        if not w:
            return
        if on:
            self.svc.db.update_wish(wish_id, status="paused")
        elif w["status"] == "paused":
            self.svc.db.update_wish(wish_id, status="watching", next_run_at=_iso(_now()))

    def watch_again(self, wish_id: str) -> None:
        """After a found match was dealt with (or wasn't the one), or after the 30 days ran out: keep
        looking, for another WISH_DAYS from now."""
        self.svc.db.update_wish(wish_id, status="watching", job_id=None, found_at=None, seen=1, tries=0,
                                candidates_json=None, next_run_at=_iso(_now() + timedelta(seconds=random.uniform(*WISH_EVERY_S))),
                                expires_at=_iso(_now() + timedelta(days=WISH_DAYS)))

    @staticmethod
    def days_left(w: dict) -> int | None:
        at = _parse(w.get("expires_at"))
        return None if at is None else max(0, (at - _now()).days)

    def unseen(self) -> int:
        return sum(1 for w in self.svc.db.wishes() if w["status"] == "found" and not w["seen"])

    def mark_seen(self) -> None:
        for w in self.svc.db.wishes():
            if w["status"] == "found" and not w["seen"]:
                self.svc.db.update_wish(w["id"], seen=1)

    # ---- scheduling ---------------------------------------------------------
    def due(self) -> dict | None:
        if time.monotonic() - self._started < self._first_delay:
            return None
        now = _now()
        for w in self.svc.db.wishes():
            if w["status"] == "checking":
                return w                                           # follow-ups first: they cost no search
        for w in sorted(self.svc.db.wishes(), key=lambda w: w.get("next_run_at") or ""):
            if w["status"] == "watching":
                ends = _parse(w.get("expires_at"))
                if ends is not None and ends <= now:
                    self.svc.db.update_wish(w["id"], status="expired", note=f"Nothing turned up in {WISH_DAYS} days")
                    self.log(f"wish {w['query']!r}: expired")
                    continue
                at = _parse(w.get("next_run_at"))
                if at is None or at <= now:
                    return w
        return None

    def tick(self, busy: Callable[[], bool] = lambda: False) -> dict | None:
        """One step of work, or None. Never runs a search while the user is searching, nor when the
        search budget would have to wait (the user's own searches come first)."""
        w = self.due()
        if w is None:
            return None
        if w["status"] == "checking":
            return self._follow(w)
        if busy() or self.svc.search_budget.wait_needed() > 0:
            return None
        if not self.svc.adapter_logged_in():
            return None
        return self._run(w)

    # ---- the work -------------------------------------------------------------
    def _run(self, w: dict) -> dict:
        wid, q = w["id"], w["query"]
        self.svc.db.update_wish(wid, last_run_at=_iso(_now()), runs=(w.get("runs") or 0) + 1,
                                next_run_at=_iso(_now() + timedelta(seconds=random.uniform(*WISH_EVERY_S))))
        try:
            self.svc.engine_housekeeping()
            res = collect(self.svc, q, WISH_DEADLINE_S, budget=self.svc.search_budget, log=self.log, check_login=False)
        except Exception as e:                                    # engine away, network down: next run
            self.log(f"wish {q!r}: search failed: {e}")
            self.svc.db.update_wish(wid, note=f"Last check failed: {e}")
            return self.svc.db.wish(wid)
        if res is None:
            return self.svc.db.wish(wid)
        try:
            self.svc.forget_search(res.search_id)
        except Exception:
            pass
        reasons: dict[str, int] = {}
        good: list[Candidate] = []
        for c in res.candidates:
            why = gate(q, c, self.svc.settings, self.svc.already_have, expect_s=w.get("expect_s"),
                       artist=w.get("artist") or "", title=w.get("title") or "", mix=w.get("mix") or "")
            if why:
                reasons[why] = reasons.get(why, 0) + 1
            else:
                good.append(c)
        good.sort(key=rank)
        n = len(res.candidates)
        if not good:
            top = ", ".join(f"{k} ×{v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])[:3])
            note = (f"{n} result{'s' if n != 1 else ''}, none good enough ({top})" if n else "Nobody online had it") \
                if not res.error else f"Last check failed: {res.error}"
            self.log(f"wish {q!r}: {note}")
            self.svc.db.update_wish(wid, last_seen=n, note=note, candidates_json=None)
            return self.svc.db.wish(wid)
        self.log(f"wish {q!r}: {len(good)} of {n} pass the gate; requesting the best")
        self.svc.db.update_wish(wid, last_seen=n, tries=0, candidates_json=json.dumps([asdict(c) for c in good[:WISH_MAX_TRIES]]),
                                note=f"{len(good)} of {n} results look right — checking the best one")
        return self._request_next(self.svc.db.wish(wid))

    def _request_next(self, w: dict) -> dict:
        """Send the next remaining candidate to quarantine; back to watching when none are left."""
        wid = w["id"]
        rest = [Candidate(**d) for d in json.loads(w.get("candidates_json") or "[]")]
        while rest and (w.get("tries") or 0) < WISH_MAX_TRIES:
            c = rest.pop(0)
            try:
                job = self.svc.request_download(c)
            except ActionBlocked as e:
                self.log(f"wish {w['query']!r}: skipped {c.display_name!r}: {e}")
                continue
            except Exception as e:
                self.log(f"wish {w['query']!r}: request failed: {e}")
                continue
            self.svc.db.update_wish(wid, status="checking", job_id=job["id"], tries=(w.get("tries") or 0) + 1,
                                    candidates_json=json.dumps([asdict(x) for x in rest]),
                                    note=f"Checking “{c.title or c.display_name}” from {c.user}")
            self.log(f"wish {w['query']!r}: requested {c.display_name!r} from {c.user!r} (job {job['id'][:8]})")
            return self.svc.db.wish(wid)
        self.svc.db.update_wish(wid, status="watching", job_id=None, candidates_json=None,
                                note="The matches didn't check out — looking again later")
        return self.svc.db.wish(wid)

    def _follow(self, w: dict) -> dict | None:
        """A candidate is in quarantine: wait for its verdict. Good / Have a look → found (bell).
        Broken / error / gone → next candidate."""
        wid = w["id"]
        job = self.svc.db.job(w.get("job_id") or "")
        if job is None:
            return self._request_next(w)
        st = job["state"]
        if st in (J.QUEUED, J.STAGING, J.ANALYZING, J.PROMOTING):
            return None                                            # still on its way
        if st == J.READY:
            a = self.svc.db.analysis(job["id"]) or {}
            if a.get("overall_status") in ("PASS", "WARN"):
                self.svc.db.update_wish(wid, status="found", found_at=_iso(_now()), seen=0,
                                        note="Found — waiting for you on the Ready tab")
                self.log(f"wish {w['query']!r}: FOUND {job['original_name']!r} ({a.get('overall_status')})")
                found = self.svc.db.wish(wid)
                if self.on_found:
                    self.on_found(found)
                return found
            # Broken: it goes nowhere on its own (the user may still look at it); try the next one
            self.log(f"wish {w['query']!r}: {job['original_name']!r} came back Broken; next")
            return self._request_next(w)
        if st in (J.PROMOTED,):
            self.svc.db.update_wish(wid, status="found", found_at=_iso(_now()), seen=1, note="In your library")
            return self.svc.db.wish(wid)
        # ERROR, REJECTED, CANCELLED, EXPIRED
        self.log(f"wish {w['query']!r}: job {job['id'][:8]} ended {st}; next")
        return self._request_next(w)


# ---- batch import ---------------------------------------------------------------------
def parse_list(text: str) -> list[tuple[str, int | None]]:
    """Turn a pasted playlist into (query, expected seconds) pairs.
    Understands: one track per line ("Artist - Title", "01. Artist – Title", "Title by Artist"), an
    Exportify / TuneMyMusic / Soundiiz CSV (header with Track Name / Artist Name / Duration), an M3U
    (#EXTINF:240,Artist - Title). Duration becomes the gate's length check when the source gives one."""
    import csv
    import io
    import re
    text = text.strip()
    if not text:
        return []
    lines = [ln.rstrip() for ln in text.splitlines()]
    head = lines[0].lower()
    out: list[tuple[str, int | None]] = []
    # CSV with a header naming the track/artist columns
    if "," in head and ("track" in head or "title" in head) and "artist" in head:
        rows = list(csv.DictReader(io.StringIO(text)))
        cols = {k.lower().strip(): k for k in (rows[0].keys() if rows else [])}

        def pick(*names):
            for n in names:
                for low, real in cols.items():
                    if n in low:
                        return real
            return None
        c_title = pick("track name", "title", "track")
        c_artist = pick("artist name", "artist")
        c_dur = pick("duration")
        for r in rows:
            title = (r.get(c_title) or "").strip() if c_title else ""
            artist = (r.get(c_artist) or "").strip() if c_artist else ""
            artist = re.split(r"[,;/]| feat\.? | ft\.? ", artist, maxsplit=1)[0].strip() if artist else ""
            if not title:
                continue
            secs = None
            if c_dur and (r.get(c_dur) or "").strip():
                v = r[c_dur].strip()
                try:
                    n = float(v.replace(",", ""))
                    secs = int(round(n / 1000)) if ("ms" in c_dur.lower() or n > 20_000) else int(round(n))
                except ValueError:
                    m = re.match(r"(\d+):(\d\d)", v)
                    secs = int(m.group(1)) * 60 + int(m.group(2)) if m else None
            out.append((_clean(f"{artist} {title}"), secs))
        return out
    # M3U / plain lines
    pending_secs = None
    for ln in lines:
        if not ln.strip():
            continue
        if ln.startswith("#EXTINF:"):
            m = re.match(r"#EXTINF:\s*(-?\d+)[^,]*,(.*)", ln)
            if m:
                pending_secs = int(m.group(1)) if int(m.group(1)) > 0 else None
                out.append((_clean(m.group(2)), pending_secs)); pending_secs = None
            continue
        if ln.startswith("#") or "://" in ln or re.search(r"\.(mp3|flac|wav|aiff?|m4a)$", ln, re.I):
            continue                                            # comments, URLs and file paths are not tracks
        s = re.sub(r"^\s*\d{1,3}[.)\-]\s*", "", ln)              # "01. " / "3) " numbering
        s = re.sub(r"\s+\d{1,2}:\d\d\s*$", "", s)                 # trailing "3:42"
        m = re.match(r"(.+?)\s+by\s+(.+)$", s, re.I)
        if m and " - " not in s and " – " not in s:
            s = f"{m.group(2)} {m.group(1)}"
        out.append((_clean(s), None))
    return [(q, t) for q, t in out if q]


def split_query(q: str) -> tuple[str, str, str]:
    """Best guess at (artist, title, mix) from what someone typed in the search box, to pre-fill the form.
    "Artist - Title (Mix)" splits cleanly; anything else lands in the title."""
    import re
    q = " ".join(q.split())
    mix = ""
    m = re.search(r"[\(\[]([^)\]]+)[\)\]]\s*$", q)
    if m and (VERSION_WORDS & set(words(m.group(1))) or "mix" in m.group(1).lower()):
        mix, q = m.group(1).strip(), q[:m.start()].strip()
    for sep in (" - ", " – ", " — "):
        if sep in q:
            a, t = q.split(sep, 1)
            return a.strip(), t.strip(), mix
    return "", q, mix


def wish_label(w: dict) -> str:
    """What a wish is called on the page: the form's parts when there are any, else the query."""
    if w.get("title") or w.get("artist"):
        s = w.get("title") or ""
        if w.get("artist"):
            s = f"{w['artist']} — {s}" if s else w["artist"]
        if w.get("mix"):
            s += f" ({w['mix']})"
        return s
    return w["query"]


def _clean(s: str) -> str:
    import re
    s = re.sub(r"[\-–—|•·]+", " ", s)
    s = re.sub(r"\((?:feat|ft)\.?[^)]*\)", " ", s, flags=re.I)
    return " ".join(s.split())
