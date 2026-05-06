# Electro-Price — Design

**Date:** 2026-05-06
**Status:** Approved (brainstorm phase)

## Summary

A static webpage that answers the question *"is electricity cheap right now?"* at a glance, optimized for reading on a Kindle's e-ink browser. The page renders a single filled-area chart of Nord Pool spot prices for price zone SE4 (Malmö), covering the last 6 hours plus the next 18 hours at 15-minute granularity. The page is regenerated hourly by a GitHub Actions cron job and served from GitHub Pages. No client-side JavaScript is required to view the chart.

## User and Use Case

- **User:** the project owner, living in Malmö (price zone SE4).
- **Device:** the Kindle Experimental Browser (old WebKit, grayscale e-ink, slow refresh, limited JS).
- **Decision the page supports:** *"Should I run the laundry machine now, or wait?"*

The design is single-user and read-only. There are no accounts, no preferences, no settings.

## Scope

**In scope:**

- Fetch Nord Pool spot prices for SE4 from elprisetjustnu.se.
- Render a single static HTML page with the visual locked in v3 (see "Visual Design").
- Publish the page to GitHub Pages via a scheduled GitHub Actions workflow.
- Auto-refresh the page in the Kindle browser every 60 minutes.

**Out of scope (YAGNI):**

- Historical archive (no past-day storage beyond what the API serves directly).
- Multi-zone support (SE4 is hardcoded).
- Spot-plus-VAT, all-in pricing, or currency unit toggles. Only raw spot in öre/kWh.
- Notifications, alerts, push, email.
- Any client-side JavaScript for data, interactivity, or framework-driven UI.
- PWA, service worker, offline mode.
- Analytics or telemetry.
- Styling for non-Kindle devices beyond "doesn't actively look broken".

## Architecture

```
GitHub Actions (cron)  ─►  build.py
                              │
                              ├─ fetch elprisetjustnu.se (today + tomorrow)
                              │
                              ├─ derive: now-slot, last-6h..+18h window,
                              │   cheapest upcoming slot, 24h average
                              │
                              └─ render index.html (inline SVG, inline CSS,
                                 no JS) ──►  GitHub Pages artifact deploy
                                                         │
                                                         ▼
                                          Kindle browser → Pages CDN
```

- One Python script (stdlib only — `urllib.request`, `json`, `datetime`, `zoneinfo`).
- Output is a single self-contained `index.html`. No external assets, no fonts, no JS for data.
- Build-time-rendered: the page already says "JUST NU 80 öre, Uppdaterad 14:02" when the Kindle loads it.
- Publishing uses `actions/upload-pages-artifact` and `actions/deploy-pages` so the workflow does not commit generated HTML to any branch — Pages serves the artifact directly.

## Data Source

- **API:** `https://www.elprisetjustnu.se/api/v1/prices/<YYYY>/<MM-DD>_SE4.json`
- **Auth:** none.
- **Returns:** array of slots, each containing `SEK_per_kWh`, `EUR_per_kWh`, `EXR`, `time_start`, `time_end`.
- **Granularity:** 15-minute slots (96/day on standard days; 92 on spring-DST day, 100 on autumn-DST day). Script must iterate over what the API returns rather than assume a fixed slot count.
- **Tomorrow's data:** publishes around 13:00 Europe/Stockholm. Before that, the tomorrow URL returns 404.
- **Build performs two requests:** today, and tomorrow (404 tolerated).

## Time Windowing

- **Display window:** the slot containing `now − 6h` through the slot containing `now + 18h` (Europe/Stockholm).
- **"Now" slot:** the slot satisfying `time_start <= now < time_end`.
- **DST correctness:** trust the API's `time_start` ISO-8601 timestamps with offsets. Do not infer slot times by index from midnight.
- **Cheapest upcoming slot:** minimum `SEK_per_kWh` across slots whose `time_start > now` and which fall inside the display window.
- **24h average:** mean `SEK_per_kWh` across all slots in the display window.

Prices are stored internally in öre/kWh = `SEK_per_kWh × 100`, rounded to integer for display.

## Visual Design (locked, v3)

The visual was iterated over three rounds in the brainstorm session and locked at v3. Reference the v3 mockup in the brainstorm artifacts (`/.superpowers/brainstorm/.../graph-layout-v3.html`).

**Header row** (above a 1px black hairline):

- Left: `JUST NU` (small uppercase) above `80` (44–52 px, 800 weight) and a smaller `öre/kWh` suffix.
- Right: `Uppdaterad 14:02` (the `14:02` is bold, 18 px) and below it `Tisdag 6 maj` in Swedish.

**Chart** (single SVG, viewBox 720×260):

