# Project Archive

A DJ audio preflight tool. Stage a track, see what it **really** is (true format, bitrate, whether it plays
all the way through, and a spectrogram that exposes fake 320s), then explicitly keep it in your library or
reject it. Everything runs locally on your own computer: no uploads, no servers.

> The app reports evidence, not proof. A 320 kbps MP3 or a WAV can still come from a low-quality source.
> It never labels a file "authentic" or "verified lossless". You make the final call.

## Status (v0.1, in progress)

| Done | Next |
|---|---|
| Real format detection, bitrate (CBR/VBR), sample rate, bit depth, channels | Chris's front-end design |
| Full play-through test with claimed-vs-actual length check | Windows testing (Chris) |
| Spectrogram + frequency-cutoff warning | History / search filters |
| PASS / WARN / FAIL with plain-English reasons | App icon, signing (later) |
| Quarantine, Save to Library (hash-verified, never overwrites), Reject | |
| Watched Incoming folder, auto-cleanup, crash recovery, settings | |
| Store search (Beatport, Bandcamp, Juno, Traxsource, Discogs) | |
| 35 automated tests on synthetic audio | |

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

## How it works

Drop a track (or let the watched folder pick it up) -> it's copied into a private quarantine folder ->
checked -> you choose **Save to Library** (PASS), **Save to Library anyway** (WARN, explicit), or
**Reject**. FAIL can only be rejected. Your original file is never modified or deleted.

| Check | Method |
|---|---|
| Actual format | FFprobe + file signature, compared with the extension |
| Bitrate | FFprobe; CBR/VBR from the LAME/Xing header |
| Plays through | Full FFmpeg decode; actual length compared with the length the file claims |
| Frequency cutoff | Averaged FFT spectrum; warns when energy stops well short of what the format implies |
| Fingerprint | SHA-256, re-verified after copying into the library |

## Layout

```
app/core      workflow: service (stage/analyze/promote/reject), rules, jobs, safety, analyzer
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

No Soulseek protocol or automation, no hosting or sharing of music, no uploads. Users are responsible for
having the right to obtain and keep each file.

## Licensing note

The Windows build bundles an FFmpeg GPL build from BtbN/FFmpeg-Builds (license text included in the
bundle). Fine for private use between us; revisit before distributing publicly.
