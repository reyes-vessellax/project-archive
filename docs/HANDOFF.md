# Handoff — Pied Piper (working name), v0.5.8

For: Reyes, picking up macOS debugging and general engineering.
From: JR (chris-gooding) and the assistant that built 0.2 → 0.5.8 with him.

This document is the contract for the next stretch of work. Everything in **Non-negotiables** is the
product; everything else is open to improvement.

---

## 1. What this is, in one paragraph

A desktop app for DJs that searches a peer-to-peer network, pulls a chosen file into a **quarantine**
folder, **checks it** (true format, bitrate, play-through, spectrogram + frequency-cutoff detector),
gives a verdict — **Good / Have a look / Broken** — and only then lets the user **Download to
Library** (hash-verified, into `<library>/Pied Piper/`) or **Delete**. Nothing reaches the library
without the user's decision. Everything runs locally; there are no servers of ours in the loop.

## 2. Non-negotiables (the core idea — do not stray from these)

1. **Quarantine first, always.** A file never lands in the user's library until it has been checked
   and the user has said yes. No "trust this source" shortcuts, no auto-import.
2. **Evidence, not promises.** The app never labels a file "authentic", "verified" or "lossless-
   confirmed". It shows what it measured and a plain-English verdict in three words: Good / Have a
   look / Broken. Keep the wording.
3. **The user decides.** Download to Library and Delete are explicit clicks. Have-a-look needs a
   confirm; Broken can only be deleted. Automatic retries are fine; automatic *decisions* are not.
4. **Invisible plumbing.** The user never sees the engine's name, its API, its port, or a raw log.
   Per-user identity and API key are generated silently; firewall prompts carry the app's name;
   anything technical lives under Settings → Advanced. Error text is plain English.
5. **One network search per query** and a client-side budget. The network rate-limits accounts that
   search often; the 0.4.x "ladder" (four searches per query) proved it (see CHANGELOG 0.5.6). Don't
   add searches per query to make things feel faster; stop the one search when results dry up instead.
6. **No modal dialogs in the everyday flow.** Status strip and inline text only. (Settings/account
   actions may confirm.) A test (`tests/test_no_stray_windows.py`) fails the build if any widget is
   ever shown as a stray top-level window — keep it green.
7. **Local by default.** No telemetry, no uploads, no account server until the backend work in the
   roadmap is done deliberately. Logs stay on the user's machine unless they choose to send them.
8. **Light and dark both first-class**, Sora + IBM Plex Mono, the v5 design. New screens follow
   `app/ui/theme.py` tokens and `widgets.py` helpers rather than ad-hoc styling.

If a change makes Windows faster or macOS work and keeps all eight, do it. If a change needs one of
them to bend, write it up in `docs/DECISIONS_AND_FLAGS.md` and talk to JR before building it.

## 3. Where things are

```
app/
  config.py        APP_NAME / APP_SLUG / APP_VERSION / PREVIOUS_NAMES, Settings dataclass, data_dir()
  adapters/        SourceAdapter contract (base.py) + the bundled engine adapter (slskd_adapter.py)
  core/            service.py (state machine, quarantine, promote/reject, downloads, retries, bots)
                   analyzer.py + rules.py (checks and verdict), slskd_manager.py (engine lifetime),
                   procs.py (stray-process reclaim, Windows Job Object), upnp.py, firewall.py,
                   credentials.py (OS keyring), account.py (local account), fuzzy.py (typo fallback)
  media/           decode.py (FFmpeg pipe), probe.py, spectrogram.py
  storage/db.py    SQLite schema + MIGRATIONS (add columns there; never edit old migrations)
  ui/              main_window.py (shell, search loop, polling), pages.py (Home/Search/Review),
                   library_page.py, settings_page.py, onboarding.py, tour.py, widgets.py, theme.py,
                   brand.py (the "pp" mark + icon)
  bench.py         --bench mode for search comparisons
packaging/build.py PyInstaller + icon generation + folder tidy (Windows and macOS branches)
.github/workflows/build.yml   tests (Win+mac) → windows-app → macos-app matrix (AppleSilicon, Intel)
docs/              ROADMAP_1.0.md, DECISIONS_AND_FLAGS.md (attorney flags), SEARCH_TEST_CASES.md,
                   UI_HANDOFF.md, this file
tests/             103 tests; fake_slskd.py is a behaviourally faithful engine (responses only after a
                   search ends, PUT = stop, time-outs, ad bots); conftest makes synthetic audio
```

