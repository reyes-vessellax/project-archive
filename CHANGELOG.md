# Changelog

All notable changes to DEADWAX (working name; formerly Project Archive). Dates are build dates.
The product name is the `APP_NAME` constant in `app/config.py`; when the final name is chosen, that
one line changes and this file gets a note.

## Unreleased

- Account backend on the website (sign-up, sign-in, license check); the in-app screens already exist.
- Plan & billing: the account page shows the section; nothing is stored or charged yet.
- App icon (window, taskbar, exe).
- Installer with code signing and a Windows Firewall rule named after the app, so the first-launch
  firewall prompt disappears (see `docs/DECISIONS_AND_FLAGS.md`, D15).
- macOS build with the bundled engine.
- Support / FAQ page on the website (the Help button already points at `SUPPORT_URL`).
- "Find it to buy" store search (Beatport, Bandcamp, Juno, Traxsource, Discogs); the code is kept, no button.

## 0.4.4 — unreleased (more search results)

Aimed at matching what SoulseekQt shows for the same words.
- **Open port.** The engine now listens on a fixed port chosen once per user (49152–65000) and the app
  asks the router to forward it with UPnP at every start (`app/core/upnp.py`, standard library only).
  Other users deliver results and files straight to us instead of via the server's slow indirect
  route. Settings → Advanced shows the port and whether the router agreed; UPnP can be turned off.
- **Longer collection.** Searches stay open up to 45 s (was 15) and stop 10 s after the last new
  result (was 3.5); first rows still paint within a second and the count ticks up.
- **Bigger caps.** The engine keeps up to 2,000 responses / 20,000 files per search (was 300 / 4,000).
- **Other formats are shown, greyed, tagged "Extension mismatch"** instead of hidden, so the source
  count matches other clients. They sort to the bottom and can't be picked; the header says how many.

## 0.4.3 — unreleased (no popups, Search tab, library drop-down)

- **Search** tab in the top bar brings back your last results at any time.
- Library: click a track and a drop-down opens under the list with the spectrogram + player, verdict,
  facts, the checks, Show in folder and Full details. Click the same row again (or Close) to fold it.
- Library "Show in folder" works on Windows (Explorer wanted `/select,"path"` as one argument).
- No more popups in the everyday flow: deleting a checked track from the queue no longer asks first
  (the status strip says what happened); Download / Delete problems go to the status strip too.
- Download to Library and Delete run off the UI thread (hash check + copy used to freeze the window
  for a moment); the buttons grey out until it's done.
- Faster refreshes: finished analyses are read from the database once and cached.
- Diagnostics: every top-level window that appears is logged to `app.log` with where it came from, so
  a stray popup can be named from the log.

## 0.4.1 — unreleased (one engine, tidy folder, × on the left)

### Fixed: searches coming back with 0 sources
Every build signs into the same Soulseek account (the one the app created for the user). When an
engine from an earlier run was still alive — the app was ended from Task Manager, crashed, or an
older build's engine never exited — the two sign-ins kicked each other off the server in turns and
searches returned nothing while the other side held the session. Now:
- before the engine starts, the app ends any engine it started before (pid file) and any process
  running under one of our engine names;
- the engine is attached to a Windows Job Object, so it ends the moment the app process ends, however
  it ends (Task Manager included);
- only one copy of the app runs at a time ("DEADWAX is already running").

### Changed
- × for clearing a queue entry is on the LEFT of each row (queue and the Ready rail), where the hand
  already is. Rows stay aligned when there's nothing to clear.
- The app folder is tidier: `_internal/vendor/ffmpeg/` and `_internal/vendor/engine/` hold what we
  bundle; unused Qt modules, translations, the engine's web UI and packaging leftovers are stripped
  (about 60 MB smaller). A README.txt at the top explains the folders.
- Settings → Advanced has **Open logs folder** (engine.log, app.log) for support.
- Uncaught errors are written to `app.log` in the data folder.

## 0.4.0 — unreleased (tour, library, playback)

