# DigMart

*The Google of music.* (Working name. We'll change it. Probably.)

DigMart is a desktop platform that lets DJs discover, acquire, and validate music across a
decentralized peer-to-peer ecosystem — with a trust layer in front of the library so nothing lands
in your crates until it's been checked. Think of it as **audio pre-flight**: every file passes through
quarantine, gets a full-spectrum analysis, and earns a verdict before you decide whether it ships.

> We surface evidence, not promises. A file is never labeled "authentic" or "verified lossless" —
> the verdict is **Good**, **Have a look**, or **Broken**, with the receipts. You make the call.

## What it does today (v0.5)

**Discover.** One search fans out across the network in waves, so results populate top-down while the
long tail keeps arriving — consistently matching or beating the incumbent clients on result counts.
Sources are ranked by availability and speed, locked and off-format files are shown but greyed,
advertising bots are detected and sunk, and a search that comes back empty quietly retries without
the word most likely to be a typo (and says so).

**Acquire.** Pick a result and it streams into a sandboxed quarantine — never your library. Downloads
that stall are retried automatically; the review page shows live progress; a failed one can be
re-requested with one click.

**Validate.** Each file is decoded end to end and graded: true container and codec vs. the extension,
bitrate (CBR/VBR), sample rate, bit depth, channels, play-through integrity, and a spectrogram with a
frequency-cutoff detector that exposes up-sampled fakes. Five checks run in parallel; the rest queue.

**Decide.** Good / Have a look / Broken. **Download to Library** moves the file (hash-verified, never
overwrites) into a dedicated folder inside your existing library; **Delete** removes it for good.

**Library.** Every track you've kept, with its facts, a filter-as-you-type search, an inline drop-down
with the spectrogram and a built-in player (playhead crawls across the spectrum), and *Show in folder*.

**Zero-config networking.** The transport engine is bundled and invisible: a per-user identity and
API key are provisioned silently, the router is asked to open a port automatically, firewall prompts
carry the app's name, and stray engine processes from earlier sessions are reclaimed on start.

**Polish.** Light and dark themes (Sora + IBM Plex Mono), a first-run tour, smooth momentum scrolling,
a start-up screen that lights each step as it completes, local accounts with sign-up / sign-in, and a
Settings → Advanced escape hatch (logs, port status, start fresh).

Everything runs on the user's machine. No uploads, no servers, no telemetry.

## Platforms

| | Status |
|---|---|
| Windows 10/11 (x64) | Test builds on every push; unsigned for now (*More info → Run anyway* once) |
| macOS (Apple Silicon and Intel) | Test builds on every push, one dmg per chip; ad-hoc signed, not yet notarized (*right-click → Open* once) |
| Linux | Builds from source; no packaged app yet |

Builds are published as artifacts on **Actions → Test and build → latest green run**:
`DigMart-<version>-Windows` (zip of the app folder) and `DigMart-<version>-macOS-AppleSilicon` / `-Intel` (a `.dmg`: open it, drag the app to Applications).

## Architecture (one paragraph)

Python 3.13 + PySide6 front end; a service layer owning a SQLite state machine
(DISCOVERED → QUEUED → STAGING → ANALYZING → READY_FOR_REVIEW → PROMOTED / REJECTED); a media layer on
bundled FFmpeg/FFprobe and NumPy for decoding, spectral analysis, and rendering; and a pluggable
**source adapter** contract behind which the bundled P2P engine (and, later, store integrations) live.
Credentials sit in the OS keyring. The engine is driven over a loopback-only API with a per-user key.

```
app/
  adapters/    source adapter contract + the bundled engine adapter
  core/        service, analyzer, rules, account, credentials, firewall, UPnP, process lifetime
  media/       decode, probe, spectrogram
  storage/     SQLite schema + migrations
  ui/          theme, widgets, pages, onboarding, tour, library, settings
packaging/     PyInstaller build, icon generation, folder tidy
tests/         100+ tests on synthetic audio and a behaviourally faithful fake engine
```

## Roadmap to 1.0

See [`docs/ROADMAP_1.0.md`](docs/ROADMAP_1.0.md). Headlines: already-have-it detection, standing
searches with a notification bell and auto-validation, auto-update, live network status, BPM and key
detection (validated against the user's own tagged library), source reputation, silent pre-checks,
hosted accounts, one-click diagnostic reports, installers, signing and notarization.

## Developing

```
pip install -r requirements.txt pytest
python -m pytest -q          # ~100 tests, ~50 s
python -m app                # run from source (needs FFmpeg on PATH)
python packaging/build.py    # local packaged build
```

New here? Start with [`docs/HANDOFF.md`](docs/HANDOFF.md) (what must not change, where things are, how to build and ship).
Decisions and open legal flags: [`docs/DECISIONS_AND_FLAGS.md`](docs/DECISIONS_AND_FLAGS.md).
Change history: [`CHANGELOG.md`](CHANGELOG.md).


## Thanks and open-source licences

Special thanks to the **slskd** team. DigMart's download engine is [slskd](https://github.com/slskd/slskd)
0.26.2, bundled unmodified and renamed *DigMart Engine*, under the
[GNU Affero General Public License v3.0](https://www.gnu.org/licenses/agpl-3.0.html).

| Component | Version | Licence | Source |
|---|---|---|---|
| slskd (ships as *DigMart Engine*) | 0.26.2 | AGPL-3.0, copy at `vendor/engine/LICENSE` | <https://github.com/slskd/slskd/tree/0.26.2> |
| FFmpeg / FFprobe | latest GPL build at build time | GPL-3.0, copy at `vendor/ffmpeg/FFMPEG-LICENSE.txt` | <https://github.com/FFmpeg/FFmpeg> (builds: <https://github.com/BtbN/FFmpeg-Builds>) |
| PySide6 (Qt for Python) | see `requirements.txt` | LGPL-3.0 | <https://code.qt.io/cgit/pyside/pyside-setup.git/> |
| NumPy, Mutagen, yt-dlp | see `requirements.txt` | BSD-3-Clause, GPL-2.0-or-later, Unlicense | their project pages |

You may copy, study, change and share slskd and FFmpeg under their licences; nothing in DigMart's own terms
limits that. The same notes ship inside every copy of the app (`README.txt`). The engine version is set in one
place, `ENGINE_VERSION` in `app/config.py`; moving to a new engine release is described in
[`docs/ENGINE_UPDATES.md`](docs/ENGINE_UPDATES.md).
