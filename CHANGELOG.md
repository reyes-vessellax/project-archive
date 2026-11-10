# Changelog

All notable changes to DigMart (formerly Pied Piper, DEADWAX, Project Archive). Dates are build dates.
The product name is the `APP_NAME` constant in `app/config.py`; when the final name is chosen, that
one line changes and this file gets a note.

## 0.9.18 (2026-11-10) — no repeats, more artists, rows remembered again

- **Each song once:** a track shows in one row only (For you, an era or a style), and a row never shows the same song
  twice (another mix or copy of it).
- **No single artist takes over a row:** each era now digs 4 of its artists a day (not 2), with at most 4 tracks
  each; a style row shows at most 3 tracks by one artist.
- **Fix: rows were searched again on every start.** DigMart stops a search itself once it's full, and the network
  calls that "cancelled", which 0.9.12 mistook for a failure, so nothing was remembered. Rows are remembered for
  3 hours again, so reopening Discover is instant.

## 0.9.17 (2026-11-10) — no number badges

- For you's tracks no longer carry 01, 02, 03… badges (on a track without cover art they sat on the artist's name).

## 0.9.16 (2026-11-10) — "Preview", not "the drop"

- "Play the drop" is now **Preview** everywhere (Dig the crate, track cards, the Queue, the Library, the tour):
  the 20 seconds aren't always the drop, so nothing promises it. The spectrogram marker, the comment written into
  saved files, and the Rekordbox hot cue B say "preview" too.
- Includes 0.9.15 (the first-run tour, up to date).

## 0.9.15 (2026-11-10) — the first-run tour, up to date

- The tour a new user gets after signing up now matches the app: Dig the crate (Play the drop, Check this file,
  Dig again), For you / eras / styles, and Search (Watch this search when nobody has it), ending with the whole
  loop: hear the drop, check the file, Download to Library from the Queue. (It still described label rows.)
- The track details panel no longer stops on a track with an incomplete check result.

## 0.9.14 (2026-11-10) — Discover goes editorial: The Dig.

- **Discover is now "The Dig."**, a daily issue: a masthead with today's date and the search box, and a strap
  with how many tracks are ready to hear.
- **Dig the crate leads the page:** a dark panel (a little bigger than the rows) with the cover, where the track came
  from (For you, an era, a style), the artist and the year it first came out, why it's here ("Here because you play
  Fast Eddie and Adonis. 3 people are sharing it right now, 2 in lossless."), BPM / key / format / length chips, and
  Play the drop, Dig again and Check this file.
- **The year** a track first came out: the earliest of MusicBrainz and Discogs (a reissue only ever makes it later).
  Right for most records; now and then a classic shows a year or two late when neither lists its original pressing
  under that title.
- **Watch only when nothing's there:** Watch is for tracks nobody is sharing, so it's gone from Dig the crate and the
  track cards (the file is right there), and Search offers "Watch this search" only after a search finds nothing
  you can download. The track card's "More from this label" is now "More by this artist".
- **For you** gets a big section head and numbered tracks (01, 02…). **The eras** are black panels with the years in
  big yellow type, the era's story, and its row of tracks. **Styles of the day** each get a one-line description
  of the sound.
- **Fix: the account menu (bottom-left) opened off screen.** It was still placed for the old top-right avatar; it
  now opens upwards or downwards and left or right, wherever it fits, and always stays on screen.

## 0.9.13 (2026-11-10) — one Discover page that rotates by itself

- The genre pills at the top of Discover are gone: the page is always the daily mix (For you, three eras, five
  styles), and it changes every day on its own.
- Afro house is no longer one of the styles.

## 0.9.12 (2026-11-10) — Discover fills in once you're connected

- **Fix: Discover said "Connect to the network…" forever.** Its rows were built before the engine signed in and
  nothing told them when it did (0.9.9 stopped the 2-second page rebuild that used to nudge them by accident). Now
  the window tells Discover the moment it's connected, and Discover also looks again every 2 s while a row is
  waiting. Rows only search once signed in.
- An empty or failed search is never remembered, so a row that searched too early isn't stuck empty for 3 hours.

## 0.9.11 (2026-11-10) — For you that fits, rows that change daily, nothing slides sideways

- **For you rebuilt:** it was using Deezer's "related artists", which drift to commercial vocal house (Freemasons,
  Didier Sinclair) and, from Soft Cell, to synth-pop. Now: ListenBrainz's similar artists (from what people actually
  play one after another) for the 10 artists you have most of, ranked by how many of yours point at them, each
  checked as house/dance on MusicBrainz and Deezer. On your library today: Mr. Fingers, Phuture, Farley Jackmaster
  Funk, Marshall Jefferson, Tyree, Armando, Steve Poindexter… (Depeche Mode, The Cure, Dean Martin filtered out).
  Today's three are drawn from the best dozen, so it changes every day. First build ~25 s, then ~1 s.
- **Rotates every day:** each style row shows a different first screenful each day (lossless still first), and the
  page reloads its styles, eras and For you artists when the day changes, even if the app stayed open.
- **Genre accuracy:** in each style row, artists MusicBrainz knows for THAT style come first (Acid house: acid
  artists ahead of house-in-general), on top of the house/dance check every artist already passes.
- **No more sideways scrolling:** the Queue's track panel, Discover, Settings and the other pages are pinned to the
  window's width (wide content wraps or squeezes), the Search table's Title and Folder columns squeeze with "…"
  instead of widening it, and a long title in Dig the crate wraps.

## 0.9.10 (2026-11-10) — Discover fills fast, and actually fills