- Build artifacts carry the version: `DEADWAX-0.4.0-Windows`.
- First-run tour after sign-up: dimmed overlay, a spotlight on one control at a time, Back / Next,
  and a small always-visible "Skip tour" in the bottom-right. Click inside the spotlight to try the
  control. Replay any time from the avatar menu ("Take the tour").
- Library tab is now a page: every downloaded track with Title / Artist / Mix / Format / Bitrate /
  Length / Checked / Added / File, a search box that filters as you type, **Show in folder** (selects
  the file in Explorer / Finder), Details (opens the track's review page), and Open downloads folder.
  Files moved or deleted outside the app are shown greyed.
- The spectrogram is kept after a download, so Library and Details still show it.
- Queue housekeeping: **Clear finished** (removes every downloaded / deleted / cancelled / errored
  entry from the list in one go), × on every finished row in the Ready rail, and "Remove from list"
  on a finished track's review page. Downloaded files always stay in the library.
- Clicking a queue row opens that exact track in the review page (it always did; the rail now
  highlights it, and long titles no longer push the × off the edge).
- **Play** button and playhead on the spectrogram (Home "Last checked" and the review page): press
  play, the track plays and a white playhead crawls across the picture in time; click anywhere on the
  picture to jump there; space pauses. Works on quarantined and downloaded tracks.
- Search results page: "Nobody online is sharing a match" now appears in the results area itself,
  not in the small line under the search box; the same spot shows the plain-English reason when a
  search fails. Results page 100 at a time: scroll to the bottom (or click the "Load 100 more" row)
  to reveal the next page, keeping your scroll position.

## 0.3.5 — 2026-11-05 (downloads folder)

- Approved downloads go into a `DEADWAX` folder inside the library folder the user chose, created on
  the first download. People can point the app at their whole library (which is also what gets
  shared), and everything the app brings in stays in one place. If the chosen library is already a
  folder named after the app, nothing is nested. The Library tab opens that folder once it exists.
- Default library folder is now plain `Music` (was `Music\Project Archive Library`).

## 0.3.4 — 2026-11-05 (firewall)

- Before the engine starts, the app asks Windows whether this engine is already allowed through the
  firewall. If it is (from a previous click or a previous build at the same path), nothing is shown.
  If it isn't, one question — "Allow it now?" — adds a firewall rule named after the app with a
  single Windows confirmation, so Windows' own prompt never appears. Remembered per build path; the
  old "firewall note" is gone.

## 0.3.3 — 2026-11-05 (resources, Error category)

### Fixed: the app bogged down after 5–6 tracks
- FFmpeg's output pipes were never closed after a decode, leaking two OS handles per track; and
  each analysis kept tens of MB of spectrum data alive after it finished. Pipes are now closed,
  the spectrum memory is released as soon as the PNG is written, and the number of spectra kept
  per track is capped (a file lying about its length can't grow it without bound).
- The engine is told to forget each download the moment it's moved into quarantine (or failed),
  completed transfers and old searches are cleared on sign-in, every 10 minutes, and every five
  searches — nothing stays lurking in its lists.
- Cancel now removes the transfer from the engine instead of leaving it marked cancelled.

### Error category
- "Error" is its own word tag (red) for tracks whose download or check failed, with a short reason
  (download failed / couldn't stage / check failed). Word tags are coloured everywhere: queue rows,
  review rail, counts, verdict. Error rows get a red left edge in the review rail.
- Search results from a source that already failed us, or whose file turned out broken, are shown in
  red with "⚠ failed before" / "⚠ broken file" in the Speed column.

## 0.3.2 — 2026-11-05 (search speed, flashing window)

- Fixed: a small blank window kept flashing at the top of the screen and stole focus (clicking the
  avatar "kicked you out"). The avatar menu was a hidden popup window that got re-styled on every
  status tick. It is now created on click and destroyed on close, and the stylesheet is applied only
  when the theme actually changes.
- A search that the engine ends with an error now says so ("The search couldn't run…") instead of a
  silent "0 sources"; a real empty result gets a plain explanation and a suggestion.

- First results appear in about 0.3 s (was at least 1 s): the first poll is at 300 ms and backs off
  to 1.5 s; the table redraws only when the number of results changed.
- A search finishes about 3.5 s after results stop arriving (12 s cap), instead of a fixed 15–20 s
  of "still collecting". The engine's own search timeout is 8 s (was 15).
- Results table shows the best 400 rows, inserted in one batch with repaints suspended.
- One kept-alive connection to the engine per thread.
- The home queue no longer rebuilds its rows on every download poll when nothing visible changed.
- Measured with 1,500 results trickling in over 4 s: first rows at 0.31 s, done at 4.4 s, 7 redraws.

## 0.3.1 — 2026-11-05 (security pass + start-up fix)

### Start-up
- Fixed: a dialog box naming the engine kept popping up while the engine was still signing in
  (every failed background call opened its own popup, and search polls once a second).
  Background problems now show once in the status strip, never as a popup, and no message names
  the engine.
- New "Getting things ready…" screen after sign-up and on every launch: spinner and three steps
  (engine, network, sharing). The app opens when signed in; after 90 s it opens anyway with a note,
  and a real failure shows the Try again / Help dialog.
- Search is disabled with the connection message as its placeholder until the engine is signed in.

### Security

- A result's file type is taken from its file name, never from the type the peer's client reports;
  a file named `evil.exe` tagged "mp3" is no longer listed, and can't be requested.
- A requested download that fails validation on arrival (wrong type, empty, oversize) is deleted
  instead of being left in the engine's folder. Nothing unreviewed stays on disk.
- Invisible and right-to-left override characters are stripped from remote names everywhere they are
  shown or saved, so a name can't display as a different file type than it is.
- Text that comes from inside a file (decoder messages) is escaped before it is shown in the review
  checks; no markup from a file reaches the interface.
- Finished downloads are also found when the engine had to rename them for Windows
  (`?`, `:`, `*` and friends become `_`).
- Sizes reported by peers are clamped (negative or non-numeric → 0); passwords are capped at 256
  characters so a huge password can't stall sign-in.
- 72 automated tests.

## 0.3.0 — 2026-11-05

### New look (design v5)
- Light and dark themes (Settings → Appearance), one amber accent, bundled typefaces Sora (UI and
  headlines) and IBM Plex Mono (readouts). Both are OFL; licenses ship in `app/ui/fonts/`.
- Home: hero search field, one queue with a word tag per row (Down / Check / Wait / Good / Look /
  Broken / Done / Gone), progress and a short readout, "Last checked" spectrogram with format,
  bitrate, rate and length, and Good / Have a look / Broken counts with one "Review N tracks →" button.
- Search results: Title · Mix · Artist · Folder · User · Size · Rate · Length · Speed, fastest sources
  first, Check this file on select or double-click.
- Review: verdict as words (Good / Have a look / Broken) with "N things to check", facts strip,
  spectrogram with the cutoff line, checks as a list with the problem first, Download to Library /
  Download anyway / Delete, Re-check, Open folder. Keyboard: ↑↓ move, Enter downloads, Delete deletes.
- Settings as a page: Account, Library & sharing, Checks, Appearance, Advanced.
- Avatar menu (top right) replaces the gear: Account & profile, Settings, Appearance, Help & FAQ,
  What's new, Sign out.

### Account (local for now)
- Sign up with name, email and password; sign in afterwards. Only a salted PBKDF2 hash is stored,
  never the password. Everything lives on the user's machine until the website backend exists.
- Account page: profile (name, DJ name, bio with a 200-character limit), sign-in details, change
  password, sign out, delete account. Plan & billing section laid out and inert.
- First-launch flow: Account → Your library → Ready.

### Product name
- Placeholder name is now **DEADWAX**, held in one constant. The data folder (`%APPDATA%\DEADWAX`)
  and the engine executable (`DEADWAX Engine.exe`) take the name from it; an existing `Project
  Archive` data folder is renamed on first start and saved secrets carry over, so the Soulseek
  identity and queue history survive the rename.

### Housekeeping
- 66 automated tests. CI uploads the artifact as `DEADWAX-Windows`.

## 0.2.3 — 2026-11-05

- Artist and title are parsed from file names in the "Artist - Title (Mix)" convention, including
  underscores, en/em dashes, "feat." (kept with the title), labels in brackets and leading track
  numbers such as `01.` or `A1`. Names that don't follow the convention keep the whole name under
  Title with Artist blank. Verified against a set of John Summit-style names (9 of 11 clean; the
  reversed "Title - Artist" form and names with no separator stay ambiguous on purpose).
- The mix ("Extended Mix", "Dom Dolla Remix") is its own results column, out of the title.
- The review header shows the real embedded tags (artist, title) once a file has been checked.

## 0.2.2 — 2026-11-04

- The engine ships as `Project Archive Engine.exe` so prompts show the product path. Its embedded
  description can't be edited (a .NET single-file bundle); the installer will add a named firewall
  rule instead.
- × on finished, deleted, cancelled, expired or errored queue entries removes them from the panel;
  history is kept.
- Results columns Title / Artist / Folder / User / Size / Bitrate / Length / Queue / Speed, all
  click-and-drag resizable; the search button is labelled "Search"; fastest sources first (free slot,
  then shortest queue, then upload speed); header sorting off.
- Engine log file closed on stop (Windows file-lock fix).

## 0.2.1 — 2026-11-04

- First-run setup asks for the DJ library folder and shares it back to Soulseek, on by default with
  a one-click opt-out. The 0.2 test showed every download parked at "Queued, Remotely" for an
  account that shares nothing. Settings gets a "Share my library folder" checkbox; the engine
  restarts quietly when sharing changes.

## 0.2.0 — 2026-11-04

### Soulseek search and download
- Search Soulseek from the app; results from other users' clients; "Check this file" downloads the
  pick straight into quarantine, where it is checked before anything can reach the library.
- Downloads are moved (not copied) from the engine's folder into quarantine, so Delete leaves
  nothing on disk; Download to Library moves the approved file to the folder chosen in Settings.
- Up to 5 tracks are checked at once (Settings); more wait in the queue.
- Store search (Beatport, Bandcamp, Juno, Traxsource, Discogs) is kept in the code but off the UI.

### Bundled engine
- slskd is bundled in the Windows build and runs as a hidden background process. First launch
  generates an API key and a human-looking Soulseek account, keeps both in the OS credential vault
  (file fallback, user-only), writes a loopback-only headless config, and starts the engine; it is
  stopped on quit. The Soulseek password is passed by environment variable, never written to disk.
- Status wording never names the engine: "Connecting to …", "Connected to …", "Having trouble
  connecting to the server." with Try again / Help (Help opens the website FAQ, to be created).
- One-time firewall note before the first start, in plain language.
- Advanced settings: own slskd (URL, API key, downloads folder), own Soulseek login, FFmpeg folder.
- Health check uses `/api/v0/application` (any key role); `/server` needs Administrator and answered 403.

### Data
- Jobs gain remote transfer columns (user, path, size, transfer id, progress) and a hidden flag, with
  a migration for existing databases.

### Docs
- `docs/DECISIONS_AND_FLAGS.md`: decisions D1–D17 and attorney flags F1–F6 for the EULA.
- `docs/UI_HANDOFF.md` updated for the new flow; README rewritten.

## 0.1.0 — 2026-11-03 (Reyes)

- Audio preflight engine: real format detection, bitrate (CBR/VBR), sample rate, bit depth, channels,
  full decode with claimed-vs-actual length, spectrogram and frequency-cutoff warning, PASS / WARN /
  FAIL with plain-English reasons, quarantine, hash-verified promotion that never overwrites, reject,
  watched folder, auto-cleanup, crash recovery, settings, 35 tests on synthetic audio, Windows build
  with bundled FFmpeg.
