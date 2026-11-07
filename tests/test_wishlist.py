"""Wishlist: the quality gate, and the standing search landing a match in quarantine (0.6.2)."""
import time

from app.adapters.base import Candidate
from app.config import Settings
from app.core import jobs as J
from app.core.wishlist import Wishlist, gate

from tests.test_soulseek import API_KEY, connected, slskd  # noqa: F401  (fixtures)


def cand(name="Artist - Dance It Out.mp3", ext="mp3", kbps=320, size=None, length=240, free=True, queue=0,
         user="dj_fred", locked=False, note="", folder="Music"):
    size = size if size is not None else int(kbps * 1000 / 8 * length)
    return Candidate("soulseek", user, f"@@x\\{folder}\\{name}", size, display_name=name, folder=folder,
                     extension=ext, bitrate_kbps=kbps, length_s=length, free_slot=free, queue_length=queue,
                     locked=locked, note=note)


S = Settings()


def test_gate_passes_the_obvious_match_and_names_every_failure():
    assert gate("dance it out", cand(), S) == ""
    assert gate("dance it out", cand(locked=True), S) == "locked"
    assert gate("dance it out", cand(user="www.shop.com"), S) == "ad bot"
    assert gate("dance it out", cand(name="Artist - Dance It.mp3"), S).startswith("missing")
    assert "under your" in gate("dance it out", cand(kbps=192), S)
    assert gate("dance it out", cand(ext="flac", kbps=None, size=30_000_000), S) == ""      # lossless: no floor
    assert gate("dance it out", cand(size=900_000), S) == "size doesn't fit the length"
    assert gate("dance it out", cand(free=False, queue=40), S) == "source is busy"
    assert gate("dance it out", cand(free=False, queue=2), S) == ""
    assert "remix" in gate("dance it out", cand(name="Artist - Dance It Out (Dom Dolla Remix).mp3"), S)
    assert gate("dance it out remix", cand(name="Artist - Dance It Out (Dom Dolla Remix).mp3"), S) == ""
    assert gate("dance it out", cand(name="Artist - Dance It Ouy.mp3"), S) == ""           # one typo is fine
    assert gate("dance it out", cand(), S, already_have=lambda c: {"where": "library"}) == "you already have it"
    assert "playlist's" in gate("dance it out", cand(length=240), S, expect_s=300)
    assert gate("dance it out", cand(length=242), S, expect_s=240) == ""


def test_add_is_idempotent_and_due_waits_for_the_first_delay(connected):
    wl = connected.wishlist
    a = wl.add("real  track"); b = wl.add("Real Track")
    assert a["id"] == b["id"] and a["query"] == "real track" and a["status"] == "watching"
    assert wl.due() is None                                   # first run waits WISH_FIRST_S after start
    wl._first_delay = 0
    assert wl.due()["id"] == a["id"]
    wl.pause(a["id"], True); assert wl.due() is None
    wl.pause(a["id"], False); assert wl.due()["id"] == a["id"]
    wl.remove(a["id"]); assert wl.all() == []


def test_tick_searches_requests_and_rings_the_bell(connected, slskd):
    wl = connected.wishlist
    wl._first_delay = 0
    found = []
    wl.on_found = found.append
    w = wl.add("real track")
    assert wl.tick(busy=lambda: True) is None                 # never while the user is searching
    w = wl.tick()                                             # the standing search runs, best match requested
    assert w["status"] == "checking" and w["job_id"], w
    assert w["runs"] == 1 and w["tries"] == 1
    job = connected.db.job(w["job_id"]); assert job["state"] == J.QUEUED
    assert wl.tick() is None                                  # still on its way: nothing to do, no search spent
    connected.poll_downloads()                                # fake delivers
    connected.analyze(w["job_id"])                            # the ordinary check
    w = wl.tick()
    assert w["status"] == "found" and w["seen"] == 0 and found and found[0]["id"] == w["id"]
    assert wl.unseen() == 1
    wl.mark_seen(); assert wl.unseen() == 0
    assert connected.db.job(w["job_id"])["state"] == J.READY   # waiting for the user: nothing auto-promoted
    wl.watch_again(w["id"])
    assert connected.db.wish(w["id"])["status"] == "watching"


