"""Source reputation (roadmap #6): worked out from the job history, shown last on search, a ranking tie-breaker."""
from __future__ import annotations

import uuid

from app.adapters.base import Candidate
from app.core import jobs as J
from app.core.reputation import Rep, from_rows


def _job(db, user, state, staged=False, size=10_000_000, status=None, req="2026-11-01T10:00:00+00:00",
         stg="2026-11-01T10:00:10+00:00"):
    jid = str(uuid.uuid4())
    db.insert_job(id=jid, source_kind="soulseek", original_name="t.mp3", state=state, remote_user=user,
                  remote_path=f"@@x\\{jid}.mp3", remote_size=size, staged_path=f"/q/{jid}/t.mp3" if staged else None)
    db._con.execute("INSERT INTO events (job_id, timestamp, event_type, message) VALUES (?,?,?,?)", (jid, req, "requested", ""))
    if staged:
        db._con.execute("INSERT INTO events (job_id, timestamp, event_type, message) VALUES (?,?,?,?)", (jid, stg, "staged", ""))
    if status:
        db._con.execute("INSERT INTO analyses (job_id, overall_status, analysis_json) VALUES (?,?,?)", (jid, status, "{}"))
    db._con.commit()
    db.update_job(jid, state=state)                       # bump jobs_version


def test_counts_and_speed_from_history(service):
    db = service.db
    _job(db, "good", J.PROMOTED, staged=True, status="PASS")
    _job(db, "good", J.READY, staged=True, status="PASS")
    _job(db, "flaky", J.ERROR)
    _job(db, "flaky", J.ERROR)
    _job(db, "faker", J.REJECTED, staged=True, status="FAIL")
    _job(db, "patient", J.CANCELLED)                       # user cancelled: not the source's fault
    reps = service.source_reputation()
    g = reps["good"]
    assert (g.delivered, g.failed, g.broken) == (2, 0, 0) and abs(g.speed - 1e6) < 1
    assert reps["flaky"].never_delivers and reps["flaky"].tone() == "fail"
    assert reps["faker"].broken == 1 and reps["faker"].tone() == "fail"
    assert reps["patient"].delivered == 0 and reps["patient"].failed == 0 and reps["patient"].label() == ""
    assert g.label() == "✓2" and g.tone() == "pass_" and "about 1.0 MB/s" in g.sentence()


def test_cache_follows_new_jobs(service):
    assert service.source_reputation() == {}
    _job(service.db, "someone", J.ERROR)
    assert service.source_reputation()["someone"].failed == 1


def test_rank_uses_history_as_tie_breaker_and_sinks_never_delivers():
    from app.ui.pages import _rank
    a = Candidate("soulseek", "a", "p", 1, free_slot=True, queue_length=0, upload_speed=9_000_000)
    b = Candidate("soulseek", "b", "p", 1, free_slot=True, queue_length=0, upload_speed=1_000_000)
    reps = {"b": Rep(delivered=3), "a": Rep()}
    order = sorted([a, b], key=lambda c: _rank(c, "", reps.get(c.user)))
    assert [c.user for c in order] == ["b", "a"]            # proven source beats a faster-claiming unknown
    reps = {"a": Rep(failed=2)}
    slow = Candidate("soulseek", "c", "p", 1, free_slot=False, queue_length=50)
    order = sorted([a, slow], key=lambda c: _rank(c, "", reps.get(c.user)))
    assert [c.user for c in order] == ["c", "a"]            # never delivered, failed twice: below even a long queue


def test_rows_without_user_are_ignored():
    assert from_rows([{"remote_user": None, "state": "ERROR"}]) == {}
