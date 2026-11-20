# Accessibility sweep at three widths (0.9 row D, S4), 2026-11-20

This is a report only. No code was changed, and every violation below becomes a fix row of its own. It
was a sandbox Chromium run, not the maintainer's click-through (Q1128).

## Setup

| | |
|---|---|
| Code | main at `91780c9eb` |
| State | state C from `scripts/ui_clickthrough_seed.py` (populated, plaintext), booted with `OO_NO_SCHEDULER=1 OO_LLM_AUTOSTART=0 OO_AIRPLANE_SOCKET_GUARD=1` and `--loop asyncio` |
| Offline | Airplane mode was engaged through `/api/system/network` before the first page and was still on after the last. The browser aborted every request not addressed to the loopback server, and none were aborted. |
| axe | axe-core v4.14.0, from the vendored `scripts/vendor/axe-core/axe.min.js`. It was evaluated through the DevTools protocol, so the app's CSP was unchanged. |
| Widths | 1440×900, 768×1024, 390×844 |
| Surfaces (16) | The 13 sidebar tabs, each on its default subtab: Home, Feed, Explore, Insights, Observatory, Time map, Law, Agenda, Climate, Indices, Markets, Living sources and Library. Also Settings, the task-manager window (`/tasks`) and the article reader (`/api/articles/{id}/view`). |
| Pass 1 | Every axe rule, in the default theme (Ink), on every surface at every width. 48 runs. |
| Pass 2 | The two axe rules that measure colour, `color-contrast` and `link-in-text-block`, in each of the 13 other selectable themes, on every surface at 1440×900. 208 runs. |
| Pass 3 | The reader again, every rule at the three widths, with the browser in dark colour scheme. 3 runs. |
| Result | 259 runs. No run failed and no page raised an error. `report.json` holds every violation with up to 25 targets each and a ratio for every node, and `sweep.py` reproduces the run. |

**The reader does not take the app theme.** Its page (`src/api/main.py`, around line 3483) has its own palette: dark by
default, light under `prefers-color-scheme: light`. Playwright's default scheme is light, so passes 1 and 2 measured
the reader's light palette 14 times over, and pass 3 measured its dark palette. Every claim below about themes
covers 15 surfaces, not the reader. The task-manager window does take the app theme (`taskmanager.js` reads it),
and its failing colours do differ by theme.

To reproduce: seed a data folder, boot the app on it with the settings above, then run
`OO_WALK_BASE=http://127.0.0.1:PORT OO_WALK_OUT=<dir> python docs/audit/a11y-sweep-2026-11-20/sweep.py`.
Add `OO_WALK_CHROMIUM=<path>` when the installed Playwright expects a different browser build than the one present.

**There were two runs.** The first, kept as `report-run1.json`, had no pass 3. Its pass 2 checked colour contrast
only, and it kept only the first node's ratio. An Opus read of the first draft found those gaps, so the sweep was
widened and run again. The second run gave the same results as the first for every finding but one, V1 below.

## Verdict

- **Clean in every run**, for all rules at all three widths, and in all 14 themes for both colour rules: Feed, Observatory, Law, Climate, Indices, Markets, Living sources, Library and Settings.
- **Ink** passes `color-contrast` on all 16 surfaces.
- **The reader** passes `color-contrast` in both its palettes.
- **Findings:** 11 rows, below. They come from 8 distinct axe rules: 7 in pass 1 and 1 more in pass 2.
- **Nothing is waived.** The four best-practice findings (V5–V8) are listed as findings, not set aside.

## Pass 1: every rule, Ink theme

The node count is summed over the widths named in the row.

| # | Rule (impact, WCAG) | Page | Widths | Nodes | What fails |
|---|---|---|---|---|---|
| V1 | `link-in-text-block` (serious, 1.4.1) | Home, "Most recent" panel | 1440, first run only | 6 | `.home-recent-row > a`, the offline-copy links. The link colour `#5b9dd9` against the surrounding text `#e8ebf0` is 2.41:1, below the 3:1 floor, and the link has no underline. The panel starts `hidden` and opens once `loadHomeRecent` has picked a tag (`index.html:370`, `app-home.js:856`). In the first run it was open when axe ran at 1440. In every other run it was still hidden, and axe skips hidden content. The colour pair does not change, so this fails whenever the panel shows. |
| V2 | `link-in-text-block` (serious, 1.4.1) | Time map, the line shown when OpenStreetMap is not set up | 1440, 768, 390 | 3 | The "Settings → OpenStreetMap" link (`app-map.js:3528`). The link colour `#5b9dd9` against the muted text `#8c95a6` is 1.04:1, with no underline. |
| V3 | `nested-interactive` (serious, 4.1.2) | Insights, keyword family buttons | 1440, 768, 390 | 9 | `button[data-on-click="pickTerm(…)"]` (`app-insights.js:151`) contains the Wikidata `a.kw-qid` link from `kwQidHtml` (`app-corpus.js:1117`), so a keyboard user cannot reach the link or hear it announced on its own. The link was kept inside the button on purpose (`app-corpus.js:1110-1111`, `noDossier`, the row 178 review), so the fix has to weigh that decision. |
| V4 | `scrollable-region-focusable` (serious, 2.1.1) | Time map, the ranked country list | 1440, 768, 390 | 3 | The scroll box `.oomap-rank > div` (`app-map.js:761`) holds nothing focusable and has no `tabindex`, so a keyboard user cannot scroll it. |
| V5 | `region` (moderate, best practice) | Article reader | 1440, 768, 390 | 12 | `.crumb`, `h1`, `nav` and `#rp-read` are not inside any landmark. |
| V6 | `landmark-one-main` (moderate, best practice) | Article reader | 1440, 768, 390 | 3 | The page has no `<main>`. One fix covers V5 and V6. |
| V7 | `heading-order` (moderate, best practice) | Article reader | 1440, 768, 390 | 3 | The first `.mgrp > h3` comes straight after the `h1`, with no h2 between. |
| V8 | `empty-table-header` (minor, best practice) | Explore, results table | 1440, 768 | 2 | The fifth `<th>`, the actions column (`app-analysis.js:3046` and `:3098`), has no text a screen reader can read. It was not flagged at 390, and the cause was not checked. |

