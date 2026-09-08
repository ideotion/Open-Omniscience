# Visual design programme (2026-09-08)

> Produced by the live visual audit of 2026-09-08 —
> see [`docs/audit/11_VISUAL_UI_AUDIT_2026-09-08.md`](../audit/11_VISUAL_UI_AUDIT_2026-09-08.md) for the
> method, the fleet, and the honest scope. **Report-only: nothing here was implemented.**
>
> This document answers the design half of the commission: *"suggest appealing visual additions,
> optimizations, tweaks, effects"*. It was produced by six design agents working from a corpus of
> real screenshots of the running app (not from source alone), and **every proposal was then ruled on by
> three independent screening panels** — an invariant/non-negotiable panel reading `CLAUDE.md`, a
> feasibility panel reading the real frontend, and an accessibility panel. A proposal rejected by any
> panel either dies (§9) or returns in its amended form.
>
> **Two caveats carried from the source work, stated rather than buried.** (1) The accessibility panel's
> per-item output was truncated in transmission after its first ruling; where a specific accessibility
> ruling cannot be cited the text says so and falls back to that panel's seven complete cross-cutting
> rules. (2) Contrast numbers quoted from the agent phase predate the mid-run correction of the audit
> harness (§0.1 of the audit report); the **authoritative, corrected 17-theme figures** are in
> [`docs/audit/ui-visual-2026-09-08/contrast-corrected.csv`](../audit/ui-visual-2026-09-08/contrast-corrected.csv)
> and in §2.2 of the audit report. Where the two disagree, the corrected sweep wins.
>
> Nothing in this document is a maintainer ruling. Where a proposal would touch a numbered UI invariant,
> it says which one and proposes the amendment wording — the maintainer amends invariants, not a session.

---

# Design & aesthetics — critique and programme

*Synthesis of five source audits (design-system, critique-flagship, critique-secondary, dataviz, colour-type-motion) and three screening panels (invariant/non-negotiable, feasibility, accessibility) against a live, screenshotted instance of Open Omniscience (STATE C fixture, port 8039 fleet). Grounded in `/home/user/Open-Omniscience/src/static/app.css` (1,718 lines / 717 selectors), `index.html`, and ~130 screenshots under `/home/user/oo-ui/`. One caveat carried through every section below: the accessibility screening panel's per‑item output was truncated in transmission after its first ruling (`P1-DS`) — where I cannot cite a specific accessibility ruling I say so rather than invent one, and fall back to the panel's seven cross-cutting rules (numbered ①–⑦, listed in §6) which are complete and load-bearing.*

---

## 1. What this app looks like today, honestly

Open Omniscience is a disciplined, unusually well-documented codebase wearing an inconsistent face. The colour system, the honesty rules baked into its chart primitives, and the comment culture in `app.css` are better than most production apps this size — and three or four surfaces (Library's Database & storage tab, Search's command palette, the Observatory's core geometry, Custody's loading state) are genuinely excellent, portfolio-grade work. But the product was built one screen at a time over roughly a year, and it shows in the seams: a type system with 24 ad hoc font-size values, 9 independently-built "chip" components for one visual atom, and — the single most pervasive defect found by every one of the five audits independently — a consent popup that covers the app's own content on every surface it was screenshotted on.

**The one thing true of nearly every surface.** `#net-coach` ("You're offline…") renders at the same fixed top-right coordinates and clips real content in **11/11 secondary surfaces**, **8/8 Observatory theme/locale renders**, and every sampled Home/Feed/Search/Insights screenshot — never landing in empty space. It truncates the stat strip's "13 SOURCES QUALIFIED" to "13 SOUR" (`/home/user/oo-ui/wf-a1/home/home-00-initial.png`), it clips Analyze's "Sentiment" subtab label — a navigation element, not decoration (`/home/user/oo-ui/out/surface-analyze.png`) — and on the Observatory it clips the one sentence disclosing that the chart's angle channel is meaningless (`/home/user/oo-ui/wf-b/themes-dark/ink-observatory.png`, `terminal-observatory.png`). On World map it collides with a second floating tooltip ("Tasks & system"), producing genuinely garbled overlapping text (`/home/user/oo-ui/wf-f/capabilities-backend-unsurfaced/04-timemap-tab.png`). This is not six separate bugs; source inspection (feasibility panel) found the fix already exists as a tested function, `_placeCoach()`, that already guards against 4 top-bar buttons — the job is extending one union-rect, not writing new collision logic. See §3/§7 (`home-1`).

**What's already excellent, named plainly, because taste needs anchors:**
- The colour token system (`:root`'s 24 colour custom properties, `color-mix()`-derived, contrast-checked across 17 themes with the actual worst-case ratios left in the source as comments) — the best-engineered part of the file.
- `ooChart`'s three redundant identity channels (colour + dash + marker), built specifically because the team measured and documented that two of the six `--fig` colours collapse to 1.00:1 luminance separation on the Cyber theme (`app.css` lines 59–91).
- The sparse-series bar rule (n<10 → bars, value-capped, baseline-labelled) — verified live and correctly rendered on the Commodities board (`/home/user/oo-ui/out/surface-markets.png`).
- The Observatory's two honest refusals (log-scale below one decade; zero-valued galaxies to a labelled outer band, never merged with the nebula) — real, tested, and correctly triggered on the reference corpus.
- Library → Database & storage (`/home/user/oo-ui/wf-a2/library/library-30-storage-remeasuring.png`) and Settings → Graphics (a 17-swatch theme grid, each font button set in the font it names) — both should be the template the rest of the app is brought up to.
- The RTL implementation on Indices (`/home/user/oo-ui/wf-a2/indices/15-rtl-arabic-all.png`): correctly mirrored tabs, right-aligned popup, LTR numerals inside Arabic prose. A positive reference, not an afterthought.
- Custody's loading state ("Loading custody settings…" with visibly disabled checkboxes) — exactly the affordance three other surfaces (Governments' bare empty dropdowns) lack.

**What reads as unfinished, named plainly:**
- Home's draft-basket panel (`/home/user/oo-ui/wf-a1/home/home-23-draft-basket-open.png`) looks like a different, earlier app next to the polished lead cards above it.
- Insights ends its Explore panel with two bare bold headings ("How outlets frame this," "In context") and **zero content beneath either** — no rule, no placeholder — in 6/6 sampled theme/locale screenshots.
- Governments cycles through five different registers in six clicks: empty → empty → medium → empty → a genuinely good Law dashboard → a six-form raw fetch console (`law-03-subtab-statistics.png`) that is exactly the "plumbing in a data tab" invariant #8 forbids.
- Settings' "Advanced" tab hides a 10-section, 3-levels-deep accordion (a 3,618-row source table, a 241-feed calendar directory, a literal statistical-threshold tuning console) behind identical-weight collapsed headers with zero indication of scale.
- Help shows two non-matching navigation structures for one document in a single screenshot (`/home/user/oo-ui/out/surface-help.png`), and its left-rail chrome — not just the 167,022-character body — stays in English in the German and French renders while every other piece of chrome on the same screenshot is translated.
- Agenda's month grid ellipsis-truncates 7/7 visible multi-word event titles, with "International Day of …" the identical truncated prefix for three *different* events on the same screen (`/home/user/oo-ui/out/surface-agenda.png`).

The honest summary: this is a team that solved several genuinely hard honesty-vs-beauty problems well, in one file at a time, and never went back to make the solutions consistent with each other. Nearly everything below is "do here what you already did three lines up" — not invention.

---

## 2. The design system it does not yet have

`:root` defines 35 custom properties. 24 are colour (well-built — see §1). The remaining 11 give a font stack, one flat `--pad`/`--space` pair, one flat `--radius`/`--radius-sm` pair, one flat `--shadow`, and `--sidebar-w`. **There is no type scale, no spacing scale beyond two rungs, no shadow tiers, and no z-index scale.** One property, `--line`, is referenced 41 times across the SPA and defined nowhere — every one of those declarations is silently invalid at computed-value time.

