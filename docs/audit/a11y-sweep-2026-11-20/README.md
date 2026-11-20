# Accessibility sweep at three widths (0.9 row D, S4), 2026-11-20

This is a report only. No code was changed, and every violation below becomes a fix row of its own.

It was a sandbox Chromium run. It is not the maintainer's click-through (Q1128).

## Setup

| | |
|---|---|
| Code | main at `91780c9eb` |
| State | state C from `scripts/ui_clickthrough_seed.py` (populated, plaintext), booted with `OO_NO_SCHEDULER=1 OO_LLM_AUTOSTART=0 OO_AIRPLANE_SOCKET_GUARD=1` and `--loop asyncio` |
| Offline | Airplane mode was engaged through `/api/system/network` before the first page and was still on after the last. The browser aborted every request that did not go to the loopback server, and none were aborted. |
| axe | axe-core v4.14.0, the vendored `scripts/vendor/axe-core/axe.min.js`. It was evaluated through the DevTools protocol, so the app's CSP was unchanged. |
| Widths | 1440×900, 768×1024, 390×844 |
| Surfaces (16) | The 13 sidebar tabs on their default subtab (Home, Feed, Explore, Insights, Observatory, Time map, Law, Agenda, Climate, Indices, Markets, Living sources, Library), plus Settings, the task-manager window (`/tasks`) and the article reader (`/api/articles/{id}/view`) |
| Pass 1 | All axe rules, in the default theme (Ink), on every surface at every width: 48 runs |
| Pass 2 | The colour-contrast rule only, in each of the 13 other selectable themes, on every surface at 1440×900: 208 runs. Contrast is the only axe rule a theme changes. |
| Result | 256 runs. No run failed, and no page error was raised. `report.json` holds every violation with its targets, and `sweep.py` reproduces the run. |

To reproduce: seed a data folder, boot the app on it with the variables above, then run
`OO_WALK_BASE=http://127.0.0.1:PORT OO_WALK_OUT=<dir> python docs/audit/a11y-sweep-2026-11-20/sweep.py`.
Add `OO_WALK_CHROMIUM=<path>` when the installed Playwright expects a different browser build than the one present.

## Verdict

- **Clean in every run:** Feed, Observatory, Law, Climate, Indices, Markets, Living sources, Library and Settings, in all rules at all three widths and in all 14 themes for contrast.
- **The Ink theme passes colour contrast on all 16 surfaces.**
- **Violations:** 8 distinct problems, listed below. **Nothing is waived.** The three best-practice rules are listed as findings too, not set aside.

## Violations

The count is the number of failing nodes summed over the runs named in that row.

### Pass 1: all rules, Ink theme

| # | Rule (impact, WCAG) | Page | Widths | Nodes | What fails |
|---|---|---|---|---|---|
| V1 | `link-in-text-block` (serious, 1.4.1) | Home, "Recent" list | 1440 | 6 | `.home-recent-row > a` (offline-copy links). Link `#5b9dd9` against surrounding text `#e8ebf0` is 2.41:1, below the 3:1 floor, and the link has no underline. Not flagged at 768 or 390. I have not checked why; the likely cause is the narrower row layout. |
| V2 | `link-in-text-block` (serious, 1.4.1) | Time map, the OSM-not-set-up line | 1440, 768, 390 | 3 | The "Settings → OpenStreetMap" link (`app-map.js:3528`). Link `#5b9dd9` against muted text `#8c95a6` is 1.04:1, with no underline. |
| V3 | `nested-interactive` (serious, 4.1.2) | Insights, keyword family buttons | 1440, 768, 390 | 9 | `button[data-on-click="pickTerm(…)"]` (`app-insights.js:151`) contains the Wikidata `a.kw-qid` link from `kwQidHtml` (`app-corpus.js:1117`). A link inside a button cannot be reached or announced on its own. |
| V4 | `scrollable-region-focusable` (serious, 2.1.1) | Time map, the ranked country list | 1440, 768, 390 | 3 | `.oomap-rank > div` (`app-map.js:759`) scrolls but holds nothing focusable and has no `tabindex`, so a keyboard user cannot scroll it. |
| V5 | `region` (moderate, best practice) | Article reader | 1440, 768, 390 | 12 | `.crumb`, `h1`, `nav` and `#rp-read` sit outside any landmark. |
| V6 | `landmark-one-main` (moderate, best practice) | Article reader | 1440, 768, 390 | 3 | The page has no `<main>`. V5 and V6 have the same fix. |
| V7 | `heading-order` (moderate, best practice) | Article reader | 1440, 768, 390 | 3 | The first `.mgrp > h3` follows the `h1` directly, skipping h2. |
| V8 | `empty-table-header` (minor, best practice) | Explore, results table | 1440, 768 | 2 | The fifth `<th>` (the actions column, `app-analysis.js:3046` and `:3098`) has no text a screen reader can read. Not flagged at 390, and I have not checked why. |

