# Prompt 15 — The browser-verified UI backlog

> **Scope:** `src/static/`, the click-through harness, i18n keying, accessibility.
> **Gated on:** H2 (the verification bar), H3 ⛔ (the Insights search bar), H4 (inline handlers), L2, L5, L7.
> **Sequencing:** independent, and it is the prompt with the most accumulated debt. Split it across several
> sessions rather than trying to land it in one.

## 0. Working mode

Read `_WORKING_MODE.md` — in particular §6, because **this sandbox has Chromium** and the standing
"browser-unverified per fork-3" caveat is a habit rather than a limit. Then read
`docs/audit/GUI_TEST_REPORT_2026-07-22.md`, `docs/audit/UI_CLICKTHROUGH_2026-08-13.md` and
`docs/audit/UI_CLICKTHROUGH_2026-08-20.md`, and `docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-28_GUI_AUDIT.md`.

The honesty rules for browser work are recorded and each was learned from a defect that shipped:

- Score the **composited** colour, not the declared token — element `opacity` composites the whole element
  over what is behind it, so a rule reading `color:var(--muted); opacity:.6` is not a muted-on-panel pair, and
  scoring it as one passed on all 17 themes while 16 of them failed AA in reality.
- Read pseudo-element inheritance with `getComputedStyle(el, '::after')` — a component that gains a shared
  `::after` from a convention inherits every property the more specific rule does not declare, which is how a
  ruled diagonal bar rendered as a 4×4 dot for months.
- Apply greyscale as a **browser filter** and capture **mid-interaction** — a screenshot taken after the click
  navigated away tests nothing about the state you care about.
- An untested code path is not a pass. If the fixture contains no gaps, the gap-rendering path is unverified,
  and saying so is the finding.
- `uppercase` is a no-op in five of the twelve locales, so case can never carry hierarchy.
- Punctuation-joined values (dates, versions, IDs, URLs, ranges) need bidi isolates in RTL; a bare number does
  not.
- One browser per server instance: the "384 JS errors" in the 2026-07-22 run were 100% rate-limit console
  lines from that run's own 14-agent parallelism, with **zero** uncaught exceptions.

## 1. Slices

### S1 — The residue of the 2026-07-22 report

All five P0s are fixed and 21 of 24 P1s. **Three P1s remain open**: the Home glance strip mixing languages,
Lead titles frozen in the locale they first rendered in (the interpolated-`tf()`-string class — an already
interpolated string is no longer a key, so a render-once surface must register with `oo:langchange`), and
unsegmented zh keywords on the Insights map.

The **P2 tier was never closed** — 12 open, 8 partial, 5 unchecked — although a shipped-ledger row describes
that report as closed out. Correct the row and work the tier.

### S2 — H4: the inline handlers, and the CSP that waits on them

Measured 2026-09-06: roughly **590** inline `on*=` handlers (~331 in `index.html`, ~259 across the
`app-*.js` modules) against ~103 `addEventListener`. The ledger's recorded figure of "295 as of 2026-06-15"
counted `index.html` only and predates the module split.

This is what blocks a nonce-based CSP; `'unsafe-inline'` remains in `script-src`. It is also the largest
single browser-gated item, so do it in bounded passes with a byte-parity discipline: a green walk does not
prove each of 590 handlers works when clicked.

### S3 — Dead UI code, deleted with a browser open

The retired temporal-map cluster (`loadTimemap`, `renderTimemap`, `showTmapDetail` and their siblings in
`app-map.js`) is unreachable but **interleaved with live helpers** that `ooMap` still uses — `kindColor`,
`TMAP_KINDS`, `fmtYear`, `fmtDate`, `dateToT`, `lon2x`/`lat2y`, `tmapFindCoverage`. A wrong deletion passes
`node --check` and breaks the map at runtime, which is exactly why this was deferred.

Also: the retired `#corpus-win` modal, the orphaned `loadIndicesData` / `loadMarketData`, the orphaned
`#onboard` locale keys, and **PRH-14** — the unwired `#vitals-pop` popover, which is in the tree and absent
from the recorded dead-UI worklist. Do **not** delete `firstRun`; it is test-pinned and intentionally retained.

### S4 — ⛔ H3: the Insights search bar

`#ins-term` and `exploreTerm` are still live. Removal is absorption-gated: the omnibar → spawned analysis tab
must own term exploration first, and `#ins-explore` interleaves the search bar with a **non-searchable**
corpus-landscape and a **relocatable** shared `#mm-kit` that moves into the corpus window and back. A blind
`display:none` is the interleaved-shared-component hazard. Port, guard the absorption, then hide — with a
browser open.

