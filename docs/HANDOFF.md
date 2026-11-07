# Handoff: DigMart, v0.6.0 (builds 0.6.0.N)

For: Chris (chris-gooding) and his assistant, picking the project back up after 0.5.8.
From: Reyes and the assistant that built 0.6.0 with him (on top of Chris's 0.2 to 0.5.8 work).

Read this first, then `CHANGELOG.md` (0.6.0 entry) and `git log --oneline` since 0.5.8.
Everything in **Non-negotiables** is the product; everything else is open to improvement.

---

## 1. What changed since 0.5.8 (the short version)

- **Name and brand: DigMart.** `APP_NAME = "DigMart"`; "Pied Piper" is in `PREVIOUS_NAMES`, so old installs
  migrate (account, history, engine identity, data folder). Logo files are the brand kit's own artwork in
  `app/ui/brand_assets/` (see section 3). Colours: black, crimson `#DC143C`, yellow `#FFD700`, white.
  Fonts: Poppins (headings), Open Sans (body), IBM Plex Mono (measured values). All bundled.
- **Design v7 ("DigMart + hi-fi"):** left **sidebar** (Home, Search, Ready, Library, Batch), warm off-white with
  a light grain (true black with the same grain in dark), **square corners everywhere** (3 px; only the avatar
  is round), black/yellow active menu item and main button, **dark display tiles with amber readouts** for
  BPM / Key / Length / Format, **amber spectrogram**, **LED level strip** that follows the music while it plays.
- **Music analysis** (`app/media/musical.py`): BPM, key (Camelot + name), and the **drop** (first big rise into
  the loud part; falls back to the liveliest 20 s). Runs during the check, ~1 s per track.
- **Metadata + cover art** (`app/media/metadata.py`): file tags first, then Deezer, MusicBrainz/Cover Art Archive,
  iTunes for the gaps (artist + title only are sent; weak matches ignored). **Rekordbox-ready tags** are written
  to the library copy on Download to Library (never overwriting existing tags; audio is verified before tagging).
- **Search:** filters (Lossless / MP3 320 / Ready now / mix kind / show private) and **plain-English
  availability** (`app/core/availability.py`): "Ready now · ~30 sec", "Short wait · few min", "Long wait · 10+ min",
  "Very long wait", "Busy". Waits stay broad on purpose (the network doesn't tell us enough for minutes).
- **Preview lives in Search only:** "▶ Preview" downloads into quarantine, checks, plays 20 s from the drop,
  stops by itself ("■ Stop" while playing). Downloaded tracks (Ready, Library) play in full: no preview button.
- **Library:** BPM + Key columns, BPM range and Camelot "mixes with" filters, Playlist filter, everything inline.
- **Ready list** clears itself after Download to Library / Delete.
- **Batch** (`app/core/batch.py`, `batch_runner.py`, `app/ui/batch_page.py`): each playlist you drop in is its
  **own batch** (YouTube, SoundCloud, Spotify, Apple Music links, pasted lists, CSV/M3U, or a folder to upgrade).
  One spaced search per track (8 s apart). Tracks kept from a batch go to `<library>/DigMart/<playlist name>/`.
- **Auto save** (`app/core/session.py`): page, selection, search + filters, batches, window size.
- **Automatic updates** (`app/core/updater.py`): see section 4. This changes how pushing to `main` works.

## 2. Non-negotiables

Chris's original eight still hold: quarantine first; evidence, not promises (Good / Have a look / Broken); the
user decides; invisible plumbing; one network search per query (batches are spaced); no modal dialogs in the
everyday flow; local by default; light and dark both first-class. Added in 0.6.0:

9. **Show only what the app really knows at that moment.** Search results have name / size / format / speed /
   queue; BPM, key, drop, spectrum, verdict and preview exist only after the file is downloaded and checked.
10. **Use the brand kit's files as they are.** Never redraw or "reinterpret" the logo. Allowed: transparent
    background, scaling, a plain colour swap for dark mode.
11. **Every push to `main` ships to both of us** (section 4). Test before pushing to `main`; use a branch + PR.

## 3. Where things are (new or changed)

```
app/media/musical.py      BPM, key/Camelot, drop + preview window
app/media/metadata.py     tags read/write (mutagen), online lookup, cover download
app/core/availability.py  wait wording + search filters
app/core/batch.py         playlist/list/folder parsing, best-copy scoring, "already have"
app/core/batch_runner.py  spaced searching of a batch
app/core/session.py       auto save
app/core/updater.py       signed updates (check, download, verify, install on restart)
app/ui/batch_page.py      Batch screen (cards per playlist, stat tiles, track rows)
app/ui/brand.py           logo widget + app icon (uses brand_assets)
app/ui/brand_assets/      digmart-logo(.png/-dark.png), digmart-mark.png, digmart-icon-outline.png,
                          digmart-app-icon.png (burst + smiley on a white tile), grain-light/dark.png
app/ui/theme.py           palettes + tokens (nav_*, cta_*, disp_* for the amber displays)
packaging/make_manifest.py  signs latest.json in CI
```
New dependencies: `mutagen`, `yt-dlp` (titles only, never media), `cryptography` (update signatures).

## 4. Build, test, release (read this one carefully)

```
pip install -r requirements.txt pytest
python -m pytest -q            # 171 tests, all green before any push to main; tests never touch the network
python -m app                  # run from source (does NOT self-update; use git pull)
python packaging/build.py      # local packaged build; bundles fonts + brand_assets
```

- **Every push to `main` = a public release.** CI stamps the run number (`app/_build.py`, so versions are
  `0.6.0.N`), builds Windows + macOS Apple Silicon, signs `latest.json` with the `DIGMART_SIGNING_KEY` repository
  secret, and publishes a GitHub Release marked latest. Installed apps check
  `releases/latest/download/latest.json` a minute after launch and every 6 h, download in the background, show
  "Update ready · restart" in the sidebar, and swap on restart (the old copy is kept until the new one starts).
- **Apps only install updates signed with our key.** The private key is a repo secret (and on Reyes's Mac); the
  public half is in `updater.py`. Never commit the private key. Size and SHA-256 of each download are verified.
- **Bump `APP_VERSION`** (config.py + pyproject.toml, a test keeps them equal) for real versions; the build
  number takes care of every push in between. Add a CHANGELOG line per user-visible change.
- **Intel macOS** was removed from CI (GitHub's Intel runners never start and blocked every release). Build Intel
  locally on an Intel Mac if needed.
- **Signing:** Windows unsigned (SmartScreen "Run anyway"); macOS ad-hoc (right-click → Open the first time).

## 5. Working agreement

- Branch + PR into `main`; keep PRs focused. Remember a merge ships to both apps.
- Don't change the verdict words, the three decisions, the quarantine flow, or the no-dialog rule.
- Search cadence changes (`SEARCH_*` in `main_window.py`, `GAP_S` in `batch_runner.py`) need a real-session log.
- Record decisions and attorney flags in `docs/DECISIONS_AND_FLAGS.md`.
- The repo is **public** now. No secrets, audio, or personal data in commits.

## 6. Open items

- Product decisions still open (unchanged on purpose, by choice): library sharing is ON by default for new users;
  generated Soulseek usernames are made to look human; the smiley mark may be a trademark issue before any
  paid/public launch. See `DECISIONS_AND_FLAGS.md`.
- Spotify / Apple Music playlist links depend on their public pages; pasting the track list always works.
- Code signing / notarization (removes the first-run warnings) when it's time to go wider.