### Pass 2: colour contrast per theme (1440×900; WCAG 1.4.3 AA, 4.5:1)

| # | Page | Theme: nodes, worst ratio | What fails |
|---|---|---|---|
| C1 | Task manager (`/tasks`) | light 10 (4.24), dawn 10 (2.62), mint 10 (3.90), paper 10 (3.85), solar 4 (4.31) | `.tm-metric .ml`, the `.tm-tabs` buttons and `#tm-foot` are muted with `opacity: .6` and `.55` (`taskmanager.html:54`, `:62`, `:133`). On a light background, opacity drops the text below 4.5:1. In solar only the four metric labels fail. |
| C2 | Agenda, today's day number | solar 1 (4.05), dawn 1 (4.03), paper 1 (4.42) | `.ag-cell.today .ag-dn` paints `var(--accent)` at 11 px (`app.css:1178`). These three themes' accents fall short of 4.5:1 at that size. |
| C3 | Home, briefing card back | dawn 1 (4.49) | `.card-back .acts .lead-open`: `#575279` on `#d9c5de`, 0.01 below the floor. It sits on the card's back face, which a user sees after one flip. |

Midnight, cyber, forest, aubergine, garnet, sepia, terminal and contrast pass colour contrast on all 16 surfaces.

## What this sweep does not cover

- **Default subtabs only.** Other subtabs, open dialogs (consent, restore preview, link preview), menus, hover bubbles and the first-run guide were not audited.
- **Simple mode** (#34) was not swept.
- **English only.** Locale and RTL layout are the click-through's axes.
- **axe finds a subset of WCAG failures.** Keyboard order, focus visibility and screen-reader wording need the human pass.
- **Contrast in non-default themes was checked at one width.** The colours do not change with width, but layouts that appear only at narrow widths were measured in Ink alone.

## Proposed fix rows, ranked by node count

Each row is a separate PR with its own test and R319 line. The first column is the order to take them in.

| Order | Fixes | Nodes | Scope |
|---|---|---|---|
| 1 | C1 | 44 | Task manager: replace opacity-muting with a muted colour that clears 4.5:1 in every theme. Add a test that the window's muted text uses the token, not `opacity`. |
| 2 | V5, V6, V7 | 18 | Reader: wrap the article in `<main>`, put the crumb and nav in landmarks, and make the group headings h2. |
| 3 | V3 | 9 | Insights family buttons: move the Wikidata link outside the button, the same way the term rows place it beside the link. |
| 4 | V1, V2 | 9 | Underline links that sit inside text (Home "Recent" and the Time map OSM line). Optionally lift the link colour to 3:1 against muted text. |
| 5 | C2, C3 | 4 | Theme accents: solar, dawn and paper accent for the 11 px today number, and the dawn card-back action. Adjust the theme tokens and extend the theme contrast test to these pairs. |
| 6 | V4 | 3 | Time map rank list: `tabindex="0"`, a role and a label on the scroll box. |
| 7 | V8 | 2 | Explore results table: a visually hidden "Actions" label in the empty header, ×12. |