- **Fix: Discover could sit empty for minutes.** Any blip in the engine connection rebuilt every row and cancelled
  every search in flight; each cancelled search still used one of the paced search slots, so with blips coming
  faster than searches finished, nothing ever landed. Now only switching genre cancels anything, a cancelled
  search gives up before it uses a slot, a row that's loading is never queued twice, and rows that were offline
  just fill in when the connection returns.
- **Faster first paint:** each row's first search runs before any row's second, two run at once, and For you
  and the eras show their first artist's tracks the moment that search lands, growing as the rest arrive.
- **Your searches come first:** Discover's (and the upgrade finder's) background searches only go while a search
  slot stays free, so a search you type, and the Wishlist, never wait behind them.

## 0.9.9 (2026-11-10) — Discover without label rows: For you, Eras, Styles, every artist checked

Label rows searched the network for a label's name and kept whatever was filed under it, so wrong songs got in.
They're gone (and Label of the Day with them). Every row now checks its tracks before showing them:
- **For you** (new, top): artists Deezer lists as related to the ones you have most of in your library, tracks
  by those artists only. The row says why: "Because you have Fast Eddie & Moodymann".
- **Eras** (new): the hand-picked artists for each era (Chicago jack 1984–1990, NY & Jersey garage, Detroit deep…),
  a couple a day; tracks by those artists only, records from the era's years first (MusicBrainz's dates are too
  patchy to drop tracks on: it dates Larry Heard's "Can You Feel It" 2014).
- **Styles** (14 now, five a day on Everything): each artist must be known for that music on MusicBrainz;
  pop/rock/rap artists with a stray "dance" tag are out (checked on real data: Metallica, Taylor Swift, Dua Lipa,
  Drake out; Kerri Chandler, Moodymann, Fast Eddie, Larry Levan, Black Coffee in). Artists MusicBrainz doesn't
  know fall back to Deezer.
- Genre pills now pick that genre's eras and styles. Tracks without art get a sleeve with the artist's name.
- Artists are looked up 8 at a time (MusicBrainz allows one request a second: a row's checks went from ~20 s to
  2-3 s), Deezer fallbacks 4 at a time, and everything is remembered for weeks. A famous namesake can't sneak in:
  when Deezer files the name firmly outside dance (Drake), it's out.

Speed:
- The download poll (every 2 s) no longer rebuilds the pages when nothing changed.
- The window logger that ran on every single UI event (mouse moves, repaints) is off; it was logging every
  tooltip with a stack trace. (Set DIGMART_LOG_WINDOWS=1 to turn it on when debugging.)
- Measured on your library: start-up about half a second, page switches under 25 ms, opening a Library row 25 ms.

Audit: every page and button clicked (160 clicks, Library panels opened, played and rebuilt mid-playback, Discover
cards, genre pills, themes): no errors.

Also: app.log is rotated at start-up once it's over 5 MB (the previous one kept as app.log.1); the Library
drop-down no longer shows "10A  ()" when a tag gives a Camelot key without its name.

## 0.9.8 (2026-11-10) — club length only on Discover

- **Discover shows club-length tracks only:** 4 minutes or longer, and no radio / short / intro / 7" edits by name.
  Extended, Original, Club and Dub mixes all stay (classic originals rarely say "Extended"). When a source doesn't
  report the length, it's worked out from the file size (WAV/AIFF 10.1 MB a minute, MP3 size ÷ bitrate, FLAC ~6 MB).
- **Search:** a new "4 min+" filter chip does the same there (on by default in Discover's own search).
- Rows and ready tracks remembered from before are discarded so nothing short shows.

Audit fixes (from a full check: the error log, a code scan, every button clicked):
- **The big one:** after a Library track's panel was rebuilt while it played, the old spectrum view stayed hooked
  to the player and errored on every position tick (over 14,000 errors in one log). Fixed; the panel disconnects
  when it's gone.
- Closing the app while a background job was running no longer logs "closed database" / "deleted" crashes.
- Discover no longer drops artists with "Radio" in the name (Radio Slave) as radio edits.
- Upgrade finder skips tracks already lossless (no copy can beat them), saving searches.
- Rekordbox USB export: two tracks with the same file name from different folders no longer overwrite each other.

## 0.9.7 (2026-11-10) — genre pills; play after switching fixed

- **Genres instead of eras on Discover:** Everything, Deep, Chicago, Detroit, Garage & NY, Soulful, Disco & edits,
  Acid, Ghetto & juke, Tech house, Lo-fi, French filter, Minimal, Afro house, Italo & cosmic, Balearic. Each fills
  the page with its labels' rows and its style rows. Rounded pills with a colour dot; the chosen one is filled.
- **Fix:** after switching era/genre, ▶ on a track did nothing (the track card lived inside a row that was rebuilt
  and got deleted with it).

## 0.9.6 (2026-11-10) — club badges, BPM/key before you download, Rekordbox export, upgrade finder

- **Club-ready at a glance:** a row of badges on a track's details (CDJ ✓ · MONO ✓ · PEAK −0.3 dBTP · −8.1 LUFS ·
  LOW END ✓ · USB ✓), coloured by result; hover one for the full sentence.
- **Fakes marked on the spectrogram:** when the spectrum check doesn't pass, the cutoff line turns red and the missing
  highs above it are shaded ("highs missing").
- **BPM and key before you download:** playing a preview measures the clip and shows "≈ 124 BPM · 8A (A minor)";
  Dig the crate shows them for every ready track.
- **Export to Rekordbox** (Library, or a crate): rekordbox.xml with BPM, key, label, year, bitrate, hot cue A at the
  start and B (plus a memory cue) at the drop; optionally copies the files to a USB stick and points at the copies.