def test_nothing_good_enough_is_explained_and_rescheduled(connected, slskd):
    wl = connected.wishlist
    wl._first_delay = 0
    w = wl.add("low track", expect_s=400)                      # the fake says every file is 40 s long
    w = wl.tick()
    assert w["status"] == "watching" and "none good enough" in (w["note"] or ""), w
    assert "length" in w["note"] and w["last_seen"] == 1
    assert w["next_run_at"] > w["last_run_at"]
    w2 = wl.add("nobody has this")
    w2 = wl.tick()
    assert w2["status"] == "watching" and w2["note"] == "Nobody online had it" and w2["last_seen"] == 0


def test_broken_match_moves_to_the_next_candidate(connected, slskd, monkeypatch):
    """Two sources for the same track; the first delivers a cut-off file → Broken → the second is tried."""
    wl = connected.wishlist
    wl._first_delay = 0
    good = r"@@peer\Music\Artist - Same Track.mp3"
    bad = r"@@other\Music\Artist - Same Track.mp3"
    import pathlib
    fx = {p: v for p, v in slskd.library.items()}
    slskd.library[bad] = next(v for k, v in fx.items() if "Cut Off" in k)
    slskd.library[good] = next(v for k, v in fx.items() if "Real" in k)
    slskd.user_for = {bad: "peer_z", good: "peer_a"}
    # make the bad one rank first: pretend it's the faster source by ordering (rank ties → list order)
    monkeypatch.setattr("app.core.wishlist.rank", lambda c: (0 if c.user == "peer_z" else 1,))
    w = wl.add("same track")
    w = wl.tick(); assert w["status"] == "checking"
    first = w["job_id"]
    connected.poll_downloads(); connected.analyze(first)
    assert connected.db.analysis(first)["overall_status"] == "FAIL"
    w = wl.tick()                                             # Broken → next candidate, no new search
    assert w["status"] == "checking" and w["job_id"] != first and w["tries"] == 2 and w["runs"] == 1
    connected.poll_downloads(); connected.analyze(w["job_id"])
    w = wl.tick()
    assert w["status"] == "found"


def test_a_wish_is_a_30_day_standing_order_that_can_be_renewed(connected):
    from app.core.wishlist import WISH_DAYS
    wl = connected.wishlist; wl._first_delay = 0
    w = wl.add("rare one")
    assert Wishlist.days_left(w) in (WISH_DAYS - 1, WISH_DAYS)
    connected.db.update_wish(w["id"], expires_at="2000-01-01T00:00:00+00:00")
    assert wl.due() is None
    w = connected.db.wish(w["id"]); assert w["status"] == "expired" and "30 days" in w["note"]
    wl.watch_again(w["id"])
    w = connected.db.wish(w["id"]); assert w["status"] == "watching" and Wishlist.days_left(w) >= WISH_DAYS - 1


def test_parse_list_handles_lines_csv_and_m3u():
    from app.core.wishlist import parse_list
    plain = "01. Dom Dolla - Dance It Out\n2) Fred again.. – Marea (we've lost dancing) 3:42\nGirl by Jamie xx\n\n# comment"
    assert parse_list(plain) == [("Dom Dolla Dance It Out", None), ("Fred again.. Marea (we've lost dancing)", None),
                                 ("Jamie xx Girl", None)]
    csv_text = ('Track URI,Track Name,Album Name,Artist Name(s),Release Date,Duration (ms),Popularity\n'
                'spotify:track:1,Dance It Out,Single,"Dom Dolla, Someone",2024-01-01,215000,70\n'
                'spotify:track:2,Marea,Actual Life,Fred again..,2021-04-16,242004,60\n')
    assert parse_list(csv_text) == [("Dom Dolla Dance It Out", 215), ("Fred again.. Marea", 242)]
    m3u = "#EXTM3U\n#EXTINF:240,Dom Dolla - Dance It Out\nC:\\Music\\dance.mp3\n#EXTINF:-1,Jamie xx - Girl\nhttp://x/y.mp3\n"
    assert parse_list(m3u) == [("Dom Dolla Dance It Out", 240), ("Jamie xx Girl", None)]