- Filled-area shape, fill `#cfcfcf`, stroke black `1.5px`.
- 24-hour rolling window: NU positioned at 25% from the left (so 6h of history is visible on the left, 18h of forecast on the right).
- NU marker: solid black dot, radius 7, with `NU · <price>` label to its right.
- Cheapest upcoming slot: small black dot, with `↑ billigast <price> öre (kl HH)` label above.
- Baseline at the bottom (`y = 0` of the data).
- Y-axis hint: max value top-left, `0` bottom-left.
- X-axis ticks every 6h with hour labels; the NU tick is bold and reads `HH (NU)`.
- Two zone labels below the axis: `SENASTE 6 H` (left) and `KOMMANDE 18 H` (right).

**Footer row** (above a 1px hairline):

- Left: `Vänta till kl HH för billigaste pris (XX öre/kWh)` — or, if NU is itself the cheapest upcoming slot, `Billigast just nu`.
- Right: `Snitt 24h: XX öre`.

**Page-level:**

- `<meta http-equiv="refresh" content="3600">` so the Kindle reloads hourly when left on the page.
- Inline CSS only. No web fonts. Default serif stack: `Georgia, "Times New Roman", serif`.
- Black on white, no color anywhere.

**Language:** Swedish (matches user's locale and the source API).

## Cron Schedule

GitHub Actions cron expressions are UTC. Two cron entries on the publish workflow:

- `2 * * * *` — every hour at `:02 past`. The `:02` offset gives elprisetjustnu.se a couple of minutes of headroom for any sub-hour updates.
- `15 11 * * *` — extra trigger at 11:15 UTC (= 13:15 Stockholm summer time) to catch tomorrow's prices the moment they publish. In winter this fires at 12:15 Stockholm time, which is harmless — the run just rebuilds with the same data.

A `workflow_dispatch` trigger is also enabled so the workflow can be run manually.

## Error Handling

| Case | Behavior |
|---|---|
| Today's API request fails | Build fails (non-zero exit, GHA marks run failed → email notification). Last successful Pages deployment stays live. |
| Tomorrow's API returns 404 | Treat as "tomorrow not yet available". Build proceeds with today-only data. The display window simply ends at the last available slot, possibly shorter than 18h. |
| Tomorrow's API returns 5xx or times out | Same as 404 — treat as unavailable, proceed with today. (Tomorrow's data is best-effort.) |
| API returns hourly slots instead of 15-min | Render whatever cadence comes back. The chart x-axis is time, not slot index. |
| Negative spot price | Y-axis baseline = `min(0, observed_min_in_window)`; the area dips below the zero line when negative. |
| DST transition day | Iterate over API-provided `time_start` values; do not assume 96 slots/day. |
| Stale data (e.g., previous deploy from 2h ago because cron lagged) | No special banner. The `Uppdaterad HH:MM` timestamp tells the user when the data was fetched. |

Network requests use a 10-second timeout. One retry with a 5-second delay on transient failures (connection error, 5xx). Anything that still fails after the retry follows the table above.

## Testing

- **Unit tests** (pytest, stdlib only) for the pure-data layer:
  - Parsing the elprisetjustnu.se JSON shape.
  - Window slicing (`last 6h .. +18h` from a given "now").
  - DST-day windowing (verify 92-slot and 100-slot days both render correctly).
  - "Now slot" lookup at slot boundaries.
  - Cheapest-upcoming-slot selection (incl. tie-breaking by earliest time).
  - 24h average calculation.
  - Negative-price handling: baseline scales to include the minimum.
- **No render snapshot tests.** The published Kindle page is the source of truth for visuals.
- **CI:** `pytest` runs on every push to `main` (a separate workflow). The `publish` workflow runs the same tests before deploying — a regression cannot ship.

## Repository Structure

```
electro-price/
├── README.md
├── build.py                        # generator: fetch, transform, render
├── tests/
│   └── test_build.py               # pytest unit tests
├── .github/
│   └── workflows/
│       ├── publish.yml             # cron + build + Pages deploy
│       └── test.yml                # pytest on push/PR
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-05-06-electro-price-design.md
└── .gitignore                      # ignores .superpowers/, __pycache__, etc.
```

The HTML/SVG template lives inline inside `build.py` as a Python f-string. The template is small enough (≈80 lines) that a separate file would add friction without benefit.

## Decisions and Defaults Locked in This Spec

| Decision | Value |
|---|---|
| Price zone | SE4 (hardcoded) |
| Time zone | Europe/Stockholm |
| Currency unit | öre/kWh, integer-rounded |
| Price content | Spot only (no VAT, no grid fee, no energy tax) |
| Time horizon | last 6h .. now .. +18h, rolling |
| Granularity | whatever the API returns (target 15-min) |
| Hosting | GitHub Pages (artifact deploy, no `gh-pages` branch) |
| Build runtime | Python 3, stdlib only |
| Deps | none beyond `pytest` for tests |
| Auto-refresh | 60 min via `<meta http-equiv="refresh">` |
| Visual variant | v3 (single chart, NU at 25% from left) |

---

**End of design.** Next step: implementation plan via `superpowers:writing-plans`.
