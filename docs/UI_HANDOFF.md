# Project Archive: UI handoff for front-end design

The engine (checks, spectrogram, staging, library moves) is built and tested (35 passing tests).
This file is what the UI has to show and which buttons it can offer. Design anything you like on top,
but every screen should map to the data and actions below.

Stack: **Python + PySide6 (Qt)**, desktop app for macOS and Windows. Designs should be buildable as Qt
widgets: lists, panels, buttons, images, labels. Custom styling via Qt stylesheets (CSS-like) is fine.

## The one workflow

Drop / auto-detect file -> staged into quarantine -> checked (~0.3 s per track) -> user decides -> library or deleted.

## Track states (show as a badge)

| State | Meaning | Allowed actions |
|---|---|---|
| `STAGING` | being copied into quarantine | none |
| `ANALYZING` | checks running (show progress step) | none |
| `READY_FOR_REVIEW` | results ready | Save / Save anyway / Reject / Re-check |
| `PROMOTED` | in the library | Show in folder |
| `REJECTED` | staged copy deleted | none (history only) |
| `ERROR` | something broke (message explains) | Re-check / Reject |
| `EXPIRED` | not decided in time, auto-cleaned | none |

Progress steps while analyzing: `Fingerprinting`, `Probing`, `Decoding`, `Generating spectrum`.

## Overall grade (the big badge)

- `PASS`: show **Save to Library**
- `WARN`: show **Save to Library anyway** (explicit override; never the default)
- `FAIL`: **no save button at all**, only Reject

## Data available for each track

```
original_name        "Artist - Track (Original Mix).mp3"
state                see table above
overall_status       PASS | WARN | FAIL
facts.container      mp3 | wav | flac | aiff      (what the file REALLY is)
facts.codec          mp3 | pcm_s16le | pcm_s24le | flac ...
facts.bitrate_bps    320000  (null = unknown, show "unknown", never 0)
facts.bitrate_mode   CBR | VBR | lossless | unknown
facts.sample_rate_hz 44100
facts.channels       2
facts.bit_depth      16 | 24 | null (MP3 has none)
facts.duration_s     what the file claims
decode.decoded_s     what actually played (cut-off files: claims 6:00, plays 1:15)
cutoff_hz            ~20200 real 320, ~16800 fake 320
spectrogram_path     PNG, 1000 x 512 px, time left->right, 0 Hz at bottom,
                     top = half the sample rate (22.05 kHz for 44.1 kHz files)
tags                 artist / title / album / date if present
sha256               fingerprint
checks[]             list of { id, status, title, message }
```

`checks[]` ids: `format`, `bitrate`, `decode`, `spectrum`, `duration`, `channels`, `silence`.
Messages are already plain English, e.g.
"MP3 reports 192 kbps; your threshold is 320 kbps." Show them as-is.

## Actions the UI can call

| Button | Engine call |
|---|---|
| Add files / drag & drop | `stage(path)` then `analyze(id)` |
| Save to Library | `promote(id)` |
| Save to Library anyway | `promote(id, override_warning=True)` |
| Reject | `reject(id)` |
| Re-check | `analyze(id)` |
| Open staging folder | opens the track's quarantine folder |
| Find (search box) | opens Beatport, Bandcamp, Juno, Traxsource, Discogs search pages |

## Settings screen fields

Library folder, Incoming (watched) folder, MP3 warning level (default 320 kbps), VBR average warning
level (default 220 kbps), keep undecided files for (default 24 h), max file size (default 2048 MB),
accepted formats (mp3, wav, flac, aiff), FFmpeg location (optional).

## Rules the design must respect (from the spec)

- Never auto-save to the library; saving is always a click.
- Disable Save while staging/analyzing; hide it entirely for FAIL.
- Never use the words "verified", "authentic" or "lossless master": the app shows evidence, not proof.
- Don't auto-play audio.
- Show measured facts separately from warnings.
