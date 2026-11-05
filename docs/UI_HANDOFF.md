# Project Archive: UI handoff for front-end design

The engine (Soulseek search through slskd, download into quarantine, checks, spectrogram, library moves)
is built and tested (52 passing tests). This file is what the UI has to show and which buttons it can
offer. Design anything you like on top, but every screen should map to the data and actions below.

Stack: **Python + PySide6 (Qt)**, desktop app for macOS and Windows. Designs should be buildable as Qt
widgets: lists, tables, panels, buttons, images, labels. Custom styling via Qt stylesheets (CSS-like) is fine.

## The one workflow

Search Soulseek -> results -> user picks one -> it downloads into quarantine -> checked (5 at a time, the rest
wait in the queue) -> results shown -> user chooses **Download to Library** or **Delete**.

Local files can also be dragged in or picked up from a watched folder; they join the same queue.

## Screens

1. **Search results** (right side, replaces the review panel while browsing). A search box in the top
   bar, a results table, a **Check this file** button. Double-click does the same.
2. **Queue** (left side, always visible). Every track in every state, newest first.
3. **Review** (right side). Facts, spectrogram, checks, decision buttons for the selected queue item.
   Selecting a queue item switches back to this page; a **Search results** button goes back to the table.
4. **Settings** dialog.

## Connection status (top bar)

| Shown as | Meaning |
|---|---|
| green dot · `Connected to Soulseek as <name>` | slskd is running and logged in; search works |
| amber dot · `slskd is running but not logged in to Soulseek` | slskd up, no network yet |
| grey dot · `Local mode. Add your slskd API key in Settings to search Soulseek.` | no API key set; drag & drop only |
| grey dot · `Can't reach slskd at <url>. Is it running?` / `slskd rejected the API key…` | problems to fix in Settings |

Refreshed every 15 seconds and after Settings is saved.

## Search results: data per row

```
display_name    "Artist - Track (Original Mix).mp3"   file name on the peer's machine
folder          "Compilation Vol 2"                   remote parent folder (often the album/release)
user            "someuser"                            peer that offers it
size            bytes
bitrate_kbps    320 | null      what the PEER'S client claims. Show as "claimed"; our check decides later
vbr             true | false | null
length_s        247 | null
free_slot       true | false    peer can start sending right now
queue_length    0..n | null     files already waiting on that peer
upload_speed    bytes/s | null
locked          true | false    can't be requested; show greyed
```

Default sort: free slot first, shortest queue, then claimed bitrate. Results arrive over ~20 seconds; the
header shows "searching…" then "done". Only files in the accepted-formats list are shown.

## Track states (show as a badge in the queue)

| State | Meaning | Allowed actions |
|---|---|---|
| `QUEUED` | slskd is downloading it (show `progress` 0–100 and `message`, slskd's own state text) | Cancel download |
| `STAGING` | being moved/copied into quarantine | none |
| `ANALYZING` | checks running (show progress step), or waiting for a free slot | none |
| `READY_FOR_REVIEW` | results ready | Download / Download anyway / Delete / Re-check |
| `PROMOTED` | in the library | Show in library |
| `REJECTED` | deleted from quarantine; nothing left on disk | none (history only) |
| `CANCELLED` | download cancelled before it arrived | none (history only) |
| `ERROR` | something broke (`message` explains, e.g. "Download failed: Completed, Errored") | Re-check (if a file exists) / Delete |
| `EXPIRED` | not decided in time, auto-cleaned | none |

Progress steps while analyzing: `Fingerprinting`, `Probing`, `Decoding`, `Generating spectrum`.
A track past the parallel limit sits in `ANALYZING` with "Waiting for a free slot…".

## Overall grade (the big badge)

- `PASS`: show **Download to Library**
- `WARN`: show **Download anyway** (explicit override; never the default)
- `FAIL`: **no download button at all**, only Delete

## Data available for each track

```
original_name        "Artist - Track (Original Mix).mp3"
source_kind          soulseek | manual | folder
remote_user          peer the file came from (soulseek only)
state                see table above
progress             0–100 while QUEUED
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
| Search Soulseek | `search(text)` then `search_results(id)` every second until `finished` |
| Check this file (on a result) | `request_download(candidate)` -> job appears in the queue as QUEUED |
| (automatic, every 2 s) | `poll_downloads()` -> finished downloads move to quarantine, then `analyze(id)` |
| Cancel download | `cancel(id)` |
| Add local files / drag & drop | `stage(path)` then `analyze(id)` |
| Download to Library | `promote(id)` |
| Download anyway | `promote(id, override_warning=True)` |
| Delete | `reject(id)` |
| Re-check | `analyze(id)` |
| Open staging folder / Show in library | opens the folder |
| Settings | `save_settings(settings)` |

Top-bar status: `connector_status()`.

## Settings screen fields

Download-to folder (the library), Incoming (watched) folder, slskd URL, slskd API key (password field;
empty = Soulseek off), slskd downloads folder, MP3 warning level (default 320 kbps), VBR average warning
level (default 220 kbps), check this many tracks at once (default 5), keep undecided files for (default
24 h), max file size (default 2048 MB), accepted formats (mp3, wav, flac, aiff), FFmpeg location (optional).

## Rules the design must respect (from the spec)

- Never auto-download to the library; it is always a click.
- Disable Download while downloading/staging/analyzing; hide it entirely for FAIL.
- Never use the words "verified", "authentic" or "lossless master": the app shows evidence, not proof.
  The bitrate in search results is what the peer claims; label it that way.
- Don't auto-play audio.
- Show measured facts separately from warnings.
- Don't show the user's Soulseek password anywhere; the app never has it (slskd does).