Data at runtime lives in the user profile (`%APPDATA%\Pied Piper` on Windows, `~/Library/Application
Support/Pied Piper` on macOS): `archive.db`, `staging/` (quarantine), `spectrograms/`, `client/`
(engine instance: `engine.log`, `slskd.yml`, `data/`), `app.log`, `bench.csv`.

## 4. Build, test, release

```
pip install -r requirements.txt pytest
python -m pytest -q            # all green before any push; ~55 s
python -m app                  # run from source (FFmpeg on PATH; engine optional)
python packaging/build.py      # local packaged build (dist/Pied Piper[.app])
```

- **Version** lives in two places and a test keeps them equal: `app/config.py:APP_VERSION` and
  `pyproject.toml`. Bump both; add a `CHANGELOG.md` entry; one line per user-visible change.
- **CI** runs on every push and on *Run workflow*. Artifacts: `PiedPiper-<ver>-Windows`,
  `PiedPiper-<ver>-macOS-AppleSilicon`, `PiedPiper-<ver>-macOS-Intel` (Intel runners are scarce on
  GitHub; expect queueing). Each app build runs the packaged binary with `--self-test` (FFmpeg,
  engine start, audio playback) and, on macOS, mounts the dmg, copies the app out, verifies the
  signature survived and self-tests the copy. A red self-test means no artifact — intended.
- **Signing**: Windows unsigned (SmartScreen "Run anyway"); macOS ad-hoc signed, not notarized
  (right-click → Open once). Decision deferred by JR; see DECISIONS_AND_FLAGS.

## 5. macOS — what's known, what to look at

Verified only on GitHub's runners so far; nobody has run the dmg on a real Mac yet.

Known good: static FFmpeg (arm64 and x86_64) found at `Contents/Frameworks/vendor/ffmpeg`, engine
starts and answers on loopback, Qt audio plays, dmg mounts, codesign verifies after copy.

Likely first problems, in order of my suspicion:
1. **Gatekeeper**: "damaged and can't be opened" = quarantine on an unsigned app. Workaround
   `xattr -dr com.apple.quarantine "/Applications/Pied Piper.app"`; real fix is notarization.
2. **Engine binary permissions** inside the bundle after dmg copy (`chmod +x` is applied at build;
   confirm `ls -l Contents/Frameworks/vendor/engine`).
3. **Firewall prompt** for the engine naming the binary — macOS shows its own dialog; nothing to do
   but confirm it says "Pied Piper Engine".
4. **Keyring**: `credentials.py` uses the OS keyring with a 0600 JSON fallback; on macOS that's the
   login Keychain — first run may prompt. Make sure the prompt text isn't alarming.
5. **Process reclaim**: `procs.kill_by_name` uses `pgrep -x` on macOS; the engine's process name has
   spaces ("Pied Piper Engine"). Verify stray engines are actually found.
6. **UPnP** and **reveal_in_folder** (`open -R`) are untested on a real Mac.
7. **Data dir migration** from previous names on macOS paths.

Where to read: Settings → Advanced → Open logs folder (`app.log`, `client/engine.log`,
`client/logs/`). `app.log` names every search, download retry, stray window and crash.

## 6. Working agreement

- Work on your own fork/branch; PR to `main` when green. Keep PRs focused; one subject each.
- Don't change the verdict words, the three decisions, the quarantine flow, or the no-dialog rule.
- Any change to search cadence (`SEARCH_*` constants in `main_window.py`) needs a log from a real
  session showing it doesn't go dark (see CHANGELOG 0.5.6 and `docs/SEARCH_TEST_CASES.md`).
- Windows is the primary platform today; a macOS fix that would slow or complicate Windows should
  be platform-gated (`sys.platform`) rather than global.
- Record decisions and anything that needs the attorney in `docs/DECISIONS_AND_FLAGS.md` (D-numbers
  and F-numbers), not in chat.
- Don't commit while JR is mid-test on a build unless he says so; he tests from the artifacts.

## 7. Open items (short list; full list in ROADMAP_1.0.md)

- Intel Mac build needs a real-Mac run (JR has an Intel MacBook).
- "janeret" returned 0 on 0.5.7 — re-check on a quiet account.
- UPnP: JR's router answers "no router found"; manual port-forward instructions in Settings → Advanced
  would help users in the same spot.
- Installer + auto-update, standing searches with bell, already-have-it check, BPM/key, backend.
