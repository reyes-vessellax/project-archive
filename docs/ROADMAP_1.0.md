# Road to 1.0 — agreed 2026-11-05

Order is roughly the order to build. Each item says what "done" looks like.

## 1. Already-have-it check (subtle)
Before a request goes out, look for the same track in the library and the queue: same hash, or same
parsed artist+title (fuzzy, ignoring mix words), or the same remote file. If found, the **Check this
file** button turns grey with a one-line note under it — *"You may already have this: Dance It Out · 320
· June"* — and a **second click** sends it anyway. No dialog. Same note on the queue row.

## 2. Wishlist (standing searches)
- "Watch this search" from the Search page: the query is saved and re-run on a slow cadence
  (every 20–30 min, jittered; the network punishes chatty clients), plus on app start.
- **Quality gate** for a match, all of which must hold: every query word present; accepted format;
  not an ad bot; not locked; size plausible for its length and bitrate; bitrate ≥ the user's floor
  (or lossless); source has a free slot or a short queue; not a duplicate of something already in the
  library or queue; parsed title within a typo of the wished title; no "remix/edit/bootleg" words
  unless the wish had them.
- The best match is downloaded and **checked automatically**. If the check says Broken, the next
  candidate is tried (up to 3). Only a Good/Have-a-look result reaches the user.
- A bell in the top bar with a small count; clicking it lists the matches, each one already waiting
  on the Ready tab for yes/no. No OS notifications or email yet.

## 3. Auto-update
**Status:** Installer: done in 0.7.3 (per-user, Inno Setup). Updater: built, switched on when the repo goes public.
Installer first (Inno Setup, Program Files, Start-menu entry, uninstaller). Then on start the app
reads a small version file from the release feed; if newer, downloads the installer in the background
and offers "Update and restart". Code signing is the business-side prerequisite (flag: certificate is
issued to the legal entity).

## 4. Network status + smoother intro
- Status dot follows the engine live: Connected / Reconnecting… / Offline. Engine death or a dropped
  network reconnects on its own; no restart needed. Test by pulling the cable.
- The sign-up → "Getting things ready" → tour sequence gets proper transitions (cross-fades, no jumps
  in layout, lights that settle in order).

## 5. BPM and key
**Status:** Done (0.7.0–0.7.3), including tags shown "from tags".
Scale: two to three days, in-house, no new heavy dependencies.
- We already decode every track to mono float32 for the spectrum; BPM comes from an onset envelope +
  autocorrelation over that same audio (with half/double-time disambiguation for 4/4 dance music),
  key from a chroma profile matched against major/minor templates, reported in Camelot (8A) and
  musical (A minor) notation. Adds ~1–2 s per track.
- Validation: the user's own library carries Rekordbox BPM/key in its tags — the checker compares
  against those and reports accuracy before we trust it. Target: BPM within 1 on ≥95 %, key exact or
  relative on ≥80 % of club tracks.
- Library columns become Title · Artist · BPM · Key; everything else lives in the drop-down.
- If the file already carries BPM/key tags, show those and mark them "from tags".

## 6. Source reputation
**Status:** Done in 0.7.3.
Per-user memory: deliveries, failures, average speed. Shown as a right-most "Source" column on results
(off by default-ish: narrow, last), and used as a tie-breaker in ranking. Ad bots and never-delivers
sink.

## 7. Silent pre-checks
Before the spectrum step, a quick pass with no UI of its own but with the progress bar moving:
magic bytes vs extension, archive/executable detection, size vs duration sanity, tag header sanity,
truncated-file check. A failure short-circuits to Broken with the reason.

## 8. Accounts backend (approaching beta)
Hosted accounts so the same login works on any machine: a small API (auth, profile, plan, device
list) with the local account becoming a cached copy. Billing UI stays inert until the provider is
chosen. **Flag — attorney:** terms of service, privacy policy, data residency for user emails.

## 9. Send a report
**Status:** Done in 0.7.3 (local zip; upload waits for the backend).
Settings → "Send a report": zips app.log + engine.log (+ optional note) and uploads to the backend.
Until the backend exists, it just gathers the zip for the user to send.

## 10. Installer, signing, macOS, EULA
Known; see DECISIONS_AND_FLAGS.md for the attorney flags.