def test_window_watch_button_bell_and_page(connected, slskd):
    """Through the real window: Watch this search → wish; the tick finds it; the tab shows ●1; opening the tab clears it."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from tests.test_ui_search import spin
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    s = connected.settings; s.setup_done = True; s.tour_done = True; connected.save_settings(s)
    connected.accounts.sign_up("T", "t@example.com", "correct-horse-battery")
    w = MainWindow(connected); w.resize(1200, 800); w.show(); spin(app, 0.5)
    w._tab("search"); spin(app, 0.5)
    w.searchp.q.setText("Artist - Real Track"); w.searchp.watch_btn.click(); spin(app, 0.1)
    assert w.searchp.wish_form.isVisible() and w.searchp.wish_form.artist.text() == "Artist"
    assert w.searchp.wish_form.title.text() == "Real Track"
    w.searchp.wish_form.btn.click(); spin(app, 0.1)
    wishes = connected.wishlist.all(); assert len(wishes) == 1 and wishes[0]["status"] == "watching"
    assert wishes[0]["artist"] == "Artist" and wishes[0]["title"] == "Real Track" and not w.searchp.wish_form.isVisible()
    assert "Watching" in w.statusBar().currentMessage()
    connected.wishlist._first_delay = 0
    for _ in range(100):                                      # the window's own tick loop does the rest
        w._wish_tick(); spin(app, 0.2)
        st = connected.wishlist.all()[0]["status"]
        if st == "checking":
            break
    assert st == "checking"
    for _ in range(100):
        spin(app, 0.2)                                        # poll_downloads + analysis run on the window's timers
        w._wish_tick()
        if connected.wishlist.all()[0]["status"] == "found":
            break
    assert connected.wishlist.all()[0]["status"] == "found"
    spin(app, 0.3)
    assert "● 1" in w.topbar.tabs["wishlist"].text()
    w._tab("wishlist"); spin(app, 0.1)
    assert w.topbar.tabs["wishlist"].text() == "Wishlist"
    assert w.wishlistp.rows.count() > 1 and "FOUND" in [c.widget().findChildren(type(w.wishlistp.count))[0].text()
                                                       for c in (w.wishlistp.rows.itemAt(0),)][0]
    w.close()


def test_structured_wish_matches_each_part_where_it_belongs():
    from app.core.wishlist import split_query, wish_label
    ok = cand(name="Chris Gooding - Solaris.mp3")
    assert gate("chris gooding solaris", ok, S, artist="Chris Gooding", title="Solaris") == ""
    assert gate("", cand(name="Other Guy - Solaris.mp3", folder="Chris Gooding Promos"), S, artist="Chris Gooding", title="Solaris") == ""
    assert "artist is missing" in gate("", cand(name="Other Guy - Solaris.mp3"), S, artist="Chris Gooding", title="Solaris")
    assert "title is missing" in gate("", cand(name="Chris Gooding - Polaris.mp3"), S, artist="Chris Gooding", title="Solaris")
    assert "remix" in gate("", cand(name="Chris Gooding - Solaris (Fred Remix).mp3"), S, artist="Chris Gooding", title="Solaris")
    assert gate("", cand(name="Chris Gooding - Solaris (Fred Remix).mp3"), S, title="Solaris", mix="Fred Remix") == ""
    assert "mix is missing" in gate("", cand(name="Chris Gooding - Solaris (Fred Remix).mp3"), S, title="Solaris", mix="Dom Dolla Remix")
    assert gate("", cand(name="Chris Gooding - Solaris (Extended Mix).mp3"), S, title="Solaris", mix="Extended Mix") == ""
    assert "mix is missing" in gate("", cand(name="Chris Gooding - Solaris.mp3"), S, title="Solaris", mix="Extended Mix")
    assert split_query("Chris Gooding - Solaris (Extended Mix)") == ("Chris Gooding", "Solaris", "Extended Mix")
    assert split_query("solaris chris gooding") == ("", "solaris chris gooding", "")
    assert wish_label({"query": "x", "artist": "Chris Gooding", "title": "Solaris", "mix": "Extended Mix"}) == "Chris Gooding — Solaris (Extended Mix)"


def test_add_from_the_form_builds_the_query(connected):
    wl = connected.wishlist
    w = wl.add(artist="Chris Gooding", title="Solaris")
    assert w["query"] == "Chris Gooding Solaris" and w["artist"] == "Chris Gooding" and w["title"] == "Solaris"
    import pytest
    with pytest.raises(ValueError):
        wl.add(mix="Extended Mix")
