"""Rekordbox export: valid rekordbox.xml with BPM, key, cues, file URLs; optional copy to a folder."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from app.core.rekordbox import RbTrack, export, location
from tests.conftest import needs_ffmpeg


def test_xml_has_tracks_cues_and_playlist(tmp_path):
    f = tmp_path / "Phuture - Acid Tracks.mp3"; f.write_bytes(b"x" * 100)
    g = tmp_path / "Fast Eddie - Yo Yo Get Funky.flac"; g.write_bytes(b"y" * 50)
    out = export([RbTrack(f, "Acid Tracks", "Phuture", label="Trax Records", year="1987", bpm=124.6, key="Am",
                          seconds=742, kbps=320, sample_rate=44100, drop_s=64.5),
                  RbTrack(g, "Yo Yo Get Funky", "Fast Eddie", bpm=125.0)], tmp_path / "x.xml", "DigMart · Test", version="0.9.6")
    root = ET.parse(out).getroot()
    t1, t2 = root.find("COLLECTION").findall("TRACK")
    assert t1.get("AverageBpm") == "124.60" and t1.get("Tonality") == "Am" and t1.get("Kind") == "MP3 File"
    assert t1.get("Location").startswith("file://localhost/") and "Phuture%20-%20Acid%20Tracks.mp3" in t1.get("Location")
    marks = [(m.get("Name"), m.get("Num"), m.get("Start")) for m in t1.findall("POSITION_MARK")]
    assert ("Start", "0", "0.000") in marks and ("Preview", "1", "64.500") in marks and ("Preview", "-1", "64.500") in marks
    assert [m.get("Name") for m in t2.findall("POSITION_MARK")] == ["Start"]          # no drop known: no drop cue
    pl = root.find("PLAYLISTS/NODE/NODE")
    assert pl.get("Name") == "DigMart · Test" and [t.get("Key") for t in pl.findall("TRACK")] == ["1", "2"]


def test_copy_to_usb_points_at_the_copies(tmp_path):
    f = tmp_path / "lib" / "a.mp3"; f.parent.mkdir(); f.write_bytes(b"z" * 10)
    usb = tmp_path / "USB"
    out = export([RbTrack(f, "A", "B")], tmp_path / "x.xml", "Friday", copy_to=usb)
    copy = usb / "DigMart" / "Friday" / "a.mp3"
    assert copy.exists() and f.exists()                                               # copied, original kept
    assert ET.parse(out).getroot().find("COLLECTION/TRACK").get("Location") == location(copy)


@needs_ffmpeg
def test_from_library(service, fixtures):
    from app.core.rekordbox import from_library
    job = service.stage(fixtures["mp3_320"]); service.analyze(job["id"]); service.promote(job["id"])
    [t] = from_library(service, [job["id"]])
    assert t.path.exists() and t.bpm and t.kbps == 320


def test_same_file_name_from_two_folders_keeps_both_on_usb(tmp_path):
    (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir()
    f = tmp_path / "a" / "track.mp3"; f.write_bytes(b"1" * 100)
    g = tmp_path / "b" / "track.mp3"; g.write_bytes(b"2" * 200)
    out = export([RbTrack(f, "One", "X"), RbTrack(g, "Two", "Y")], tmp_path / "x.xml", "Friday", copy_to=tmp_path / "usb")
    locs = [t.get("Location") for t in ET.parse(out).getroot().find("COLLECTION")]
    assert len(set(locs)) == 2
    copies = sorted((tmp_path / "usb" / "DigMart" / "Friday").iterdir())
    assert sorted(p.stat().st_size for p in copies) == [100, 200]
    # exporting again reuses the copies instead of piling up more
    export([RbTrack(f, "One", "X"), RbTrack(g, "Two", "Y")], tmp_path / "x.xml", "Friday", copy_to=tmp_path / "usb")
    assert len(list((tmp_path / "usb" / "DigMart" / "Friday").iterdir())) == 2


def test_same_name_same_size_different_track_is_not_reused(tmp_path):
    """Audit (Medium): a same-name, same-size file on the stick was taken as the track without comparing it."""
    usb = tmp_path / "usb"; dest = usb / "DigMart" / "Friday"; dest.mkdir(parents=True)
    (dest / "track.mp3").write_bytes(b"A" * 100)                      # someone else's track, same name and size
    f = tmp_path / "track.mp3"; f.write_bytes(b"B" * 100)
    out = export([RbTrack(f, "One", "X")], tmp_path / "x.xml", "Friday", copy_to=usb)
    loc = ET.parse(out).getroot().find("COLLECTION")[0].get("Location")
    assert "track%20%282%29.mp3" in loc                               # its own copy, not the other track
    assert (dest / "track (2).mp3").read_bytes() == b"B" * 100 and (dest / "track.mp3").read_bytes() == b"A" * 100