### 2.1 The `--line` bug (P1 — DS-P1)
`grep -rn -- '--line *:' src/static/` returns zero definitions against 41 SPA usages (`app.css` ×7, `index.html` ×14, `taskmanager.html` ×2, five `app-*.js` files ×11, excluding `reader.css`'s separate 8). `app.css` lines 305–311 already document this exact failure mode for `<dialog>` and fixed *only that call site* (`dialog{border:1px solid var(--border)}`). Confirmed live and broken elsewhere: `#oo-tip` (the invariant-#17 tooltip instrument) and `#net-coach` render with **no border on any theme**, `.gw-dot` (onboarding progress dots) has an invalid `background`, `.gw-lang`/`.carousel-dot` share the same fault. Fix: `--line:var(--border);` in `:root`, or delete the 41 sites in favour of `--border`. Zero regression risk — every current computed value is `0px none`.

### 2.2 Type scale — one canonical proposal, five proposals folded into it
150 `font-size` declarations resolve to 24 distinct values; 56 (37%) sit below 12px. A 1.125 ("major second") ratio run from the app's own existing 15px body size lands within 0.5px of eight already-in-use values with **zero adjustment**:

| step | px (1.125ⁿ×15) | matches (existing, unadjusted) | delta |
|---|---|---|---|
| +4 | 24.02 | 24px (`.stat .n`) | 0.02px |
| +3 | 21.35 | *(new "hero number" rung)* | — |
| +2 | 18.98 | 18px (4 uses) | 0.98px |
| +1 | 16.87 | **17px — PRH-32's own h2 choice (2026-09-07)** | 0.13px |
| 0 | 15.00 | 15px (body) | 0.0px |
| −1 | 13.33 | 13px (12 uses) / 13.5px (5) | 0.17–0.33px |
| −2 | 11.85 | 12px (36 uses) / 11.5px (10) | 0.15–0.35px |
| −3 | 10.53 | 10.5px (11 uses) | 0.03px |
| −4 | 9.36 | 9.5px (1 use) | 0.14px |

PRH-32 (shipped one day before this audit, `app.css` 1353–1395) already unified `<h2>`/`<h3>` inside panels/dialogs — real progress, covering 2 of ~24 sizes. **This scale finishes what PRH-32 started.** Four other audits independently proposed near-identical scales (CTM-P4, CD-P1, CD-P44, CD-P46) — all of them fold into **one** migration (canonical: DS-P2), reconciled to the table above, never landed twice. The one open decision PRH-32 leaves: its own h3=15.5px sits between step 0 and step +1 with no clean rung — round to 16.9px or keep a documented half-step exception; that's a maintainer call, not an agent one. Companion rule (DS-P3, folds into the same migration): reserve the two lowest steps (9.5/10.5px) for machine-shaped labels only; anything a journalist reads start-to-finish (`.card .sum`, table cells) moves to step −1/0.

### 2.3 Spacing
125 `padding` declarations → 83 distinct shorthand strings (CD-P2: introduce `--space-1..6`, migrate incrementally, no forced rewrite). 9 chip components alone show 4 distinct radii and 6 distinct paddings for one visual atom (§2.5).

### 2.4 Z-index — one canonical scale, three proposals consuming it
19 declarations, 14 distinct raw values, no naming: `0,1,30,50,55,60,140,150,151,200(×3 unrelated roles),360,400,9998,99998`. `.sidebar` and `.vitals-pop` coincidentally share `z:60`; `.skip-link`, `#net-flash`, `#toast` coincidentally share `z:200`. **The existing relative order is already correct** (content < chrome < scrim < overlay < signal < coachmark < tooltip < consent < crash) — it just isn't named. Canonical scale (DS-P6):

```
--z-base:0        --z-raised:10      --z-dropdown:200    --z-sticky:300
--z-scrim:350     --z-rail:400       --z-overlay:500     --z-palette:510
--z-signal:600    --z-coach:700      --z-tooltip:800     --z-consent:900   --z-crash:1000
```

⚠️ **Landmine, confirmed by direct source read:** `tests/test_repo_invariants.py` line 3779 asserts the **literal string** `.chrome { position:sticky; top:0; z-index:50; background:var(--bg2); }`. Any z-index tokenization (DS-P6 and every consumer of it — CD-P4/CD-P8/CD-P47/W2) **must update this assertion in the same commit** or CI reddens. CD-P4 is a duplicate of DS-P6 with different values and must not land separately.

### 2.5 Radius, chips, shadow
- Radius: 115 declarations, 19 distinct value-strings; 106 of 115 bypass the two existing tokens. CD-P5/CD-P3: consolidate onto `--radius`/`--radius-sm`, merge the 99px/999px cluster (visually identical at chip scale).
- Chips: 9 independently-authored components (`.pill`, `.kb-chip`, `.basis-chip`, `.cap-chip`, `.ag-chip`, `.ag-catchip`, `.fam-chip`, `.ls-chip`, `.ag-tag`) → one `.chip` base + modifiers (DS-P4). **Test-pinned literal strings found by direct read**: `test_repo_invariants.py` lines 3481 and 5314 assert `.ag-catchip` and the exact template `fam-chip${isRing ? " lvl-group" : ""}` — these class names must survive as modifier classes verbatim, not be renamed away.
- Shadow: `--shadow` is *already* correctly theme-tinted (light theme: `rgba(20,30,50,.28)`, verified in ≥5 light-theme `:root` blocks) — the mechanism works. But ~9 declarations bypass it with literal `rgba(0,0,0,...)`, clustering exactly on floating chrome: `#oo-tip`, `#net-coach` + its `coachpulse` keyframe, the consent popup, the range-slider thumb. **Canonical fix is CD-P29** (retints the base `--shadow` token app-wide via `color-mix()` — the superset), with **DS-P7 folded into it** (routes the specific floating-chrome consumers onto the token). Ship together, once.

### 2.6 Motion tokens
14 `transition:` declarations spanning 11 distinct durations (.04s…9s) and 2 easing families, no shared tokens. CTM-P9: introduce named duration/easing custom properties; low functional risk since the app's global `prefers-reduced-motion` kill switch already zeroes all of it — but the 25-touchpoint breadth warrants a grep pass for any test asserting a specific duration value before retiming (none found in the spot-check performed, but not exhaustively ruled out).

---

## 3. Surface-by-surface critique — top three changes each

**Home** (`/home/user/oo-ui/wf-a1/home/home-00-initial.png` et al.) — the strongest single unit in the app is the three-lead-card row (colour accent + named badge + plain-language body + disclosed-ranking footnote); it fails on the flip-card back, where the Method paragraph clips mid-sentence with no scroll cue, and the subtab bar reorders itself unpredictably across otherwise-identical states (three screenshots, three different row-2 members).
1. `home-1` — collision-aware `#net-coach` placement (extends the existing tested `_placeCoach()`).
2. `home-2` — scrollable, fade-cued flip-card back (`max-height` + `overflow-y:auto` + `mask-image`).
3. `home-3` — stable, scrollable subtab order via `ooSubtabs` (invariant #18), not a bespoke component.

**Feed** (`feed-fully-loaded-top.png`) — a calm, well-typeset editorial list undermined by zero card framing (every article reads equally important) and a silently-shortened byline when a date is missing.
1. `feed-1` — never render a byline with a silently-missing date; translated `date_unknown` placeholder.
2. `feed-2` — unify the Order row's mixed button/text-link grammar.
3. `feed-3` — bottom-sheet net-coach placement at <600px (currently overlaps the H1 and the entire Order row at 375px).

**Insights** (`surface-insights.png`, `zoom-insights-mmkit.png`) — genuinely honest weight/size-encoded tag cloud, undercut by a live, screenshotted layout bug and two empty section headings with no fallback text.
1. `insights-1`/`DS-P8` — fix the `.seg-toggle` flex-overflow collision (Super-groups renders visibly underneath Mind-map; reproduces differently in German).
2. `insights-2` — honest, translated "not enough data" text under the two bare headings.
3. `insights-3` — re-rank the "THEMES 16" eyebrow so it never renders smaller/dimmer than the tag items it introduces (weight+size+colour token, never `text-transform:uppercase`, which is a no-op in 5/12 locales).

**Search** (`surface-search.png`) — the best-structured form in the app plus the single cleanest UI in the whole review (the command palette), diluted by a 9-button toolbar with only one weight class and four mixed affordance styles per result row.
1. `search-1` — collapse 7 of 9 toolbar buttons into one "Export & tools ▾" disclosure, preserving each item's #17 hover-tooltip.
2. `search-2` — consolidate each result's mixed link/pill/button actions into one row.
3. `search-3` — suppress the passive `#net-coach` nag while any modal (e.g. the palette) is open, without touching a genuinely-triggered `ensureOnline()` popup.

**Observatory** — treated fully in §5.

**World map** (`surface-timemap.png`) — a genuinely well-executed map (in-map pan/zoom, honest diagonal-hatch for no-data countries) let down by a choropleth that only communicates "has data / doesn't," not magnitude.
1. `W1` — widen the fill-colour scale so the legend's implied 1→237-source gradient is perceivable between filled countries, with a hover-exposed exact count so colour is never the sole read.
2. `W2` — fix the tooltip/`#net-coach` z-index collision (part of the consolidated net-coach fix, using the DS-P6 token).
3. `DV-06` — wire the already-built, zero-caller `ooViz.symbolRadii` into level-indicator maps instead of falling back to a bare table (implements the maintainer's own §5B ruling, never wired up).

**Governments** (`law-*.png`) — five registers in six clicks (see §1); the Law subtab itself is a genuinely good dashboard.
1. `G1` — a populated "not loaded yet" tile for Countries/Compare/Map instead of a silent empty `<select>`.
2. `G2` — relocate or re-skin the Statistics subtab's six-form raw fetch console; this is a direct invariant-#8 violation ("data, never plumbing"). Feasibility panel prefers the cheaper in-place restyle-as-operator-tool over a full move.
3. `G3` — cap the tracked-laws table's max-width or add a column; it wastes ~40% of a 1920px viewport (`law-wide2-1920-law.png`).

**Agenda** (`surface-agenda.png`) — the best mainstream-calendar mental-model match in the app, wrecked by truncation on the one screen a calendar exists to make scannable.
1. `A1` — allow month-grid pills to wrap instead of ellipsis-truncating (verify no regression on Week/Year/Decade, which share the grid).
2. `A2`/`CD-P23` — an always-visible (not hover-only) legend for the moon-phase glyphs; the two proposals are the same fix, `CD-P23`'s always-visible spec wins.
3. `A3` — a card boundary for the "no fixed day" strip so it reads as first-class data, not a footnote.

**Indices** (`surface-indices.png`) — an honest paragraph and a first-rate RTL render, undercut by 7 continent tabs and 9 tags that render byte-identical panel content regardless of selection.
1. `I1` — filter-aware empty-state copy ("No European indices tracked yet" vs. the generic message) so a working filter is distinguishable from a broken one.
2. `I2` — convert the mobile 7-tab wrap (4 uneven lines at 375px) into a horizontal-scroll strip, via `ooSubtabs` rather than a bespoke component.
3. `I3` — protect the existing Arabic RTL implementation as a regression guard while touching the same surface for I1/I2.

**Commodities/Markets** (`surface-markets.png`) — the most sophisticated, and only live-verified, correct instance of the sparse-bar honesty rule (#16) in production.
1. `C1` — a real card boundary between the price chart and the conceptually distinct Minerals-supply (USGS) section.
2. `C2` — an in-chart annotation explaining the bar→line mark-style transition (scoped to this panel first before generalizing into the shared `ooChart` toolkit, per feasibility panel).
3. `C3` — legibility polish on uneven-decimal Y-axis ticks (109.5/105.6/101.7/97.84) without touching the honest window-min computation.

**Library** (`library-*.png`) — the strongest-designed surface in the whole audit (Database & storage tab), let down by two small but sharp inconsistencies.
1. `L1` — unify the "—" vs "0" empty-value glyph for parallel metrics in the same stat row (preferred over `CD-P24`'s alternative hover-explained two-glyph fix).
2. `L2` — grey out 7d/30d/90d range toggles on cards that say "No data yet."
3. `L3` — fold the all-empty Tracked subtab's 4 cards into Activity's empty-state row rather than hiding the tab outright (feasibility panel: hiding risks reading as a missing feature, not an honest "not yet").

**Settings** (`surface-settings.png`, `adv-*.png`) — a control panel wearing a settings label; Graphics proves the team can build approachable settings.
1. `S2` — live row/scale counts on Advanced's collapsed section headers (the numbers are already computed for the expanded views).
2. `S3` — promote Sources (3,618 rows) and Diagnostics out of the Advanced catch-all into their own top-level tabs, staying inside Settings (compliant with invariant #8).
3. `S1` — **dies in its original form** (see §9); revisit only after S2+S3 ship.

**Analyze** (`surface-analyze.png`) — the emptiest-feeling surface for a fixable reason (controls before content) plus a clean, reproducible i18n gap.
1. `An1` — fix the hardcoded-English empty-state hint, confirmed leaking verbatim in DE/FR/ES screenshots beside a correctly-translated neighbour sentence.
2. `An2` — hide the 9-link export bar until an analysis has actually run.
3. `An3` — fold into the consolidated net-coach fix, prioritized: here the popup clips a navigation label ("Sentiment"), not decoration.

**Custody** (`surface-custody.png`) — the best-handled loading state in the app, let down by flat visual weight across four categorically different buttons.
1. `Cu1` — visually separate the once-configured preference block from the per-item action block.
2. `Cu3` — visually distinguish "Anchor root" (a real, IP-revealing egress, already consent-gated per invariant #14f) from the three purely-local buttons beside it.
3. `Cu2` — replace the "keys: plaintext-0600" badge's primary text with plain language ("Signing key: stored unencrypted on disk"), keeping the jargon in the existing #17 hover bubble — copy work costs a ×12 re-authoring in every locale, not a zero-cost edit.

**Integrity** (`surface-integrity.png`) — well-written, undermined by never-collapsible 3–4 sentence intros repeated on every visit.
1. `In2` — surface each card's fill-state count next to its own heading (cheap, uses data already computed).
2. `In1` — apply the existing flip/expand pattern to the intros — **with a hard constraint**: the collapsed state must still show the plain-language caveat verbatim; only supporting elaboration may hide behind the expand, mirroring invariant #23's flip-card precedent exactly (a naive one-line teaser would violate the informed-consent non-negotiable).

**Help** (`surface-help.png`) — better organised than its 167,022-character size suggests, undone by two concurrent navigation systems visible in one screenshot and untranslated chrome.
1. `H1` — collapse the duplicate numbered "Table of contents" into the left rail's 9 sections as one hierarchy.
2. `H3` (chrome only) — translate the left-rail titles/descriptions now, as closing an existing ×12-locale gap, not a new ask; record the larger body-translation-vs-declared-exception question in `docs/ledger/OPEN_QUEUE.md` for a maintainer ruling (see §9 for the rejected full-translation branch).
3. `H2` — split the monolith into per-topic, deep-linkable panels (QA every existing anchor survives first).

---

## 4. Data visualisation — where honesty and beauty currently fight, and how to stop that

The headline finding across the dataviz audit is reassuring: **the tension mostly isn't there.** Every place a chart looks poor is a place the same file solved the identical problem well *elsewhere* and never carried the fix over — not a forced trade against an honesty rule.

**Where it degrades, concretely:**
- `ooChart`'s dash pattern is applied via `ctx.setLineDash(st.dash)` on the real, zig-zagging canvas path (`app-markets.js:1941–1949`) — dash length is consumed by vertical travel, not time, so a dense window burns through a 27-unit dash cycle in a few pixels and reads as solid. The marker channel is separately suppressed below 9px point spacing (line 1961). Both degrade together in exactly the high-density windows the full-resolution rule guarantees (n=70 Nd series, reproduced byte-identically in EN and DE: `surface-markets.png`, `de-markets.png`) — precisely where the `--fig` ramp's own documented 1.00:1 worst case needs them most. **DV-01**: replace canvas dash-by-path-length with a hand-rolled dasher that steps by projected time-distance.
- `smallMultiplesSvg` (Library → "Growth by language") draws two shared-scale gridlines and **zero numeric labels** — only `n=NN` (point count, not value) — while its sibling `dashChartSvg` two rows above it on the exact same screen (`library-50-activity-enlarge-attempt.png`) labels every gridline with a real number via `honestTicks()`/`_axisNum()`. **DV-02**: add the missing `<text>` labels using the formatter that already exists one file over. Cheapest, cleanest fix in the whole dataviz review.
- The mind-map assigns `var(--ok)` to **both** the seed node and generic supergroup nodes (`app-corpus.js:625–628`), distinguished only by a 200-weight font difference that a larger, heavier supergroup node can visually overwhelm. **DV-04** adds a shape-based secondary channel — generalizing ooChart's own three-channel discipline. *Source-verified only, not screenshot-verified* — a populated mind-map render could not be obtained this session (shared-host memory pressure); flag for a two-minute human check before treating as confirmed.
- The VADER sentiment breakdown renders as three plain text rows despite the app already having a battle-tested, hatch-for-absence horizontal-bar primitive (`_figBars`) wired one tab over. **DV-05**: swap in `_figBars` — same numbers, same caveat, same n, zero new honesty surface.
- `renderStatMap`'s level-indicator path (`app-map.js:1844–1854`) correctly refuses to fake a choropleth for a level indicator, then **also** declines the honest alternative (`ooViz.symbolRadii`, area-proportional circles) the maintainer's own §5B ruling explicitly names as the correct treatment — and falls all the way back to a bare table. **DV-06** wires the already-built, zero-caller primitive in, capped per `oosky.js`'s own `maxStar=13` precedent to avoid crowding.

**Seven unwired primitives, measured directly** (not the eleven a prior draft claimed): `pathWithGaps`, `statSeriesPaths`, `periodToYear`, `symbolRadii`, `binCounts1D`, `bin2D`, `fiveNumberSummary` have zero external callers. Two are internal helpers with no independent use case (`statSeriesPaths`, `periodToYear`). One (`pathWithGaps`) is a real duplicate-maintenance risk: its gap-detection logic was independently re-implemented, not quite identically, as `_seriesRuns` in two separate files — a fix to gap-handling today has to be applied in three places to stay in sync. The other three (`symbolRadii`, `bin2D`, `fiveNumberSummary`) are exactly the shape needed for three new, fully honesty-compliant visualisations:

- **DV-08** (box plots, per-source coverage consistency) — `fiveNumberSummary` already returns `n=0` for empty input (a free refusal), orders by volume never a computed "consistency score," client-side computable from data the analysis window already has. Ship with a mandatory (not optional) one-line plain-language caption per invariant #9.
- **DV-09** (tone-over-time small multiples per source) — descriptive only, no ranking, carries the VADER English-lexicon caveat forward; sequence *after* DV-02 so it's legible in absolute terms from day one.
- **DV-07** (publishing-rhythm heatmap) — **dies as scoped** for this pass; see §9.

---

## 5. The Observatory — the app's most distinctive asset

The Observatory's honesty architecture is the best-engineered piece of the visualisation layer, and it needs a layout fix, not a rules change. `oosky.js`'s one-measure-per-channel discipline (angle=category+jitter disclosed as meaningless, radius=one labelled measure, size=mentions via `sqrtAreaScale` with a reference-star legend, colour=language/trend never alone) and its two refusals — log-mode below one decade (`LOG_MIN_SPAN=10` against a measured `distinct_sources` ceiling of 7), and the unplaced-outer-band for zero-valued galaxies, kept at its own radius (`R_UNPLACED`) distinct from the nebula band after a documented earlier bug merged them visually — are real, tested (`test_observatory_ui.py`, `oosky_node_test.js`), and correctly triggered. **None of the five "may not regress" properties named in invariant #31 need to change.**

What needs to change is that the app's own code comment calls the ranked table "the canonical view… rendered in full beside the sky," and the shipped layout inverts that: `#sky-stage` (canvas) → `#sky-readout` → `#sky-legend` → `#sky-caveat` → `#sky-table` in DOM order (`index.html` ~1368–1385) means at 1440×900 the canvas alone runs from y≈267 past the visible bottom (still uncut at y≈846) — the canonical table, both legends, and the scale-mode disclosure are **entirely below the fold** on first paint (`/home/user/oo-ui/out/surface-observatory.png`). The redundant lens gets 100% of the above-the-fold view; the canonical one gets 0%.

**DV-03** (invariant panel: SHIP_WITH_CHANGES): lay canvas and a side panel (legend + scale disclosure + the *complete*, scrollable ranked table) side by side at ≥1100px, stacking only at narrower widths — with the colour/size legend moved to sit directly under the already-above-the-canvas measure/lens `<select>` controls even in the stacked case. **The invariant panel's hard requirement**: the side panel must contain every row, never a "preview" subset — scrolling is not truncating, and invariant #31(c) forbids truncation outright. Re-run `test_observatory_ui.py`/`oosky_node_test.js` after the layout change, since a width change feeds `_obsOuterFor`'s sizing and therefore `rOuter`.

**obs-1** folds into the consolidated net-coach fix (§3/§7): the popup clips exactly the clause disclosing that angle is meaningless — the single load-bearing honesty sentence for the chart's most visually prominent channel, clipped identically across ink/light/aubergine/pt/terminal/mint and two EN captures (8/8 sampled).

**obs-2/obs-3**: a compact, translated legend for the two currently-unkeyed channels (colour=language, hollow=no-qualifying-data) and an inline caption on the honest non-round outer ring (2/4/6/7, never padded to 8) — both purely additive labels for already-drawn, already-honest channels, never a new composite signal.

**A genuinely good, low-risk interaction idea, not yet a formal proposal**: bridge the redundant sky and the canonical table by reusing state that already exists (`_obs.view.focus`, `rankedGalaxies`) — clicking a table row pans/pulses the corresponding star; hovering/selecting a star scrolls and highlights its table row. This would make the two views feel like one instrument instead of two documents sharing data, without adding any new signal.

Determinism itself is confirmed, not assumed: identical star positions, wedge geometry, and relative sizes across ink/light/aubergine/pt/terminal/mint/two-EN renders — only hue changes with the active theme's accent.

---

## 6. Motion, micro-interaction and craft — the system, and where motion is forbidden

**Where motion is currently absent and should stay cheap to add:** 14 `transition:` declarations across the whole 1,718-line file; only 8 `@keyframes`. **CTM-P9** names duration/easing tokens without changing feel (everything already routes through the global `prefers-reduced-motion` kill switch). **CTM-P11**/**CD-P48** wire an already-defined, unused `slidein` keyframe into `ooSubtabs`' own `select()` path — because it lives in the one shared subtab component (invariant #18), every current and future adopter (Insights, Settings, the corpus window, Home families, the task-manager window) gets the polish from one change, capped short (~150ms).

**Where craft additions are safe and small:**
- `CD-P6` hover elevation on cards, guarded by `@media (hover:hover)` and reduced-motion.
- `CD-P34` a soft focus glow layered *outside* the existing hard `:focus-visible` outline — must never weaken the Contrast theme's WCAG-driven outline underneath it.
- `CD-P32` a flash on a live-polled number's real change — must gate strictly on `old !== new`, never on the poll tick firing, or it fabricates activity that didn't happen.
- `CD-P26` a one-time, reduced-motion-gated blink on the brand mark's first mount, and `CD-P27` a loading motif reusing the grid-iris silhouette — both must keep the mark's exact pointed-oval + grid-iris geometry (invariant #5) and, for P27, stay visually and contextually distinct from the real mark so #5's "one brand mark" identity stays singular.
- `CD-P31` a one-time stroke-dash draw-in reveal on first chart paint — must exclude n<10 bar-mode charts (which need their own equivalent, e.g. a bar grow-in) and must be proven not to re-fire on pan/zoom/hover redraws before merging into the shared `ooChart` toolkit.

**Where motion is forbidden or load-bearing-fragile, named explicitly:**
1. **The Observatory must stay static when idle** (invariant #31). `CD-P33`'s hover/interaction-triggered effect is fine only if it is strictly event-driven with zero per-frame idle cost — no `requestAnimationFrame` loop while nothing is happening. This is the one property a naive implementation of any Observatory polish could accidentally violate.
2. **`CD-P10` (bounded coachmark pulse)**: any auto-playing, looping animation whose total run time exceeds ~5s needs a stop mechanism per WCAG 2.2.2 — the coachmark's `coachpulse` keyframe sits right on this boundary and needs a specific check beyond the standard reduced-motion gate, not a substitute for fixing the underlying net-coach placement bug (§3).
3. **DOM order must match visual order (WCAG 1.3.2)** for any reorder done by taste rather than necessity: `CTM-P6`'s flip-card-back reorder (plain-language explanation before the caveat/Method blocks — matching invariant #9's "plain words first, exact math beneath") and `DV-03`'s Observatory two-column layout must both reorder the actual DOM, never repaint via CSS `order`/grid-area alone, or keyboard tab order and screen-reader reading order desync from what's on screen.
4. **Skeleton loaders (`CD-P9`, `CD-P22`) and disabled-looking controls (`CD-P10`, `L2`) are visual-only by default** — a screen-reader user gets nothing unless the state is carried by a real `disabled`/`aria-disabled` attribute or an `aria-busy`/`role="status"` region, and every skeleton must resolve deterministically to real content or an honest empty state, never linger — the app is careful elsewhere about distinguishing "loading" from "genuinely empty," and a lingering skeleton would blur exactly that line.

---

## 7. The catalogue

*Every row below carries three rulings in order: **Invariant/non-negotiable panel** · **Feasibility panel** · **Accessibility panel**. Where the accessibility panel's output was not available for an item (its per-item screening was truncated after `P1-DS`), the column says "not screened — apply general note ①–⑦" (§6/this note) rather than inventing a verdict. Consolidated duplicates are shown once, with absorbed IDs noted. `CD-P*` descriptions are reconstructed from the screening panels' own reasoning, since the originating "craft-and-delight" audit's full write-ups were not included in the material available to this synthesis — flagged here per the project's own "say what you did not reach" rule.*

### 7.1 Design-system tokens

| ID | Surface | Change | Why | Effort | New strings ×12 | Invariant | Feasibility | Accessibility |
|---|---|---|---|---|---|---|---|---|
| **DS-P1** | app.css `:root` | `--line:var(--border)`, 41 sites | 41 SPA sites silently render `0px none`; confirmed live on `#oo-tip`, `#net-coach`, `.gw-dot` | S | 0 | SHIP | SHIP | SHIP (P1-DS: low-vision win) |
| **DS-P2** (canonical; absorbs DS-P3, CTM-P4, CD-P1, CD-P44, CD-P46) | app-wide, 150 sites | 9-token 1.125-ratio type scale (§2.2 table) | Matches 8/24 existing values within 0.5px incl. PRH-32's own h2 | L | 0 | SHIP — adopt as canonical | SHIP_WITH_CHANGES — one migration, full 17-theme×12-locale screenshot diff before merge | not screened — apply ④ |
| **DS-P4** | app.css, 9 chip selectors | One `.chip` base + modifiers | 9 components, 4 radii, 6 paddings for one atom | M | 0 | SHIP | SHIP_WITH_CHANGES — keep `.ag-catchip`/`fam-chip${isRing...}` literal class strings (test lines 3481/5314) | not screened |
| **DS-P5** | Home vs. Library stat numbers | Merge or document the 15px/24px divergence | 60% size delta, no comment explaining it (unlike the file's usual practice) | S | 0 | SHIP | SHIP_WITH_CHANGES — default to documenting, not merging, unless maintainer asks | not screened |
| **DS-P6** (canonical; absorbed by/consumed by CD-P4, CD-P8, CD-P47, W2) | app.css, 19 z-index sites | 12-token named z-scale (§2.4) preserving existing order | .sidebar/.vitals-pop and .skip-link/#net-flash/#toast collide by coincidence | M | 0 | SHIP — adopt as canonical | SHIP — **must update test_repo_invariants.py:3779's literal string in the same PR** | not screened |
| **DS-P7** (folds into CD-P29) | `#oo-tip`, `#net-coach`, consent popup, slider thumb | Route floating shadows through `--shadow`/a new `--shadow-float` tier | `--shadow` is already correctly theme-tinted; ~9 sites bypass it with literal black | S | 0 | SHIP | SHIP | not screened |
| **DS-P8** (canonical; absorbs insights-1, CTM-P8) | `.row>div`, `.seg-toggle button` | `flex:1 1 auto` + content-safe `min-width`; codify the convention | Live, reproduced overlap ("Super-groups" under "Mind-map") in Ink and German | S | 0 | SHIP — ship once | SHIP — one of the strongest confirmed-cheap-real fixes in the catalogue | not screened |

### 7.2 Home / Feed / Insights / Search / Observatory (critique-flagship)

| ID | Surface | Change | Why | Effort | New strings | Invariant | Feasibility | Accessibility |
|---|---|---|---|---|---|---|---|---|
| **home-1** (canonical; absorbs obs-1, W2-netcoach half, An3, feed-3, search-3) | app-wide `#net-coach` | Collision-aware placement extending `_placeCoach()`'s existing union-rect | Clips real content/navigation/caveats on 100% of sampled surfaces | M | 0 | SHIP_WITH_CHANGES — must never shift top-bar footprints (#3), never cover the airplane toggle, RTL-correct | SHIP_WITH_CHANGES — this is an extension of a tested function, not new work; consolidate all six occurrences into one PR | not screened |
| **home-2** | Home flip-card back | Scrollable `.mc` with fade-mask cue | Method text clips mid-sentence with zero scroll affordance | S | 0 | SHIP — reinforces #23 | SHIP | ② applies (ensure focus/AT order matches visual scroll) |
| **home-3** | Home subtab bar | Fixed static order + horizontal scroll, inside `ooSubtabs` | Same 9 labels wrap into 2 rows differently across 3 screenshots | M | 0 | SHIP_WITH_CHANGES — implement inside ooSubtabs (#18) | SHIP_WITH_CHANGES — verify it's already an ooSubtabs adopter first | ⑥ applies (reuse roving-tabindex pattern) |
| **feed-1** | Feed byline | Translated `date_unknown` fallback | A missing date silently shortens the byline instead of degrading loudly | S | 1 | SHIP | SHIP | not screened |
| **feed-2** | Feed Order row | One consistent pill grammar for 4 controls | 1 filled pill + 3 bare text links in one logical row | S | 0 | SHIP | SHIP | not screened |
| **insights-2** | Insights Explore | Honest "not enough data" line under 2 bare headings | 6/6 sampled screenshots end with zero content and no fallback | S | 2 | SHIP — plain factual, never a score | SHIP | not screened |
| **insights-3** | Insights tag cloud | Re-rank "THEMES 16" eyebrow above its own items | Tag items render bolder/larger than the label introducing them (weight+size+colour token, not uppercase) | S | 0 | SHIP | SHIP | not screened |
| **search-1** | Search toolbar | Collapse 7/9 buttons into "Export & tools ▾" | 9 near-identical buttons regardless of use frequency | M | 1 (menu label, feasibility-panel correction) | SHIP — preserve #17 dots in menu | SHIP_WITH_CHANGES — add the missing string; verify axe/keyboard nav | not screened |
| **search-2** | Search result rows | One consistent action-row style for 5 mixed affordances | 4 different styles × 50 results/page | M | 0 | SHIP | SHIP_WITH_CHANGES — verify DE/AR wrap at 1024px | not screened |
| **obs-2** | Observatory | Legend for colour (language) + hollow-marker (no data) | Two channels currently unkeyed on screen | M | 2 | SHIP — labels only, no new signal | SHIP | not screened |
| **obs-3** | Observatory outer ring | Inline caption on the honest non-round tick set | 2/4/6/7 reads as a quirk without explanation | S | 1 | SHIP — reinforces the honest scale | SHIP | not screened |

### 7.3 Secondary surfaces (critique-secondary)

| ID | Surface | Change | Why | Effort | New strings | Invariant | Feasibility | Accessibility |
|---|---|---|---|---|---|---|---|---|
| **W1** | World map | Widen the fill-colour gradient | All filled countries render one uniform mid-blue despite a 1→237 legend | S | 0 | SHIP_WITH_CHANGES — must keep a hover-exposed exact value so colour isn't the sole read | SHIP | not screened |
| **G1** | Governments Countries/Compare/Map | Populated "not loaded" tile vs. bare `<select>` | 3 subtabs give zero visual signal of state | M | ~1-2 (unconfirmed) | SHIP | SHIP_WITH_CHANGES — confirm whether tile copy needs new keys | not screened |
| **G2** | Governments Statistics | Relocate/re-skin the 6-form raw fetch console | Direct invariant-#8 hit ("data, never plumbing") | L | 0 | SHIP_WITH_CHANGES — prefer relocation to Settings→Advanced, keep an in-place link | SHIP_WITH_CHANGES — feasibility panel prefers the cheaper in-place restyle over full relocation | not screened |
| **G3** | Governments Law table | Cap max-width or add a column | ~40% of a 1920px viewport left empty | S | 0 | SHIP | SHIP | not screened |
| **A1** | Agenda month grid | Wrap instead of ellipsis-truncate pills | 7/7 titles truncated; 3 different events share the identical truncated prefix | M | 0 | SHIP | SHIP_WITH_CHANGES — verify Week/Year/Decade views | not screened |
| **A2**/**CD-P23** (canonical: CD-P23's always-visible spec) | Agenda dots | Always-visible legend for moon-phase glyphs | Unlabelled anywhere; hover-only would be strictly less discoverable for equal cost | S | 4 | SHIP | SHIP_WITH_CHANGES — merge the two proposals, ship the always-visible version | not screened |
| **A3** | Agenda | Card boundary for "no fixed day" events | Reads as a footnote, is real disclosed data | S | 0 | SHIP — real data, not plumbing | SHIP | not screened |
| **I1** | Indices | Filter-aware empty-state copy | All continent/tag filters render byte-identical panel body | S | ~1-2 | SHIP | SHIP | not screened |
| **I2** | Indices mobile | Horizontal-scroll tab strip via ooSubtabs | 7 tabs wrap into 4 uneven lines at 375px | S | 0 | SHIP_WITH_CHANGES — implement through ooSubtabs (#18) | SHIP | ⑥ applies |
| **I3** | Indices RTL | Regression-guard note, not code | Best RTL render sampled; protect while touching I1/I2 | — | 0 | SHIP | SHIP — add to the visual-regression checklist | not screened |
| **C1** | Commodities | Card boundary, price chart vs. Minerals-supply | Copy stresses the two datasets aren't comparable; layout doesn't | S | 0 | SHIP | SHIP | not screened |
| **C2** | Commodities chart | In-chart annotation for the bar↔line mark-switch | 3 mark grammars visible at once, individually correct, collectively busy | M | 0 | SHIP — must respect #16's no-fabricated-smoothing rule | SHIP_WITH_CHANGES — prototype scoped to this panel before generalizing into ooChart | not screened |
| **C3** | Commodities chart | Tick-label legibility polish | Uneven decimals hard to scan, computation itself stays honest | S | 0 | SHIP — reinforces #16, doesn't touch the math | SHIP | not screened |
| **L1** (canonical over CD-P24) | Library stat row | Unify "—"/"0" glyph for parallel metrics | Two glyphs for the same "nothing yet" concept in one row | S | 0 | SHIP | SHIP_WITH_CHANGES — reconcile with CD-P24, prefer the simpler same-glyph fix | not screened |
| **L2** | Library Activity | Grey out range toggles on empty cards | Dead controls dressed as live ones next to the one live card | S | 0 | SHIP | SHIP | ③ applies (needs a real `disabled` attribute, not visual-only) |
| **L3** | Library Tracked subtab | Fold 4 empty cards into Activity's empty-state row (not hide the tab) | Single emptiest screen sampled; hiding risks reading as a missing feature | M | 0 | SHIP_WITH_CHANGES — fold, don't hide | SHIP_WITH_CHANGES — same recommendation, maintainer call on Wikipedia/Law tracking's prominence | not screened |
| **S2** | Settings Advanced | Live counts on collapsed section headers | 3,618/241/29-row sections look uniformly lightweight until opened | S | 0 (counts already computed) | SHIP | SHIP | not screened |
| **S3** | Settings | Promote Sources/Diagnostics to top-level tabs (stay in Settings) | Substantial, frequently-used features buried under "Advanced" | M | yes (2 tab labels) | SHIP — compliant with #8 (stays in Settings) | SHIP_WITH_CHANGES — ship with a redirect/notice; grep for hardcoded-location assertions first | not screened |
| **An1** | Analyze | Fix hardcoded-English empty-state hint | Verbatim English leak in DE/FR/ES screenshots beside a translated neighbour | S | 0 (closes existing gap) | SHIP — mandatory under the ×12 rule | SHIP | not screened |
| **An2** | Analyze | Hide the 9-link export bar until a result exists | Controls precede content on first paint | S | 0 | SHIP | SHIP | not screened |
| **Cu1** | Custody | Separate settings block from action block | Session-level prefs and per-item actions share identical visual weight | S | 0 | SHIP | SHIP | not screened |
| **Cu2** | Custody | Plain-language primary label for "plaintext-0600" badge | Unix jargon standing in for "your signing key is unencrypted" for an at-risk-journalist audience | S | copy re-authored ×12 (treat as new-string cost) | SHIP — textbook use of #17 (plain label, jargon in hover) | SHIP_WITH_CHANGES — treat as ×12 translation work, not a free edit | not screened |
| **Cu3** | Custody | Visually distinguish "Anchor root" from 3 local-only buttons | One real network egress vs. three purely local actions, all four look identical today | S | 0 | SHIP — reinforces #14f | SHIP | not screened |
| **In1** | Integrity | Flip/expand pattern on card intros | Full re-read every visit; the constraint is the finding | M | 0 | SHIP_WITH_CHANGES — the visible summary must state the actual caveat verbatim, only elaboration may hide behind expand | SHIP_WITH_CHANGES — same constraint (informed-consent non-negotiable) | not screened |
| **In2** | Integrity | Fill-state counts in card headings | Currently buried at the bottom of each card | S | 0 | SHIP | SHIP | not screened |
| **H1** | Help | Collapse the duplicate TOC into one hierarchy | Two non-matching navigation systems visible in one screenshot | M | 0 | SHIP | SHIP_WITH_CHANGES — QA every existing anchor still resolves | not screened |
| **H2** | Help | Split the 167K-char monolith into per-topic panels | Also independently fixes H1's dual-nav problem | L | 0 | SHIP | SHIP_WITH_CHANGES — scope to routing/anchoring first; preserve external anchors via aliases | not screened |
| **H3** (chrome-translation branch only) | Help left rail | Translate titles/descriptions now | Closes an existing ×12-locale gap; the rail's chrome, not the 167K-char body | M | translate existing chrome strings | SHIP_WITH_CHANGES — this portion is mandatory, not optional; escalate the body-translation question to OPEN_QUEUE.md | SHIP_WITH_CHANGES — same split; full-body branch rejected separately (§9) | not screened |

### 7.4 Dataviz (DV-01…DV-09, minus DV-07 — see §9)

| ID | Surface | Change | Why | Effort | New strings | Invariant | Feasibility | Accessibility |
|---|---|---|---|---|---|---|---|---|
| **DV-01** | ooChart canvas | Density-aware dash/marker (project by time, not path length) | Dash+marker (the ramp's redundancy channels) both fail exactly where the ramp's own 1.00:1 worst case needs them | M | 0 | SHIP — reinforces "colour never the only signal" | SHIP_WITH_CHANGES — benchmark against the existing per-point loop before merging into the shared toolkit | not screened |
| **DV-02** | `smallMultiplesSvg` | Add real numeric gridline labels (reuse `honestTicks`/`_axisNum`) | Sibling `dashChartSvg` on the same screen already labels; this doesn't | S | 0 | SHIP | SHIP — very low risk, reuses an existing formatter | not screened |
| **DV-03** | Observatory | Two-column layout: canvas + full (never-truncated) side panel | Code's own comment calls the table canonical; layout gives it 0% of the fold | M | 0 | SHIP_WITH_CHANGES — panel must hold every row, "preview" language forbidden | SHIP_WITH_CHANGES — re-run the Observatory test suite (width feeds `rOuter`) | not screened |
| **DV-04** | Mind-map | Shape-based secondary channel for seed vs. supergroup nodes | Both currently share `var(--ok)`, distinguished only by font-weight | S | 0 | SHIP | SHIP_WITH_CHANGES — verify against a real populated render first (unconfirmed this session) | not screened |
| **DV-05** | Analyze Sentiment | Render VADER breakdown via the existing `_figBars` | Same numbers/caveat/n, just as bars instead of 3 text rows | S | 0 | SHIP — zero new honesty surface | SHIP | not screened |
| **DV-06** | World map | Wire `ooViz.symbolRadii` into level-indicator maps | Maintainer's own §5B ruling names this as correct; the primitive exists and is unused | M | 0 | SHIP — implements an existing ruling | SHIP_WITH_CHANGES — cap radius per oosky's own precedent | not screened |
| **DV-08** | Analyze Sources | Box plots via `fiveNumberSummary` | Spread + n, never a computed "consistency score" | M | 0 | SHIP_WITH_CHANGES — make the plain-language caption mandatory | SHIP_WITH_CHANGES — confirm client-side computability | ⑦ applies (needs an accessible tabular fallback like `_figBars`) |
| **DV-09** | Analyze Sentiment/Sources | Tone-over-time small multiples per source | Descriptive only, no ranking; carries the VADER caveat forward | M | 0 | SHIP | SHIP_WITH_CHANGES — sequence after DV-02 | ⑦ applies |

### 7.5 Colour / type / motion (CTM-P1…P12)

| ID | Change | Why | Effort | New strings | Invariant | Feasibility | Accessibility |
|---|---|---|---|---|---|---|---|
| **CTM-P1** | Fix `.card.bk-undertold`'s literal `#6ea8fe` via `color-mix(in srgb, #6ea8fe 55%, var(--fg) 45%)` | Measured **2.28–2.42:1** against 5 light-theme panels (need 4.5:1); 1.04:1 against Slate's own accent | S | 0 | SHIP | SHIP | SHIP-class (real AA failure) |
| **CTM-P2** | Automated AA gate for future theme authorship | Prevents a repeat of CTM-P1's exact failure mode | S | 0 | SHIP — generalizes an existing discipline | SHIP | not screened |
| **CTM-P3** | Name 3 theme tiers (Reference/Distinct/Mood-dial) via #17 hover | 9 of 17 dark themes differ only below 11% lightness — a range where hue discrimination collapses | S | 3 | SHIP — catalog never shrinks (#12) | SHIP | not screened |
| **CTM-P5** | `:lang(ar){letter-spacing:normal}` | Tracking breaks Arabic letter-joining; app already documents the uppercase no-op but never fixed tracking | S | 0 | SHIP — correctness, not style | SHIP | not screened |
| **CTM-P6** | Reorder flip-card back: plain language before caveat/Method | Matches invariant #9's "plain words first"; caveat stays present per #23's presence-only test | S | 0 | SHIP — reinforces #9/#23 | SHIP — verified against test's actual assertions (order-agnostic) | ② applies — reorder DOM, not just CSS |
| **CTM-P7** (canonical; merges CD-P15) | Extend `tabular-nums` beyond its current 8 sites | Live-updating numbers (Library tiles, storage bytes, Search PUBLISHED column) currently jitter | S | 0 | SHIP | SHIP | not screened |
| **CTM-P9** | Named duration/easing tokens | 14 transitions, 11 durations, 2 easings, no shared token | M | 0 | SHIP — compatible with reduced-motion kill switch | SHIP_WITH_CHANGES — grep for any test asserting a specific duration first | ⑤ applies |
| **CTM-P10** | Bound the coachmark's infinite pulse to a fixed iteration count | Independent value from the placement fix; doesn't resolve home-1 by itself | S | 0 | SHIP | SHIP | ⑤ applies (WCAG 2.2.2, >5s auto-loop) |
| **CTM-P11** (= CD-P48) | Underline-transition inside `ooSubtabs` itself | One change, all 5+ adopters benefit | S | 0 | SHIP — correct shared-component use of #18 | SHIP | not screened |
| **CTM-P12** | FLIP-technique reorder animation on the shared `_jobRow` renderer | Task-manager reorder currently has no transition | M | 0 | SHIP | SHIP_WITH_CHANGES — verify controls stay clickable during/after animation (no pointer-events lockout) | not screened |

### 7.6 Craft & delight (CD-P2…CD-P48, excluding those folded above; descriptions reconstructed from screening reasoning — see note at top of §7)

| ID | Change (reconstructed) | Effort | New strings | Invariant | Feasibility | Accessibility |
|---|---|---|---|---|---|---|
| CD-P2 | Additive `--space-*` tokens, incremental migration | M | 0 | SHIP | SHIP | not screened |
| CD-P3 | Consolidate 99px/999px radius literals | S | 0 | SHIP | SHIP | not screened |
| CD-P6 | Card hover elevation, `hover:hover` + reduced-motion guarded | S | 0 | SHIP | SHIP | not screened |
| CD-P7 | Table zebra striping via `--panel2` | S | 0 | SHIP | SHIP | not screened |
| CD-P8 | Sticky table headers | S | 0 | SHIP_WITH_CHANGES — use DS-P6's named z-index | SHIP | not screened |
| CD-P9 | Skeleton loaders (66 call sites) | L | 0 | SHIP_WITH_CHANGES — must resolve to real content or honest empty state, never linger | SHIP_WITH_CHANGES — scope v1 to Insights/Analysis/Agenda only | ③ applies |
| CD-P10 | Disabled-state styling parity, buttons vs. other form controls | S | 0 | SHIP | SHIP | ③ applies |
| CD-P11 | "Added" success flash | S | 0 | SHIP_WITH_CHANGES — gate strictly on real API resolution, never the click alone | SHIP_WITH_CHANGES — same | not screened |
| CD-P12 | Caret-color token | S | 0 | SHIP | SHIP | not screened |
| CD-P13 | Keyboard-shortcut hint in empty/unfocused field | S | 1 | SHIP | SHIP | not screened |
| CD-P14 | Larger hit-area/hover on existing affordance | S | 0 | SHIP | SHIP | not screened |
| CD-P16 | Padding increase on search rows | S | 0 | SHIP | SHIP | not screened |
| CD-P17 | Remove manual "(?)" text in favour of the #17 convention on 2 Custody labels | S | 0 | SHIP_WITH_CHANGES — verify the hover convention is actually wired first | SHIP_WITH_CHANGES — same | ① applies |
| CD-P18/CD-P19 (canonical: CD-P18) | Hatch/dash pattern for empty stat values (reuse `--fig-gap`) | M | 0 | SHIP_WITH_CHANGES — must not blur absence-vs-zero | SHIP_WITH_CHANGES — use the existing `--fig-gap` convention, not a plain dashed line | not screened |
| CD-P20 | Inline teaching example reusing existing placeholder text | S | 3 | SHIP | SHIP | not screened |
| CD-P21 | Placeholder visual for pre-consent state | S | 0 | SHIP_WITH_CHANGES — must not imply background activity | SHIP_WITH_CHANGES — same | not screened |
| CD-P22 | Skeleton rows on CD-P9's shared component | S | 0 | SHIP | SHIP — build on P9 | ③ applies |
| CD-P25 | Light/dark-aware favicon via media query | S | 0 | SHIP_WITH_CHANGES — brand-mark geometry must stay byte-identical (#5) | SHIP_WITH_CHANGES — spot-check real browser support | not screened |
| CD-P26 | One-time reduced-motion-gated brand-mark blink | S | 0 | SHIP | SHIP_WITH_CHANGES — fire once per session, not per SPA route change | ⑤ applies |
| CD-P27 | Grid-iris loading motif | S | 0 | SHIP_WITH_CHANGES — must stay distinct from the real mark (#5) | SHIP_WITH_CHANGES — check legibility at deployed chip size | not screened |
| CD-P28 | Nav icon redesign, existing viewBox/stroke conventions | S | 0 | SHIP | SHIP | not screened |
| CD-P29 (canonical, absorbs DS-P7) | Retint `--shadow` app-wide via `color-mix()` | M | 0 | SHIP | SHIP_WITH_CHANGES — verify no theme's tint drifts toward `--err`/`--warn` | not screened |
| CD-P30 | Inline SVG/CSS-gradient texture, 2 themes | S | 0 | SHIP — no external asset | SHIP_WITH_CHANGES — re-verify text contrast at chosen opacity | not screened |
| CD-P31 | One-time stroke-dash chart draw-in | M | 0 | SHIP_WITH_CHANGES — exclude n<10 bar-mode, give it an equivalent | SHIP_WITH_CHANGES — prove no re-fire on pan/zoom/hover | not screened |
| CD-P32 | Flash on live-polled numeric change | M | 0 | SHIP_WITH_CHANGES — gate on real delta only | SHIP_WITH_CHANGES — same | not screened |
| CD-P33 | Observatory hover/interaction effect | S | 0 | SHIP — must not violate #31's static-when-idle | SHIP_WITH_CHANGES — confirm zero per-frame idle cost | ⑤ applies |
| CD-P34 | Soft focus glow outside existing hard outline | S | 0 | SHIP | SHIP | SHIP-class (additive to existing a11y rule) |
| CD-P35 | Home stat-strip spacing/grouping | S | 0 | SHIP | SHIP | not screened |
| CD-P36 | Demote redundant filled buttons to outline style | S | 0 | SHIP | SHIP_WITH_CHANGES — grep for JS reading button class as behavior first | not screened |
| CD-P37 | Reader-page theme sync with all 17 SPA themes (verified: today branches only on `prefers-color-scheme`) | M | 0 | SHIP | SHIP_WITH_CHANGES — build mapping from already-verified token pairs; match SPA's FOUC-avoidance | not screened |
| CD-P38 | Font-size stepper in reader (Insights slider precedent) | S | 1-2 | SHIP_WITH_CHANGES — translate the control's label ×12 | SHIP | not screened |
| CD-P39 | rAF-throttled scroll/orientation indicator | S | 0 | SHIP | SHIP | not screened |
| CD-P40 | Server-computed honest "≈" figure | S | 1 | SHIP — reinforces honesty-by-construction | SHIP | not screened |
| CD-P41 | Weight/background addition to reader's `.rtabs` | S | 0 | SHIP | SHIP | not screened |
| CD-P42 | More visual distinction, source box vs. app-deduced box, via weight not only colour | S | 0 | SHIP — reinforces colour-never-sole-signal | SHIP | not screened |
| CD-P43 | Shape/icon cue on the near-duplicate caveat box | S | 0 | SHIP — reinforces colour-never-sole-signal | SHIP | not screened |
| CD-P45 | Line-height increase on preview text | S | 0 | SHIP | SHIP_WITH_CHANGES — check card min-heights | not screened |
| CD-P47 | Sticky sub-tab bars via ooSubtabs | S | 0 | SHIP_WITH_CHANGES — implement as an ooSubtabs option (#18), use the named z-scale | SHIP_WITH_CHANGES — coordinate stacking with net-coach/consent | not screened |

---

## 8. The programme

### 8a. Ten cheapest wins (ship first, independently, no sequencing dependency)
1. **DS-P1** — `--line:var(--border)`. One line, zero regression risk, fixes 41 sites.
2. **DV-02** — label `smallMultiplesSvg`'s gridlines with the formatter that already exists one file over.
3. **DS-P8** (= insights-1 = CTM-P8) — `.seg-toggle`/`.row>div` overflow fix. Live, reproduced, two-selector patch.
4. **CTM-P1** — fix the `#6ea8fe` contrast failure. A real, measured AA defect.
5. **feed-1** — translated `date_unknown` byline fallback.
6. **An1** — fix the hardcoded-English Analyze empty-state string.
7. **CTM-P5** — `:lang(ar){letter-spacing:normal}`.
8. **DS-P7 + CD-P29** — shadow retint (ship together; both value substitutions).
9. **CD-P3** — 99px/999px radius consolidation.
10. **A3** / **C1** — the two cheapest card-boundary additions (Agenda's "no fixed day" strip, Commodities' Minerals-supply separation).

### 8b. Ten changes that most change how the app *feels*
1. **home-1** (consolidated net-coach fix) — one root-cause fix that resolves five surfaces' worth of occlusion findings simultaneously (Home, Feed, Search, Insights, Analyze, Observatory, World map).
2. **DS-P2** type-scale migration — 150 declarations, 24 values → 9 tokens; the single change most responsible for the app reading as *designed* rather than *accreted*.
3. **DV-03** — Observatory's canonical table above the fold. The app's most distinctive surface finally shows its own stated priorities.
4. **DS-P4** chip consolidation — 9 components → 1 base; visibly cleans up Home, Agenda, and every badge/pill surface at once.
5. **G2** — remove the raw fetch console from Governments' primary data tab; the sharpest "plumbing in a data surface" fix in the catalogue.
6. **S2 + S3** — Settings stops reading as a control panel wearing a settings label.
7. **search-1** — the 9-button toolbar becomes a primary pair + one disclosure menu.
8. **A1** — Agenda's month grid stops being unscannable.
9. **H1 + H2** — Help becomes a designed documentation surface instead of a markdown file with a nav bolted on.
10. **DS-P6** z-index scale — invisible to a user directly, but it's what lets every other stacking-related fix in this catalogue (net-coach, sticky headers, sub-tab bars, consent popups) be implemented once, coherently, instead of as N more one-off literals.

### 8c. The token migration that unlocks the rest
Land in this order, because each step reduces the regression surface of the next:
1. **`--line` alias (DS-P1)** — zero-risk, ships alone, first.
2. **Z-index scale (DS-P6)**, updating `test_repo_invariants.py:3779` in the same commit — small, mechanical, unblocks every stacking-dependent proposal (net-coach consolidation, sticky headers CD-P8/CD-P47, W2).
3. **Shadow retint (CD-P29 + DS-P7)** — depends on nothing, but is naturally paired with the z-index pass since both touch "how floating chrome looks."
4. **The consolidated net-coach placement fix (home-1)** — now that stacking is named, extend `_placeCoach()`'s union-rect to cover stat-strips, intro paragraphs, subtab bars, and open-modal backdrops in one PR, tested once for RTL.
5. **Type-scale migration (DS-P2)**, full 17-theme × 12-locale screenshot diff — the largest single pass (627 declarations touched across font-size/radius/padding/gap/margin/shadow/z-index/transition once counted together), but every category is a value swap with near-zero perceptual delta per §2.2's table. This is the one migration everything else in the "consistency debt" category (chip consolidation, stat-number unification, CD-P44/46) should be sequenced *after*, per the feasibility panel's explicit requirement.
6. **Chip consolidation (DS-P4)** and **stat-number unification (DS-P5)** — cosmetic consolidation, now riding on stable type/space tokens.

Everything in §8a can and should ship in parallel with this sequence; nothing in §8a touches the same selectors as the migration.

---

## 9. Rejected proposals and why

Three items die in their originally-proposed form. All three are rejected on **feasibility/scope grounds, not ethics** — no invariant panel rejected anything outright — which matters: it means each comes back in a smaller, real form rather than disappearing.

**S1 — global cross-Settings search box.** *Invariant panel: SHIP. Feasibility panel: REJECT.* The reason is proportionality, not correctness: an index over 68+ controls across 12 tabs and 10 nested Advanced sections that must be hand-maintained as controls are added, plus ×12-locale diacritic/RTL-aware matching, is a new perpetually-drifting subsystem in an already 29,000-line/18-module frontend — and **S2 (live counts on collapsed headers) + S3 (promote Sources/Diagnostics to top-level tabs)** address the bulk of the same discoverability problem at S/M effort with no ongoing sync burden. **Amended form:** ship S2+S3 first; revisit a full settings-search index only if that combination proves insufficient, and if so, generate the index at build/test time from the DOM structure (assertion-covered) rather than hand-maintained, so it cannot silently drift.

**DV-07 — publishing-rhythm heatmap (day-of-week × hour-of-day).** *Invariant panel: SHIP (raw counts, colour redundant with an exact on-hover number, explicit n/date-range caveat — fully honesty-compliant as specified). Feasibility panel: REJECT. Accessibility panel: also flags this as the one proposal whose own description makes the core data hover-only with colour as the sole always-on channel* — a structural accessibility problem, not a fixable detail. The feasibility rejection is scope: this is not a CSS/JS/markup change like everything else in the catalogue — `bin2D` is pure client-side geometry, but the counts must come from a **new backend aggregation endpoint**, plus a new UI subtab, plus full ×12 i18n for a brand-new feature. A feature-design project doesn't belong in a visual-fix pass. **Amended form:** spin out as a separate product/feature ticket with its own backend design review; if greenlit later, (a) the sparse-data date-range+n caveat must be load-bearing from day one, not retrofitted, and (b) the accessibility panel's structural objection must be resolved at design time — every cell's exact count must be reachable without a hover (e.g. a real accessible grid/table, matching the `_figBars` sr-table pattern), not layered on afterward.

**H3 — the full-translation branch only** (translating Help's entire 167,022-character body across 12 locales). *Invariant panel and feasibility panel both accept the chrome-translation half of H3 (§3, §7.3) as mandatory; both reject the full-body-translation option specifically.* CLAUDE.md's own blanket "every user-facing string ships ×12" rule technically covers this content, but the feasibility panel is explicit about the ratio: translating ~2,000,000 characters (167,022 × 12) to fix a problem a one-sentence banner fixes just as well is a >100,000:1 cost-to-benefit ratio for the same stated goal. **Amended form:** ship only the translated banner stating Help's body is English-by-design (this is a genuine option, already in H3's own proposal, and already ×12-cheap); record the larger "translate the body vs. formally declare an exception" question as its own entry in `docs/ledger/OPEN_QUEUE.md` for maintainer ruling, since an agent cannot silently create a new exception to a written non-negotiable, and cannot silently commit the project to a 2M-character localization project either.

---

## 10. What could not be judged without a human eye or a real device

Recorded here rather than silently assumed, per the project's own "say what you did not reach" rule:

- **DV-04's mind-map colour collision** (seed vs. supergroup both `var(--ok)`) is source-verified only — no populated mind-map screenshot could be obtained this session; the shared host's memory dropped under 1GB partway through a live drive attempt (evidently fleet-wide parallel-audit pressure, not an app defect), and the session stopped rather than risk an OOM. Two negative-space screenshots exist (`/home/user/oo-ui/wf-e/dataviz/dv-mindmap-default.png`, `dv-wordcloud-default.png`) showing the toggle buttons render fully active-looking but no-op when no keyword has been explored — itself worth a small fix (disable them, or show an explore-first empty state), but the colour-collision claim needs a two-minute human check before being treated as confirmed.
- **The onboarding wizard's `.gw-dot`/`.gw-lang` broken-border claim (DS-P1)** is mechanism-confirmed (same invalid-`--line`-at-computed-value failure as the two directly-observed cases, `#oo-tip` and `#net-coach`) but no screenshot of the first-launch wizard exists in the corpus read for this synthesis — flagged as a gap in the screenshot set, not a confirmed render.
- **Agenda's moon-phase glyphs** (`app-agenda.js:1106–1138`, a locally-computed Meeus lunar-phase algorithm — genuinely lovely, honest, zero-network astronomy) render as thin monochrome line-art in the headless-Chromium capture rather than the colour emoji (🌑🌓🌕🌗) the source literally emits. Whether that is a sandbox font-fallback artifact or something a normal browser also does could not be determined from a screenshot alone — worth a real-device check before either fixing it or filing it as fine.
- **CD-P25 (light/dark-aware favicon via embedded media query)** and **CD-P27 (grid-iris loading motif at small chip size)** both carry proposal-stated caveats that browser-rendering support (favicon media queries) and legibility at deployed size (a ~14px chip) cannot be confirmed from source or a single-viewport screenshot — both need a real-browser spot-check before shipping as specified.
- **The Observatory's two-column reflow (DV-03)** changes `_obsOuterFor`'s width input and therefore `rOuter`; the existing resize-driven re-layout path should handle it, and the existing test suites (`test_observatory_ui.py`, `oosky_node_test.js`) should be re-run — but a human should visually confirm the side-by-side layout doesn't crowd the sky at in-between widths (1100–1300px) where neither the two-column nor the stacked treatment is clearly right.
- **Every animation/hover-feel item** (CD-P6's card elevation, CD-P26/31/32's one-time reveals, CTM-P9's retimed transitions) is, by nature, something a static screenshot cannot evaluate — these are correctly gated by the invariant/feasibility panels on mechanism (reduced-motion compliance, gating on real state changes) but their actual *feel* (is 150ms right? does the elevation read as "hoverable" or "jumpy"?) needs a live human pass, which this synthesis explicitly cannot substitute for.
- **The 8-skin GUI-alternatives gallery** (Settings → GUIs, invariant #30) was noted in CLAUDE.md as "BROWSER-UNVERIFIED" at ship time and does not appear in any screenshot read for this synthesis — it sits outside the 16-surface set this audit covered and should get its own pass before any of the above token/motion changes are assumed to propagate correctly into its 8 scoped skins.
- **Accessibility screening was incomplete for this catalogue.** The accessibility panel's per-item rulings were available only for its general cross-cutting notes (①–⑦, applied throughout §6–§7 where relevant) plus the start of its first item (`P1-DS`). No per-item accessibility verdict exists in the material available to this synthesis for the remaining ~100 proposals. Before any of §7's SHIP/SHIP_WITH_CHANGES rows land, they should get a genuine accessibility pass — not the "not screened" placeholder this report had to use in its place.