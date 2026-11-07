"""Batch "Download and check" goes out a few at a time: three at most, one per sharer, a gap between starts."""
import random

from app.core.pacer import DownloadPacer


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_eighteen_tracks_never_start_together():
    clock, active, starts = Clock(), [], []
    p = DownloadPacer(lambda: [u for u, _ in active], clock=clock, sleep=clock.sleep, rng=random.Random(1))
    items = [f"user{i % 6}" for i in range(18)]                      # six sharers, three tracks each

    def start(u):
        starts.append((clock.t, u)); active.append((u, clock.t + 40))  # each download takes 40 s

    def sleep(s):
        clock.sleep(s)
        active[:] = [(u, end) for u, end in active if end > clock.t]
    p.sleep = sleep
    left = p.run(items, lambda u: u, start)
    assert left == [] and len(starts) == 18
    times = [t for t, _ in starts]
    assert all(b - a >= 2 for a, b in zip(times, times[1:]))          # a gap between every start
    for t, u in starts:                                               # never more than 4 at once, never 2 per sharer
        running = [v for s, v in starts if s <= t < s + 40]
        assert len(running) <= 4 and running.count(u) == 1


def test_stop_hands_back_the_rest():
    clock = Clock()
    p = DownloadPacer(lambda: [], clock=clock, sleep=clock.sleep)
    done = []
    left = p.run(list(range(10)), lambda i: f"u{i}", done.append, should_stop=lambda: len(done) >= 2)
    assert done == [0, 1] and left == list(range(2, 10))


def test_a_download_waiting_in_a_sharers_queue_doesnt_hold_a_slot(service):
    from app.core import jobs as J
    for i, msg in enumerate(["InProgress", "Queued, Remotely", "Queued, Remotely", "Initializing"]):
        service.db.insert_job(id=f"j{i}", source_kind="soulseek", original_name="x.mp3", state=J.QUEUED,
                              created_at="2026-11-07", updated_at="2026-11-07", remote_user=f"u{i}", message=msg)
    assert sorted(service.download_pacer.active_users()) == ["u0", "u3"]
