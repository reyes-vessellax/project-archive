"""Upgrade finder: weak copies, better copies shared right now, and a saved upgrade replacing the old track."""
from __future__ import annotations

import pytest

from app.adapters.base import Candidate
from app.core import jobs as J
from app.core import upgrades as U
from tests.conftest import ff, needs_ffmpeg


def cand(user, ext, kbps=None, free=True, q=0, name="Larry Heard - Can You Feel It"):
    a, t = name.split(" - ")
    return Candidate("soulseek", user, f"@@x\\{name}.{ext}", 30_000_000, display_name=f"{name}.{ext}", artist=a, title=t,
                     extension=ext, bitrate_kbps=kbps, free_slot=free, queue_length=q)


def test_better_means_a_real_step_up_and_ready():
    w = U.Weak("j", "Larry Heard", "Can You Feel It", "", "MP3 192", "only 192 kbps", U._rank_file("mp3", 192))
    got = U.better_copies([cand("a", "mp3", 192), cand("b", "mp3", 320), cand("c", "flac"),
                           cand("d", "wav", free=False, q=3), cand("e", "flac", name="Someone Else - Other")], w, 320)
    assert [c.user for c in got] == ["c", "b"]                    # lossless first; same/worse, busy, wrong track out
    w320 = U.Weak("j", "Larry Heard", "Can You Feel It", "", "MP3 320", "not club-ready", U._rank_file("mp3", 320))
    assert [c.user for c in U.better_copies([cand("b", "mp3", 320), cand("c", "flac")], w320, 320)] == ["c"]


@needs_ffmpeg
def test_weak_tracks_and_replacing(service, fixtures, tmp_path):
    good = service.stage(fixtures["flac"]); service.analyze(good["id"]); service.promote(good["id"])
    low = service.stage(fixtures["mp3_192"]); service.analyze(low["id"]); service.promote(low["id"], override_warning=True)
    weak = U.weak_tracks(service)
    assert [w.job_id for w in weak] == [low["id"]] and "192" in weak[0].why
    crate = service.db.create_crate("Friday")
    service.db.add_to_crate(crate, low["id"])
    # the better copy arrives (as if downloaded), marked as the upgrade, and is saved
    new = service.stage(fixtures["flac"]); service.db.event(new["id"], "upgrade_of", low["id"])
    service.analyze(new["id"]); service.promote(new["id"])
    trashed = []
    assert service.finish_upgrade(new["id"], lambda p: (trashed.append(p), True)[1])
    assert service.db.job(low["id"])["state"] != J.PROMOTED and trashed            # old one out, to the Trash
    assert new["id"] in service.db.crate_jobs(crate)                                # same crates
    assert service.finish_upgrade(good["id"], lambda p: True) is None              # not an upgrade: nothing happens