Pass 3 found the same V5, V6 and V7 in the reader's dark palette, and nothing else.

## Pass 2: the colour rules in each theme (1440×900)

The ratio shown is the lowest across the failing nodes.

| # | Rule | Page | Theme: nodes (lowest ratio) | What fails |
|---|---|---|---|---|
| V2 | `link-in-text-block` (3:1) | Time map, OSM line | midnight 1 (1.05), cyber 1 (1.95), forest 1 (1.44), aubergine 1 (1.17), garnet 1 (1.06), solar 1 (1.01), sepia 1 (1.29), terminal 1 (2.07), contrast 1 (1.08), light 1 (1.13), paper 1 (1.02) | The same link as V2 in Ink. Only dawn and mint pass. |
| C1 | `color-contrast` (4.5:1) | Task manager (`/tasks`) | light 10 (3.63), dawn 10 (2.46), mint 10 (3.41), paper 10 (3.35), solar 4 (4.31) | The metric labels `.tm-metric .ml`, the `.tm-tabs` buttons and `#tm-foot` are dimmed with `opacity` (.6, .6 and .55; `taskmanager.html:54`, `:62` and `:133`), which drops them below 4.5:1 in these themes. Solar is a dark theme and fails too, though only on the four metric labels. |
| C2 | `color-contrast` (4.5:1) | Agenda, today's day number | solar 1 (4.05), dawn 1 (4.03), paper 1 (4.42) | `.ag-cell.today .ag-dn` is painted `var(--accent)` (`app.css:1178`). The text is 11 px bold, which is not large text, so 4.5:1 applies, and these three themes' accents fall short. |
| C3 | `color-contrast` (4.5:1) | Home, briefing card back | dawn 1 (4.49) | `.card-back .acts .lead-open`: `#575279` on `#d9c5de`, 0.01 below the floor. It is on the card's back face, which the user reaches with one flip. |

Midnight, cyber, forest, aubergine, garnet, sepia, terminal and contrast pass `color-contrast` on all 15 themed surfaces.

## What this sweep does not cover

- **Default subtabs only.** Other subtabs were not audited, and neither were open dialogs (consent, restore preview, link preview), menus, hover bubbles or the first-run guide.
- **Panels that open late.** A panel that opens only after its data arrives may be missed. V1 is one case.
- **Simple mode** (#34) was not swept.
- **English only.** Locale and RTL layout are the click-through's axes.
- **axe finds a subset of WCAG failures.** Keyboard order, focus visibility and screen-reader wording need the human pass.
- **Non-default themes at one width.** They were measured at 1440×900 only. Colours do not change with width, but a layout that appears only at narrow widths was measured in Ink alone.

## Proposed fix rows, ranked by node count

Each row is a separate PR, with its own test and R319 line.

| Order | Fixes | Nodes | Scope |
|---|---|---|---|
| 1 | C1 | 44 | Task manager: replace opacity-dimming with a muted colour that clears 4.5:1 in every theme, and add a test that the window's muted text uses that colour, not `opacity`. |
| 2 | V2, V1 | 20 (14 + 6) | Underline links set inside text: the Time map OSM line and the Home "Most recent" titles. Use an underline, not a colour change, since V2 fails in 12 of 14 themes. |
| 3 | V5, V6, V7 | 18 | Reader: put the article in `<main>`, the crumb and nav in landmarks, and make the group headings h2. |
| 4 | V3 | 9 | Insights family buttons: a link nested in a button. Read the row 178 decision (`app-corpus.js:1110-1111`) and run `planned.py` first. One option is to draw the Wikidata link as a sibling after the button. |
| 5 | C2, C3 | 4 | Theme colours: the solar, dawn and paper accent on the 11 px "today" number, and dawn's card-back action. Change the theme colours and extend the theme contrast test to these pairs. |
| 6 | V4 | 3 | Time map rank list: give the scroll box `tabindex="0"`, a role and a label. |
| 7 | V8 | 2 | Explore results table: a visually hidden "Actions" label in the empty header, ×12. |
