# DigMart design system

The single source of truth for how DigMart looks and behaves. Read this before touching any screen.
The code that implements it: `app/ui/theme.py` (colours, type, every widget style), `app/ui/widgets.py`
(shared pieces: `button()`, `hover_fx()`, `scroll()`, `label()`), `app/ui/discover_page.py` (sleeves, tiles).
To see the whole app at once: `python -m tools.screens` (renders every page, light and dark, to a folder).

## The feeling

A record shop run by DJs, printed like a music magazine. Square like records, bold like a gig poster,
quiet where the music is. Not a web page, not a SaaS dashboard.

- **Editorial:** every page opens with a masthead (big title, thick rule). Sections have a rule, a big title and
  a small mono tag. Words are short and plain.
- **Records are square.** Covers, tiles and sleeves are squares with sharp corners (radius 0–3 px).
- **One standout per page.** Discover: the Dig the crate panel. Queue: the track panel. Everything else calms down.
- **It feels physical.** Buttons rise on hover, record tiles lift like a record pulled from a crate, sleeves are
  real (paper, wear, our emblem on the label).

## Brand

- Colours: black `#000000`, crimson `#DC143C`, yellow `#FFD700`, white `#FFFFFF`.
- Logo: `app/ui/brand_assets/`. **Never redraw it.** Use the files as they are; only transparency or a colour swap.
  - `digmart-logo(.png|-dark.png)`: emblem + DigMart wordmark (sidebar top-left, first-run screens).
  - `digmart-mark(.png|-dark.png)`: emblem only (empty states, small places).
  - `sleeves/*.jpg`: the eight record sleeves for tracks without cover art.
- Light mode: crimson leads (yellow text on white is unreadable). Dark mode: true black, yellow leads.

## Colour tokens (theme.py `PALETTES`)

| token | light | dark | use |
|---|---|---|---|
| bg | #f6f4ef | #000000 | page |
| panel | #fbfaf7 | #0f0f0f | cards, inputs |
| line | #e4e0d7 | #262626 | rules, borders |
| text / muted / faint | #141414 / #5f5a50 / #8a857a | #fff / #a3a3a3 / #6e6e6e | text levels |
| accent | #dc143c (crimson) | #ffd700 (yellow) | the brand colour of the theme |
| sel (+ sel_text white) | #b3102f | #a50f2d | **selected and hovered rows** (the logo's dark red) |
| pass / warn / fail | green / amber / red | | Good / Have a look / Broken, always; a sound file that isn't club-ready (out of phase, decks can't load it) is **No club** (red), never Good (`theme.grade()`) |
| disp_* | dark readout panels | | BPM / key / length boxes, hero, era panels |

Hero and era panels stay dark in both themes (`disp_bg`), with fixed brand yellow `#ffd700` and crimson `#dc143c`.

## Type

- Display: **Poppins** (800 for titles, 600–700 for names and buttons).
- Body: **Open Sans**.
- Mono: **IBM Plex Mono**, for measured values and small caps tags (letter-spacing 1.5–2 px).

| role (objectName) | size / weight | where |
|---|---|---|
| `pagetitle` | Poppins 40 / 800, -1 px | every page's masthead |
| `mast` | Poppins 44 / 800 | "The Dig." |
| `secTitle` | Poppins 28 / 800 | section heads, "N results" |
| `styleTitle` | Poppins 22 / 800 | a style row's name |
| `heroTitle` | Poppins 32 / 800 | Dig the crate title |
| `strap`, `secTag`, `tilemeta` | Plex Mono 11, tracked | small caps lines |
| `covertitle` | Poppins 14 / 700 | a tile's title |
| `fmtbadge` | Plex Mono 10 / 700 green | FLAC / WAV / MP3 320 |
| `tilesm` | Plex Mono 18 amber | BPM / Key / Length / Format readouts |

## Layout rules

- **Masthead on every page:** `pagetitle` + optional `strap` on the right + a 3 px rule (`QFrame#mastRule`).
- **Never scroll sideways.** Pages use `scroll()` (pinned to the width); long text wraps or elides with "…".
  Tables never get a horizontal bar; their columns are fixed (Title / Folder / Availability stretch).
- **No dragging that breaks layout** (column borders can't be dragged).
- **The Queue track panel fits without scrolling** at a normal laptop window (1440×860). Check with the screen kit.
- Windows fonts run ~40% wider: give rows of chips/buttons a `FlowLayout` so they wrap.
- A widget is added to its layout **before** it is shown (`setVisible(True)` on a parentless widget flashes a
  stray window). Hide with `.hide()`; never "show" loose widgets.

## Interaction

- **Buttons** come from `button(text, role)`: roles `primary` (black/yellow), `accent` (brand colour), `ghost`
  (outlined), `danger`, `chip` (filters), `heroPlay` / `heroDig` / `heroGhost` (Dig the crate).
  Every button gets `hover_fx`: a soft shadow on hover (a faint yellow glow in dark mode).
- **Record tiles** use `hover_fx(lift=True)`: they rise 3 px with the shadow.
- **Rows** (Queue, Library, Search) hover in the brand dark red `sel` with white text, the same as selected.
- **What's playing** shows a ♫ on its row (Queue and Library), whichever row is open.
- **Loading happens in the background.** No percentages, step text or "Getting…" chatter in panels; a tag says
  enough (DOWN / CHECK). Errors are said once, plainly.

## Words

- "Preview" (never "Play the drop": the 20 seconds aren't always the drop).
- "Check this file" (download into quarantine and check), "Download to Library" (keep it).
- "Watch this search" only when nothing is available to get.
- DECKS (CDJs and XDJs), not "CDJ".
- No "from a Soulseek user", no engine jargon ("InProgress", "Cancelled") on screen.

## Covers without art (`CoverArt._paint_sleeve`)

A real sleeve photo from `brand_assets/sleeves/` picked by the track, emblem on the record's label in the
centre hole. Artist (Poppins Black caps, 2 lines max, above the hole) and title (Open Sans, one line, below it)
are *printed*: dark ink multiplied into the paper, light ink slightly see-through, the sleeve's scuffs overlaid.
Dark mode leaves out yellow, tan and cream. New sleeves: 1000×1000, same layout (hole centred, top and bottom
clear for text), add the name and ink colour to `_SLEEVE_INK`.

## Before shipping a visual change

1. `python -m tools.screens` and look at every page, light and dark.
2. Check the Queue panel note in the kit's output says it fits.
3. Run the tests (`QT_QPA_PLATFORM=offscreen python -m pytest -q`); they include no-sideways-scroll,
   stray-window and fit checks.