- **Find upgrades** (Library): finds weak copies (MP3 under 320, not Good, not club-ready) and a better copy someone is
  sharing right now (lossless or a real 320, ready to send). "Get it" downloads it through the normal checks; when you
  save it, it replaces the old track: same crates, the old file to the Trash.

## 0.9.5 (2026-11-10) — Queue: details in place

- **Queue is list + details:** click a track and its details (BPM, key, spectrogram, every check, CLUB-READY,
  Download / Delete) open beside the list, in the Queue tab. No separate Review screen to jump to.
- Queue rows: tighter, the status as a coloured pill (GOOD / LOOK / BROKEN / DOWN / CHECK), CLUB ✓/✗ next to the
  bitrate, and the open track highlighted.

## 0.9.4 (2026-11-10) — redesign, round one (includes 0.9.3, which never shipped)

- **Discover ("record shop"):** records without art get a typographic label sleeve in brand colours (label,
  catalogue number, title) instead of a grey disc; hovering a cover shows ▶ (click: its card opens and the drop
  plays); the playing track shows animated level bars on its cover.
- **Player bar in three parts:** cover and track | play/stop over the scrubber with time either side | volume.
- **Library ("pro booth"):** tighter rows, numbers in IBM Plex Mono, and a verdict pill per track
  (GOOD / LOOK / BROKEN, plus CLUB when it's club-ready).
- Test fix: the smooth-scroll test waits for the glide to settle (it failed falsely on slow CI machines).

## 0.9.3 (2026-11-10) — smooth meter, Dig the crate, dance only (stricter)

- **Level meter rebuilt:** reads the track's real loudness (left and right, every 20 ms) instead of the spectrogram
  picture, glides between the player's position reports, redraws at 60 fps, rises instantly, falls smoothly, with a
  peak marker that hangs then floats down and partly-lit top segments.
- **Dig the crate** (was Spin the crate): says what it is ("a random track from today's labels and styles, ready to
  hear"), and **Dig again** shows the next track and plays it straight away.
- **Dance and electronic only, stricter:** an artist Deezer doesn't know now needs a dance word in the path (house,
  techno, disco, garage, acid, club, edit, remix, dub, 12"…); label rows need the label's name with "Records"/
  "Recordings" or a catalogue number (so "Prelude" isn't Bach); more non-dance words blocked (classical, orchestra,
  acoustic, blues, singer-songwriter, Christmas, hip hop…). Rows and ready tracks from before are discarded.
- Release page: the Windows installer (Setup.exe) is attached next to the macOS .dmg.

## 0.9.2 (2026-11-09) — Discover: dance and electronic music only

- Network searches match words anywhere in a path, so "Chicago house" also found e.g. a metal band's
  "Live in Chicago / House of Blues". Now, for every row:
  - the label or style must appear as a phrase inside ONE folder or file name ("Disco edits" counts for Disco edit);
  - paths that say metal, rock, punk, grunge, country, folk, soundtrack… are left out;
  - each artist's genres are checked on Deezer (their top releases; remembered 90 days): no dance/electronic
    genre (Dance, Electro, Techno/House, Disco, Soul & Funk) means out. Unknown artists stay if they passed the above.
- Discover's own search ("See everything") applies the path check too. The Search tab is unchanged.
- Rows and ready spins cached by 0.9.1 are discarded so nothing from before the fix shows. "Z Records" left the
  label pool (its name alone matches almost anything).

## 0.9.1 (2026-11-09) — Discover, tightened

- **Labels and Styles are separate sections,** each with its own heading.
- **Rows:** ‹ › buttons (smooth) instead of a scrollbar; trackpad swipes still work; grey placeholder tiles while a
  row loads; long titles end in "…" instead of being cut off; tighter tiles.
- **Bug fix:** the mouse wheel over a row scrolled the row sideways instead of the page.
- **Spin is quicker:** 3 kept ready, a slow source is skipped after 20 s instead of a minute, and ready spins are
  kept between sessions, so the first spin after opening DigMart is instant.

## 0.9.0 (2026-11-09) — Discover: daily labels, styles, a Spin that always plays

- **8 label rows a day,** rotating through 68 labels across every era (Chicago, NY/NJ, Detroit, UK/Europe, France,
  2010s, disco), Label of the day first. Era chips still show an era's labels.
- **Style rows** mixed in: Deep house, Acid house, Chicago house, Garage house, Disco edit, Tech house.
  "Artists you play" removed.
- **Spin the crate always plays:** it picks from every row on the page, loads the preview in the background and only
  shows a track once its preview came through; ▶ plays it instantly. Two are kept ready. A preview you start
  yourself always takes priority over this background loading.
- **Covers:** anything Discogs can't match gets its cover from Deezer.
- **Fix:** Deezer stopped answering artist:/track: searches, so its covers, labels and years were silently missing
  from library lookups too. Plain searches now.

## 0.8.9 (2026-11-09) — Discover as crate rows, much faster

- **Crate rows:** Label of the day on top, then one row per label (era chips choose which), each a sideways strip
  of tracks people are sharing right now, with real label art from Discogs. "See everything" searches the label
  inside Discover. Artists you play stays at the bottom.
- **About 10x faster:** one network search per label fills a whole row (instead of one search per record), and
  rows are remembered for 3 hours, so Discover reopens instantly.
- **Spin the crate is a slim bar:** it picks from the rows already loaded, so ↻ is instant.
- **Tap a track:** its card (Play the drop, Check this file, Watch it, More from this label) opens right under that
  row. Tap again to close; tap another to switch.

## 0.8.8 (2026-11-09) — back to the Discover layout, with previews

- **The 0.8.5 layout is back** (Spin the crate, Today's dig, eras, labels) and 0.8.6's shelf is gone: no more
  downloading whole tracks ahead. On start-up, anything 0.8.6 was still fetching for it is cancelled and what it
  left in quarantine is deleted (nothing in the library is touched).
- **Previews, not downloads:** Play the drop fetches only the ~20 s it plays. Check this file downloads that exact
  copy and confirms the real quality and club-ready.
- **Faster:** the record's own title is searched first (no Discogs call), searches stop sooner, and "who's sharing
  it" is remembered for 3 hours (misses too), so reopening Discover is instant. Only copies decks can load are offered.
- **Today's dig opens in place:** tap a cover and its card opens right under that row; tap again to close, tap another
  to switch.

## 0.8.7 (2026-11-09) — shelf details open in place

- Click a track on Discover's shelf: its details open right under that row (bigger cover, format, length, BPM,
  key, the full club-ready results, Play from the drop / Add to library / Not for me). Click it again: closed.
  Click another: that one opens instead. No separate player further down the page.

## 0.8.6 (2026-11-09) — Discover is a shelf of ready-to-take tracks

- **Everything on Discover can be taken right now:** DigMart digs ahead in the background (records from the
  chosen era's labels that someone is sharing), downloads each into quarantine and runs the full check. Only
  tracks that are Good AND club-ready go on the shelf; the rest are deleted automatically.
- On the shelf: ▶ plays it from the drop (it's already here, no waiting), Add to library is instant, ✕ deletes it.
- Era chips choose what it digs (Everything, Chicago jack, Acid, … Tech & bass house).
- Bounded: about 12 tracks on the shelf, 2 downloads at a time, searches from the shared budget; dug tracks stay
  out of the Queue and expire with the normal quarantine retention if not taken.
- The catalogue pages, Spin card and Today's dig are gone from Discover (you couldn't download from them directly).

## 0.8.5 (2026-11-09) — Discover only shows what you can actually get

- **Only records someone is sharing right now:** Spin the crate and Today's dig search the network for each record
  (its A-side, then the next track) before showing it, and keep it only with a copy that's the right track,
  lossless or 320, free to send now, and not already in your library. Polite: one search at a time from the
  shared search budget; label and artist pages stay instant.
- **Play the drop instead of YouTube:** about 20 seconds from the drop, straight from the person sharing it (no
  ads, no buffering a video, nothing kept). A busy source falls through to the next ready copy.
- **Check this file** on the card downloads that exact copy; no second search. Clicking a dig cover opens its card
  right under the covers.
- **Club-ready check for the whole library:** tracks checked before 0.8.3 get it in the background on start-up
  (files are only read, never changed).

## 0.8.4 (2026-11-09) — search inside Discover, club-ready copy, a stricter club check

- **Search inside Discover:** clicking a record (Today's dig, a label or artist page, Spin's Search for it) or
  typing in Discover's search box finds it right there, with Preview and Check this file. Back returns to exactly
  where you were. The Search tab keeps its own results.
- **Discover is every era:** new crates for the 2000s (deep & soulful), 2010s (lo-fi & outsider) and tech & bass
  house; essential labels from Trax and Strictly Rhythm to Defected, Dirtybird, L.I.E.S. and Rhythm Section.
- **Make a club-ready copy** (Library details and the review page) for files the decks can't load, or older decks
  can't: AIFF, 24-bit (16 when the source is 16), 44.1/48 kHz. Each copy is proved against the original (decoded
  length within 20 ms, loudness within 0.2 LU, peaks not raised, audio match >= 0.995) then checked like a new
  file. Any failure: no copy, and the reason. The original is never changed.
- **Club check, tightened against real files** (a run over the user's own library found false alarms on loops and
  one-shots): loudness and low end only judged on files over 90 s; "-70 LUFS" (unmeasurable) no longer reported;
  mono judged by the dB actually lost when summed, and bass only when there is bass; clipping needs sustained
  full-scale hits; true-peak note from +2 dBTP; 88.2/96 kHz is a note (older CDJs play only 44.1/48).

## 0.8.3 (2026-11-09) — club-ready check, Spin the crate

- **Club-ready check** on every checked track, shown under the verdict as CLUB-READY ✓ / NOT CLUB-READY ✗:
  decks can load it (CDJs/Rekordbox: no 32-bit float, nothing over 96 kHz, no OGG/WMA), mono-safe (bass that
  cancels when a rig sums to mono), clipping and true peak, loudness (LUFS), low end present, artwork size for
  USB. The Good / Have a look / Broken verdict is unchanged. Tracks checked before 0.8.3 get it on Check again.
- **Spin the crate** on Discover: a random record from the classic labels (original era first) with its cover,
  label, year, cat #, style and tracklist. Listen plays the clip Discogs lists for it; Search for it / Watch it /
  Open the label; Spin again is instant (the next one is fetched in the background).
- M4A taken out of the file-type filter. Discogs lookups back off longer when busy; Today's dig retries itself.

## 0.8.2 (2026-11-09) — Discover, filled in

- **Discover:** Today's dig (a wall of record covers from a different classic label each day, click to search),
  Essential labels, Era crates and Artists you play. "Dig your labels" and "Mixes with your new tracks" removed.
  Cards stretch to fill each row; pages use up to 1600 px instead of stopping at 1180.
- **Search filters:** a File type drop-down (MP3, FLAC, WAV, AIFF, M4A) plus Lossless, 320 only, Ready now and
  Show private. The Mix filter is gone (file names don't say the mix reliably).
- **No more junk labels:** download sites and placeholders in the label tag ("DJDownloadMe.com", "www…", "Promo
  Only", "320kbps", "Not On Label") are ignored everywhere, and never written back into tags.

## 0.8.1 (2026-11-09) — headphones

- **Sound follows your headphones:** playback now moves to whatever the system's output is (headphones plugged
  in, AirPods connected, an interface picked in the OS). It used to stay on the speakers it started with.
- Discover: "*" name-variation marks cleaned from credits joined with "And".

## 0.8.0 (2026-11-09) — Discover

- **Discover is the new home page:** search, what's waiting for you, Era crates (Chicago jack, Acid, Detroit deep,
  NY & Jersey garage, Ghetto house, Deep '90s, French filter, Disco roots; a starter set in app/core/eras.py),
  Dig your labels, Artists you play, and Mixes with your new tracks (key + tempo, from your own library).
- **Label and artist pages** from MusicBrainz + Discogs (no account): history, parent/sub-labels or aliases/groups,
  the whole catalogue by year with label art, what you own ticked; Search for it / Watch it / open artist or label.
  Polite (MB 1/s, Discogs 1 per 2.5 s, retries when busy) and cached for a week, so it works offline after.
- **Queue replaces Home and Ready:** downloading, checking and review live in one tab.

## 0.7.4 (2026-11-09) — Library fixes

- **Library tracks open again.** After the first track opened, later clicks crashed: a scrolling flag had the same
  name as the Show-in-folder action and overwrote it. Renamed; a test now opens every track twice over.
- **Selected row is readable:** solid DigMart crimson, a shade darker, with white text (light and dark), instead
  of white text on pale pink.
- **No more empty gap in the details panel:** it was measured at the wrong width before opening; now it fits its
  content. The panel itself is neutral (panel colour, crimson edge) rather than pink.

## 0.7.3 (2026-11-09) — the rest of the 1.0 roadmap that doesn't need a business decision

- **BPM/key from tags (#5):** if a file already carries BPM/key (Rekordbox, Traktor, the label), that is shown and
  marked "from tags"; our measurement is kept beside it. Reads classic (Am, F#maj), Camelot (8A) and Open Key (1m).
- **Source reputation (#6):** what each source has really done for you (delivered / failed / came out Broken,
  speed from request to arrival), worked out from the job history. New narrow, last "Source" column on search
  (✓4, ✓1 ✗1, hover for the sentence). Used as a ranking tie-breaker; a source that never delivered and failed
  twice sinks to the bottom.
- **Send a report (#9):** Settings → Advanced → Send a report… zips app.log + engine.log + settings + your note,
  with passwords, keys and tokens left out, and opens its folder to attach to an email.
- **Windows installer (#3):** CI now builds `DigMart-<version>-Setup.exe` (Inno Setup), installs it silently,
  self-tests the installed app and uninstalls it. Per-user install (no admin prompt) so the updater can still
  swap the app folder; Start-menu entry, optional desktop shortcut, uninstaller. Unsigned until the certificate.
- CI fixes: the macOS test runner's FFmpeg has no Vorbis encoder (test now uses AAC); two batch-page tests left
  parentless widgets for Qt to tear down at exit, which crashed the Windows test run after all tests passed.

## 0.7.0 (2026-11-07) — one master copy: Reyes's 0.6.0 + Chris's beta work + Windows fixes

(Numbered 0.7.0 so it reads as newer than both 0.6.x lines: Chris's Pied Piper beta went to 0.6.5,
Reyes's DigMart was 0.6.0.)

Built on Reyes's DigMart 0.6.0 (his design and features unchanged), with what Chris's `beta` branch had
that 0.6.0 didn't (0.5.9 to 0.6.5 came after the 0.5.8 handoff), and a Windows pass.

- **Wishlist** (sidebar): standing searches. "Watch this search" on Search, or the Artist / Title / Mix form
  on the page. Asked for again every 20–30 min for 30 days; the first copy that passes the quality bar is
  pulled into quarantine and checked like any other file; Good / Have a look → it waits on Ready and the
  sidebar shows a count. Broken → the next candidate. Nothing is ever kept automatically. Whole playlists
  stay on Batch.
- **One search budget** for Search, Batch and the Wishlist, so together they can't trip the network's rate
  limit. The Wishlist never searches while you search or a batch runs.
- **Search:** click a column heading to sort (again to flip; # back to fastest first). Rate groups each
  lossless format together, so all the WAVs sit in one block.
- **Already have it?** A result that matches your library or queue shows a note; the button needs a second
  click ("Check it anyway").
- **Silent pre-checks** before the decode: programs, archives, PDFs, images or web pages with an audio name,
  files too small to be a track, and sizes that can't fit the length stop at once with the reason.
- **Engine watchdog:** if the engine dies it's started again (status: Reconnecting…), no app restart.
- **Volume** slider in the now-playing bar, remembered between sessions.
- **Fits a laptop screen.** The window could never be shorter than the 896 px sign-up screen, even after
  sign-up, so on a 768 px laptop Download / Delete fell off the bottom. Screens now size to the page showing;
  the tallest (Home) needs 597 px. On Ready the details scroll and the verdict + buttons stay pinned.
- **Ready:** the verdict (Good / Have a look / Broken) sits right above Download / Delete instead of a corner;
  wider list so names show; the LEVEL meter appears only while a track plays; the list highlights the track
  you opened (it lagged one behind).
- **Search:** Check this file / Preview sit just above the results instead of the bottom of the page; the
  wait column is coloured (green ready, amber a wait, red hours); user names have room; the note wraps.
- **Home:** Good / Have a look / Broken cards with a coloured edge; no full bar on finished tracks; long
  titles clip instead of pushing the row wider (that was the stray scrollbar and the cut-off bitrate).
- **No grain texture** behind the pages (it made text harder to read); plain off-white in light, black in dark.
- Gentler wheel scrolling (the 0.5.9 change that missed the handoff).
- **Fix: text painted over text on Ready.** Switching tracks left the previous track's check lines drawn under
  the new ones (also the Home queue, the Ready list and Library details): rows are now hidden the moment
  they're removed (the Pied Piper 0.5.10 fix that missed the handoff).
- Fixes: the review page no longer widens for a frame on every refresh; wrapped text never gets clipped;
  "Sharing your library" light only on the first start; a router that won't open the port is a dash, not
  a red cross; the self-test plays its audio probe muted.
- **Windows:**
  - The player opens the sound device on the first play, not at start-up: with no output device (remote
    desktop, an unplugged audio interface) the app used to crash on launch.
  - Auto-update swap: runs from outside the app folder (Windows can't rename a folder a process is
    standing in), unpacks the update beside the app (PowerShell can't move folders across drives),
    retries the rename for 30 s while Windows/Defender let go of files, always reopens an app (new or old),
    and logs to `update.log`.
  - Batch playlist folders keep slashes as part of the name ("Late night / sunrise" was saved as "sunrise").
  - "Recycle Bin" instead of "Trash" in Library messages on Windows.

## 0.6.0 (2026-11-07)

- **New look:** sidebar navigation (Home, Search, Ready, Library, Batch), light and dark.
- **BPM, key and the drop:** measured from the audio during the check. Key shown in Camelot (8A) and
  classic notation; "Preview the drop" plays 20 seconds starting 2 s before the first big drop (or the
  liveliest stretch when there isn't one). The drop is marked on the spectrogram.
- **Cover art and details:** the file's own tags first, then Deezer, MusicBrainz/Cover Art Archive and
  iTunes fill the gaps (artist + title only are sent; weak matches are ignored).
- **Rekordbox-ready tags** on Download to Library: title with mix, artist, album, label, genre, year,
  BPM, key, comment, embedded cover. Existing tags are never overwritten.
- **Search:** filters (Lossless, MP3 320, Ready now, mix kind, show private) and plain-English
  availability: Ready now · ~30 sec, Short wait · few min, Long wait · 10+ min, Very long wait, Busy.
- **Library:** BPM and Key columns, BPM range and "mixes with" (Camelot-compatible) filters, cover and
  drop preview in the drop-down; no more jumping to the review page.
- **Ready list:** saved or deleted tracks leave by themselves; the next waiting track opens.
- **Batch:** paste a YouTube / SoundCloud / Spotify / Apple Music playlist link or a list, or pick a
  folder of files to upgrade; one spaced search per track; download and check all picks.
- **Auto save:** reopens where you left off (page, selection, search + filters, batch list, window).
- **Updater:** signed updates (Ed25519), verified downloads, install on restart, old copy kept until
  the new one starts. Off until the download location is set.

## Unreleased


- Account backend on the website (sign-up, sign-in, license check); the in-app screens already exist.
- Plan & billing: the account page shows the section; nothing is stored or charged yet.
- App icon (window, taskbar, exe).
- Installer with code signing and a Windows Firewall rule named after the app, so the first-launch
  firewall prompt disappears (see `docs/DECISIONS_AND_FLAGS.md`, D15).
- macOS build with the bundled engine.
- Support / FAQ page on the website (the Help button already points at `SUPPORT_URL`).
- "Find it to buy" store search (Beatport, Bandcamp, Juno, Traxsource, Discogs); the code is kept, no button.

## 0.5.5 — unreleased (search load)

Searches got slow by the third query of a session. Each query was sending four engine searches, and
earlier queries' searches stayed live in the engine until a periodic clean-up; the network throttles
accounts that search that often, and the engine was carrying every past search's results in memory.
- Two engine searches per query (5 s and 40 s) instead of four, spaced 1.5 s apart; fallback is one.
- A new query first removes the previous query's searches from the engine, finished or not.
- Per-rung timing (rows, users, seconds to finish) goes to `app.log` so slow sessions can be read.

## 0.5.8 — unreleased (no more jumping lists)

- The "elements skip" after an action: three lists were rebuilt from scratch on every poll tick and
  reset their scroll to the top — the Ready rail (every 1–2 s, whether or not anything changed), the
  queue list, and the Library (which also re-opened its drop-down with the slide animation and scrolled
  the clicked row to the top). Now: the rail rebuilds only when its rows actually change (a selection
  change just moves the highlight), every rebuild keeps the scroll position, the Library keeps its
  position and re-mounts the open panel without animating, and opening a panel no longer scrolls the
  list — it only brings the panel into view if it's off-screen.
- 0.5.7 search numbers logged in `docs/SEARCH_TEST_CASES.md`: every "none found" name now returns
  thousands of rows in 6–8 s.

## 0.5.7 — unreleased

- Tighter timings: a search can be stopped from 3 s (was 4) after 2.5 s of quiet (was 3), so popular
  names land around 5 s; the budget is a burst of 4 then one search per 6 s on average (was 3 / 8 s).
  Back off if a log shows the network going dark again.

## 0.5.6 — unreleased (one search per query; the slowdown, explained)

The 0.5.3 log showed it plainly: after ~16 network searches in three minutes, five queries in a row came
back empty; after seven quiet minutes the same query returned 1,427 rows. The network rate-limits
accounts that search often, and our ladder (4, then 2 searches per query) was tripping it.
- **One network search per query**, like every other client. The engine only releases a search's rows
  once it has ended, so we watch its live counts ("29 users · 121 files so far") and **stop it ourselves
  when results dry up** (never before 4 s; after 3 s with nothing new, or under 3 % growth on a big
  result; deadline 40 s for rare names). The engine keeps everything received up to the stop.
- **Search budget**: at most a short burst, then about one search per 8 s on average. Faster than that
  and the page says "Pacing… next search in N s" instead of the network silently going dark.
- Punctuation at the ends of search words is dropped ("ulo s." → "ulo s"; "a.m." kept).
- **Benchmark mode** for the 500-name list: `"Pied Piper.exe" --bench docs\search_bench_list.txt
  --limit 60` writes `bench.csv` (time to first rows, users/files at 5 s and at the end, pickable /
  locked / other-format / ad-bot) with proper pacing. `docs/SEARCH_TEST_CASES.md` tracks the cases.
- Per-search timing lines in `app.log` (stopped at / done at, users, rows).

## 0.5.5 — unreleased (search slowing down over a session)

- Searches got slow by the third or fourth query of a session: the ladder sent four network searches
  per query and the network throttles accounts that search that often. Now two per query (5 s and
  40 s), spaced 1.5 s apart, and the previous query's searches are removed from the engine before a new
  one starts. The typo fallback is one search.
- Each query's timing goes to `app.log`: rows and users per rung and seconds to first rows.

## 0.5.4 — unreleased

- macOS builds for **both chips**: `-macOS-AppleSilicon` and `-macOS-Intel` dmgs ("this application is
  not supported on this Mac" was the Apple Silicon build on an Intel machine).

## 0.5.3 — unreleased

- macOS ships as a **.dmg** (open, drag to Applications) instead of a zip; Archive Utility refused the
  zip on at least one Mac. The build mounts the image, copies the app out the way a user would, checks
  the signature survived and runs the self-test from the copy before publishing.

## 0.5.2 — unreleased (scrolling with momentum)

- Wheel scrolling now feels like a browser's: a fixed ~110 px per notch, an ease-out glide, and
  **momentum** — notches that arrive mid-glide add distance and lengthen the glide rather than
  restarting it. Stress-tested: 25 notches in a quarter second on a 20,000-row list glides forward
  monotonically and carries the distance. Trackpads keep their native behaviour.

## 0.5.1 — unreleased

- Search buttons always return to "Search" when a search ends (the error path left them stuck).
- macOS icon generated as .icns (the Mac build failed on the .ico); icon corners transparent.

## 0.5.0 — unreleased (smooth scrolling, macOS build)

- Smooth scrolling everywhere: lists scroll per pixel and wheel ticks glide (220 ms ease-out) instead
  of jumping a row at a time; ticks that land mid-glide extend it. Trackpads are left as they are.
- **macOS build** (Apple Silicon): `PiedPiper-<version>-macOS.zip` containing `Pied Piper.app` with a
  static FFmpeg and the engine bundled, ad-hoc signed so it runs on Apple Silicon. Not notarized yet:
  first open is right-click → Open (or System Settings → Privacy & Security → Open Anyway).
- 0.5 rolls up everything since 0.4.0: tour, Library with inline drop-down and player, search that
  matches other clients (ladder, locked files, ad bots greyed, typo fallback), no popups, auto-retry,
  progress, Retry download, blip, start-up marks, spectrogram cap, Pied Piper placeholder.

## 0.4.16 — unreleased (spectrogram cap)

- Library spectrograms on disk are capped at the newest 100 (~0.8 MB each → ~80 MB). Opening an older
  track in the Library redraws its picture from the library file in the background ("Drawing the
  spectrogram again…"), which then counts as newest. The grade is not recomputed — only the picture.
  Cap is `keep_spectrograms` in settings (floor 10).

## 0.4.15 — unreleased (a little give in search; inline library drop-down)

- **Zero results → one retry without the shakiest word.** The network matches every typed word as a
  plain substring of the filename, so a typo ("dace it out") or a tense ("danced") finds nothing. When a
  search comes back empty, the app re-runs it once without the word most likely to be the mistake (not a
  common word, not seen in any result or library name before; shortest wins) and says so in the header:
  *Nothing matched "dace it out chris gooding" — showing results for "it out chris gooding" (without "dace")*.
  One extra search, only on a miss.
- On that fallback, rows whose names contain a near-miss of the dropped word ("Dance" for "dace") are
  ranked first within the same availability band — fastest sources still bubble to the top.
- **Library drop-down opens inline, under the clicked row**, full width, sliding open, and scrolls with
  the list. Click the row again or Close to fold it. Rebuilt fresh each time it opens.

## 0.4.14 — unreleased (the time-outs, named)

The 0.4.11 engine log settles the time-outs: every one of them was a request to the "user"
`https://www.rawzik.com` — a shop's advertising account that answers every search with its catalogue
and never sends a byte (the engine tried each one 3 times, 15 s apart). Every download from a real
user went through at 3–12 MB/s, and the port was open. So:
- Sources whose name looks like a web address are tagged **"Ad bot"**, greyed, sorted last and can't
  be requested; the header counts them.
- Our own automatic retries drop to 2 (15 s, 45 s) since the engine already makes 3 attempts per request.
- The router/port result is written to `app.log` at start-up.

## 0.4.13 — unreleased

- **Fixed:** after the first Download to Library, every later track's Download / Delete button stayed
  greyed (introduced in 0.4.2 when those actions moved off the UI thread; the buttons were disabled for
  the copy and never re-enabled). There is no reason to pace downloads; they run back to back. A test
  now clicks Download on one track and checks the next track's button is usable.

## 0.4.12 — unreleased (downloads that time out)

- **"Completed, TimedOut" downloads.** The engine gave a source 30 s to get the transfer going before
  giving up; peers behind firewalls often need longer. Engine timeouts raised (connect 15 s, inactivity
  60 s, transfer 120 s), and a timed-out download is now **retried automatically** up to 3 times
  (10 s, 30 s, 60 s apart) with the row saying "No answer from the source. Retrying in 30 s (2 of 3)…"
  before it's marked failed.
- Review page for a track still downloading shows a progress bar with percentage and a plain-English
  line (in line at the source / receiving the file…).
- A failed download's review page offers **Retry download** (asks the same source again, right now)
  instead of Re-check, which only re-runs the checks on a file that has arrived.
- Re-check now shows at once: the verdict flips to CHECK with moving dots and the button reads
  "Re-checking…" until the result lands.
- A queue row blips green for a moment when its track moves to the next stage (downloaded → checking,
  checking → verdict).
- Start-up screen lights are real marks now (● busy, ✓ done, ✕ failed, – skipped).
- "Open Archive" → "Open Pied Piper" (follows the app name).
- The player's pause glyph is drawn, not a font character, so the bars sit together.

## 0.4.11 — unreleased (the flashing windows, found)

### Fixed: blank windows flashing while tracks are added or change state
`app.log` named them: `QWidget 22x480`, `QProgressBar 150x3`, `QPushButton#x 18x18` — the three parts of a
queue row (the × spacer, the progress bar, the ×) were made visible *before* being placed in the row,
so each was its own top-level window for a frame, every time a row was built or rebuilt. They are now
parented first. A test drives the real window through every flow that used to flash and fails if any
widget is ever shown as a stray window (it reproduced the exact list from the log before the fix).

- Library drop-down no longer closes on its own: the page re-read and rebuilt its list on every poll,
  which dropped the selection. It now rebuilds only when the library actually changed, and keeps the
  open row selected across rebuilds.

## 0.4.10 — unreleased (results fill top-down)

- One query now runs a ladder of engine searches (4 s, 10 s, 22 s, 40 s). Each one's rows join the
  list the moment it ends, so results populate top-down while the longer ones keep collecting; the
  engine's live counts are also read from the running searches whenever it offers them.
- The last row of the list says what's happening: "Finding more… · 29 users · 121 files so far" with
  moving dots while the search runs, then "All results shown · 121 files" when it's over. The "Load
  more" row says whether the search is still running.
- Header counts are "N results" (files); user counts live in the footer.

## 0.4.9 — unreleased (THE search fix)

### Fixed: searches showed nothing although the engine had results
Root cause, from the 0.4.8 logs: the engine does not hand out a search's responses until that search
has **finished** — while it runs, `/searches/{id}/responses` is `[]` even as the search record's
response count climbs. Our search timeout and our own polling cap were the same number (15 s in
0.3.x, 45 s in 0.4.x), so the app gave up a few seconds before the engine finished and never asked
again. Big artists worked in early builds only because the engine happened to finish first.

Now every query runs **two** engine searches: a quick one (6 s) whose results land as soon as it ends,
and a long one (40 s) for the slow and far-away sources; when the long one finishes its results replace
the list (quick rows kept). While waiting, the page shows the live count from the engine ("29 sources
· 121 files so far"). The fake engine used by the tests now behaves the same way, so this can't slip
through again.

- Locked files (shared only with the peer's own list) appear greyed as "Locked".
- The exe icon is written with classic bitmap entries (plus PNG at 256), which the taskbar and
  Explorer render reliably; the build log confirms the icon was embedded.

## 0.4.8 — unreleased (search diagnostics, locked files, exe icon)

- Search results now include files the peer has **locked** (shared only with their own list), greyed
  with "Locked" — for "volpat" that was 63 of the 121 files the engine received, so the count now
  matches other clients. They can't be requested.
- The engine was receiving results (29 responses for "volpat", 999 for "john summit") that the app
  showed as none. The whole search path now writes to `app.log` — POST, every poll (count, state),
  every HTTP status and payload size, and the full traceback if anything fails — and a failed search
  shows its real reason in the results area instead of a generic line.
- Task failures (background work) are also written to `app.log`.
- The exe carries the "pp" icon (taskbar, shortcuts, Explorer); the window registers its own app id
  so Windows groups it under that icon.

## 0.4.7 — unreleased

- Mark is now the "pp" monogram tile (top-left and window/taskbar icon), replacing the pipe.

## 0.4.6 — unreleased (Pied Piper placeholder, search feedback, start-up lights)

- Placeholder name is now **Pied Piper** (one constant; DEADWAX and Project Archive installs migrate:
  data folder, keyring, engine name, and an existing `DEADWAX` downloads folder keeps being used).
  Teal accent in both themes; an original pipe mark top-left and as the window/taskbar icon.
- Search feedback: pressing Search clears the old rows at once, the header says *Searching for "…"*,
  the empty area cycles through moving phrases ("Asking around…", "Knocking on doors…", "Still
  looking…") and both Search buttons read "Searching…" until it's done. A new search cancels the old
  one's late results.
- Start-up screen lights each step as it happens (engine → sign-in → router port → sharing), with a
  note on the port line saying whether the router opened it.
- Settings → Advanced → **Start fresh…** wipes this computer's account, queue, history, quarantine and
  logs (not your music, not the Soulseek login) and closes the app.
- "Ready" / "Library" tab labels no longer clip their descenders.

## 0.4.5 — unreleased (more search results)

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
