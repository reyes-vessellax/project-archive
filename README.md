# Project Archive

A Soulseek client built for DJs. Search Soulseek, pick a result, and the file lands in a quarantine folder
where it is checked first: true format, bitrate, whether it plays all the way through, and a spectrogram
that exposes fake 320s. Then you decide: **Download to Library** or **Delete**. Nothing reaches your
library until you say so. Everything runs locally on your own computer: no uploads, no servers.

Under the hood the Soulseek side is handled by [slskd](https://github.com/slskd/slskd), a separately
installed client that owns your Soulseek login and does the searching and downloading. Project Archive
drives it through its local API. We do not implement the Soulseek protocol ourselves.

> The app reports evidence, not proof. A 320 kbps MP3 or a WAV can still come from a low-quality source.
> It never labels a file "authentic" or "verified lossless". You make the final call.

## Status (v0.1, in progress)

| Done | Next |
|---|---|
| Real format detection, bitrate (CBR/VBR), sample rate, bit depth, channels | Chris's front-end design |
| Full play-through test with claimed-vs-actual length check | Windows testing (Chris) |
| Spectrogram + frequency-cutoff warning | History / search filters |
| PASS / WARN / FAIL with plain-English reasons | App icon, signing (later) |
| Quarantine, Download to Library (hash-verified, never overwrites), Delete | |
| Watched Incoming folder, auto-cleanup, crash recovery, settings | |
| Soulseek search + download into quarantine through slskd | |
| Parallel checking (5 at a time by default), the rest queue up | |
| 52 automated tests on synthetic audio and a fake slskd | |

Store search (Beatport, Bandcamp, Juno, Traxsource, Discogs) is kept in the code for a later feature
but is not on a button right now.

## Get the Windows app (no setup)

1. On GitHub, open **Actions -> Test and build -> latest green run**.
2. Download **ProjectArchive-Windows**, unzip it, run `Project Archive.exe`.
3. First launch shows "Windows protected your PC" because the app isn't signed yet:
   click **More info -> Run anyway**.

FFmpeg is bundled inside; nothing else to install.

## Run from source (macOS or Windows)

Needs Python 3.12+ and FFmpeg (`brew install ffmpeg` on Mac; on Windows put `ffmpeg.exe`/`ffprobe.exe`
in `vendor/ffmpeg/` or on your PATH).

```bash
python -m venv ~/.venvs/project-archive          # outside the repo if its path contains ':'
~/.venvs/project-archive/bin/pip install -r requirements.txt pytest   # Windows: ...\Scripts\pip
~/.venvs/project-archive/bin/python -m app        # run the app
~/.venvs/project-archive/bin/python -m pytest     # run the tests
```

Build a standalone app: `pip install pyinstaller`, copy FFmpeg into `vendor/ffmpeg/`, then
`python packaging/build.py` -> `dist/`.

## Connect Soulseek (one-time setup)

1. Install slskd from https://github.com/slskd/slskd/releases and run it once. It creates `slskd.yml`
   in its application folder (`%localappdata%\slskd` on Windows, `~/.local/share/slskd` on Mac).
2. In `slskd.yml`, enter your Soulseek username and password under `soulseek:`, and add an API key:

   ```yaml
   web:
     authentication:
       api_keys:
         project_archive:
           key: choose-a-long-random-string
           role: readwrite
   ```

   Restart slskd. Note the downloads folder it uses (`directories: downloads:` in the same file, or the
   default `downloads` folder inside its application folder).
3. In Project Archive, open **Settings** and fill in the slskd URL (default `http://127.0.0.1:5030`),
   the API key, and slskd's downloads folder. The top bar turns green: "Connected to Soulseek as …".

Leave the API key empty and the app runs in local mode: drag and drop and the watched folder still work.

## How it works

**Search Soulseek** -> results list what other users' clients report (file, folder, user, size, claimed
bitrate, queue) -> **Check this file** -> slskd downloads it and we immediately move it into a private
quarantine folder -> checked (up to 5 tracks at once; more wait in the queue) -> you choose **Download to
Library** (PASS), **Download anyway** (WARN, explicit), or **Delete**. FAIL can only be deleted. Delete
removes the quarantined copy, so nothing is left on your computer. Download to Library moves it into the
folder you chose in Settings.

Local files you drag in are copied into quarantine; your original is never modified or deleted.

| Check | Method |
|---|---|
| Actual format | FFprobe + file signature, compared with the extension |
| Bitrate | FFprobe; CBR/VBR from the LAME/Xing header |
| Plays through | Full FFmpeg decode; actual length compared with the length the file claims |
| Frequency cutoff | Averaged FFT spectrum; warns when energy stops well short of what the format implies |
| Fingerprint | SHA-256, re-verified after copying into the library |

## Layout

```
app/core      workflow: service (search/download/stage/analyze/promote/reject), rules, jobs, safety, analyzer
app/adapters  source connector contract + the slskd adapter (Soulseek through a local client)
app/media     ffprobe/ffmpeg wrappers, streaming decode + spectrum, PNG spectrogram
app/storage   SQLite job history (metadata only, never audio)
app/ui        PySide6 window
docs/         UI_HANDOFF.md: data + actions for front-end design
tests/        synthetic fixtures generated at test time (no copyrighted audio)
```

## Data locations

- Database + quarantine: `~/Library/Application Support/Project Archive` (Mac),
  `%APPDATA%\Project Archive` (Windows)
- Library (default): `~/Music/Project Archive Library`, changeable in Settings

## Out of scope (see the spec)

No Soulseek protocol implementation of our own, no automated mass searching or scraping, no hosting or
sharing of music, no uploads. Project Archive only asks a client you installed and logged in yourself to
run the searches and downloads you click on. Users are responsible for having the right to obtain and
keep each file.

## Licensing note

The Windows build bundles an FFmpeg GPL build from BtbN/FFmpeg-Builds (license text included in the
bundle). Fine for private use between us; revisit before distributing publicly.
