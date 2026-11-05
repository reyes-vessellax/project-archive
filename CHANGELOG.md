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
- Library tab as a browsable history (today it opens the library folder).

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