### S5 — i18n: 240 unkeyed strings still in source

The 2026-07-28 audit found 286 unkeyed audit strings of which 240 are still present; 84 were keyed since.
Both ratchets sit at **zero slack** (`--max-untranslatable 560`, `--max-unkeyed-t-calls 297`), so every new
string must be keyed in the same commit or CI reddens.

Known specifics: the eight `guis/` skins are outside the gate's scope entirely; `reader.js` calls `t()` zero
times; the `{action} failed: {error}` template was considered and **rejected** in favour of full-sentence keys
(that decision is recorded — do not re-propose the template); three Library subtab labels (`Activity`,
`Tracked`, `Database & storage`) were unkeyed (PRH-33) — **SHIPPED 2026-09-07 (PR #1029)**, keyed
×12 and the untranslatable ratchet lowered 560 → 557 in the same PR; the uninstall dynamic preview and confirm dialogs stay
English (PRH-19).

Lower a ratchet in the same PR that frees the slack — leaving slack invites the next drift to land unseen.

### S6 — Accessibility and layout

The five a11y P2s from the axe-core pass. There is no layout media query between 900 px and desktop
(`max-width:900px` is still the widest).

**Two claims in this slice were STALE and are corrected here (2026-09-07, PR #1029), per the working
mode's staleness rule:**

- ~~`prefers-contrast` is unhandled~~ — **VERIFIED-PRESENT.** `app.css` carries
  `@media (prefers-contrast: more)`, added by the 2026-07-28 GUI audit's finding G-3, and the
  2026-08-20 matrix measured it applying live under `emulate_media(contrast="more")` (hint colour
  and icon borders measurably change). Do not rebuild it.
- ~~`.sr-only` is absent from the static shell~~ — **VERIFIED-PRESENT.** `app.css:161`, used by
  `app-markets.js`, `app-map.js` and `app-library.js` for the chart data tables that make an SVG
  figure readable. Do not rebuild it.

**SHIPPED 2026-09-07 (PR #1029):** the `h3`-over-`h2` type inversion (PRH-32). It was real and
wider than recorded — measured in Chromium on all 17 themes, Home's section title rendered 12.5px
in `--muted` at 4.56–12.71:1 under a briefing card's own 15px full-`--fg` title at 6.07–18.10:1,
and Library's `.lib-sub` and the Feed's `.feed-t` had the same shape. Lifted app-wide through a
zero-specificity `:where()` default. The two Export/Import dialogs turned out to be a SEPARATE
defect (they alone of eleven omitted `background`/`color`, so no theme reached them), and the same
pass found `var(--line)` undefined at 41 SPA call sites — parked with a ratchet and a question, in
`docs/ledger/OPEN_QUEUE.md`.

### S7 — The unrendered work

Several backends have no surface, and each is a small slice:
- **PRH-31:** `_window_daily_series` omits zero-count days, so the index axis compresses — day 1 and day 5
  render adjacent. The repair is zero-**filling** (for keyword mentions an absent day is a real zero), and it
  touches the trending sparklines.
- Leads 2.0 grading onto Home (evidence chips, a sort control wired to `sort_leads` with the `explain_order`
  hover, lifecycle deltas) — it visibly reorders the flagship feed, which is why it is browser-gated.
- The Conjunction-lens deeper views (conditional trend, vocabulary contrast, per-article intensity, lead/lag)
  need a payload extension; the core computes them via separate helpers today.
- The subjectivity reader highlight panel — the spans are emitted and nothing renders them.
- The corpus facet filters in the Articles subtab (source and language present in the **current** corpus,
  with counts), with an id-seeded corpus **intersecting** rather than clearing on refine.
- Eleven `ooViz` primitives remain unwired. Note the recorded correction: the namespace is `ooViz`, not
  `ooviz`, and a case-sensitive grep for a name you did not read out of the file is not evidence of absence.
- **L5:** the `_SPARSE_BAR_MAX` reach decision for `commodityOverlaySvg` (it draws a real price line, so
  probably yes), `ringDumbbellSvg` (discrete pairs, arguably no) and `ooDonut`.

### S8 — L2: settle the verification bar

Every stamp currently reads "Chromium-verified (remote sandbox) · awaiting human UX pass". The 12-locale sweep
covers four; rule 9 (adversarial screenshot reading) has never run; the Gecko/AppVM bar has never been met.
Whatever L2 rules, make the stamp mean one thing and apply it consistently.

## 2. Scope fence

The Observatory is prompt 16. Do not lower a ratchet without freeing the slack first. Do not delete a shared
helper without driving the surfaces that use it.
