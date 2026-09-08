# 11 — Live visual / UI audit (2026-09-08)

> Commissioned as: *"a full visual audit / inspection … testing every aspect of the app's visual
> interface, including all the UI translation, responsiveness, and so forth. We need to test the UI and
> to suggest appealing visual additions, optimizations, tweaks, effects, and address all bugs and speed
> issues. We also need to address the app's current UI complexity … the app should automate more stuff,
> and it's for us to decide which stuff to automate so that it doesn't go in the way of our high ethical
> standards … For now, we don't code or fix anything. We're just analyzing and making plans."*
>
> **This is the complement to [`10_TRANSVERSAL_AUDIT_2026-09-08.md`](10_TRANSVERSAL_AUDIT_2026-09-08.md),
> which states in its own §9 that it launched no browser session and that every visual/i18n finding in it
> is static-source-level.** This audit ran the app. Nothing below is inferred from source alone: every
> finding was produced by, or re-derived against, a live Chromium session driving a real instance with a
> real corpus. **Report-only, per the commissioning instruction: nothing was fixed.**
>
> Companion documents produced in the same session:
> [`docs/design/UI_COMPLEXITY_AND_AUTOMATION_PLAN_2026-09-08.md`](../design/UI_COMPLEXITY_AND_AUTOMATION_PLAN_2026-09-08.md)
> and [`docs/design/VISUAL_DESIGN_PROGRAMME_2026-09-08.md`](../design/VISUAL_DESIGN_PROGRAMME_2026-09-08.md).
> Raw evidence: [`ui-visual-2026-09-08/`](ui-visual-2026-09-08/).

## 0. Method, and the honest scope

**The instrument.** Python 3.13 + the full `[analysis,dev]` dependency tree, Playwright 1.62 driving
bundled Chromium 141, against **19 live loopback instances of the app** booted for this audit:

| instance | state |
|---|---|
| ×17 | **STATE C** — a populated corpus seeded through the *real* `index_article` chokepoint (`scripts/ui_clickthrough_seed.py`): 453 articles, 3,618 sources, 2,342 keywords, 117 commodity prices, 129 mentioned dates, a 1,338-day span, 8 languages including Arabic and Chinese, a 3-article near-duplicate cluster, 4 provenance samples, 3 deduced future events |
| ×1 | **STATE A** — virgin + encrypted: the genuine first-launch flow (language → legal → passphrase → wizard) |
| ×1 | **STATE B** — unlocked, catalog-seeded, zero articles: every empty state |

Every instance was forced into **airplane mode** before any agent touched it, and every agent worked
under a written contract (`AGENT_BRIEF.md`) forbidding it to accept a consent popup, to click anything
destructive, or to edit a file in the repository. No egress occurred at any point.

**The fleet.** 7 orchestrated workflows, **60+ Sonnet 5 agents**, each substantive claim passed through
an independent adversarial verifier with its own browser session, told to default to refutation and to
re-derive the claim itself rather than reason about whether it sounded plausible. Output so far:
**1,697 screenshots and 786 raw JSON probe files** (549 MB, kept out of the repo; the curated evidence
subset is in `ui-visual-2026-09-08/evidence/`).

**What the orchestrating session measured with its own hands** (marked **[hand-verified]** below, and
not taken from any agent): the corrected 17-theme contrast sweep, the `#net-coach` occlusion matrix, the
`.seg-toggle` overlap reproduction across themes/locales/viewports, the boot resource and idle-poll
profile, the dual `/api/sources` handlers, the absence of HTTP compression, the design-token counts, and
`pytest tests/test_repo_invariants.py -k "ui_invariants or claude_md"` (3 passed).

### 0.1 A methodology defect this audit found in itself, and corrected

The shared harness's first contrast implementation composited an element's text against its **ancestors'**
backgrounds and excluded the element's **own** `background-color`. That scores a filled button's label
against the panel *behind* the button — inventing failures for filled controls and missing real ones.
**Two agents caught this independently** (the `custody` walk and the `first-run-journey` walk, the latter
hand-verifying two flagged buttons at a real 6.65:1). The harness was corrected mid-run
(`backdrop(el, includeSelf=true)`), and **every contrast number in this report comes from the corrected
sweep, re-run by the orchestrator across all 17 themes after the fix**. Agent-reported contrast counts
taken before the correction are not carried forward. Recording this here rather than quietly re-running
is the point: an instrument that can be satisfied by a value the app did not choose is the recorded
lesson this repeats.

### 0.2 What this audit did *not* reach

Named rather than silently omitted:

- **No human eye.** The honest stamp on everything here is *"Chromium-verified (remote sandbox) ·
  awaiting human UX pass"*, never "verified". Nothing here is a substitute for a person using the app.
- **One engine, one renderer.** Chromium only. No Gecko, no WebKit, no real mobile device, no touch
  hardware, no screen reader actually run (axe-core is a static a11y linter, not a screen reader).
- **Host contention.** 4 CPU cores and 16 GB shared between ~14 concurrent agents, 19 app servers and up
  to 50 Chromium processes. Load average peaked at **151**, and one app instance (port 8012) was
  **OOM-killed by the kernel mid-audit** (`dmesg: oom-kill … task=uvicorn`), which truncated the 4×-CPU-
  throttle latency battery. **Every absolute wall-clock number in this report is therefore inflated and
  is reported as a ratio or alongside its conditions.** Byte counts, request counts, node counts and
  contrast ratios are load-independent and are the numbers to trust.
- **The corpus is synthetic.** 453 articles is a young corpus. Any rendering path that only appears at
  scale, or only with real-world messy data, is unexercised — and where a fixture could not exercise a
  path, the agents were required to say "unverified" rather than "passes".
- Not a security test, not a fuzzing run, not a full `pytest` execution.

---

## 1. The nine things that matter most

Ranked by consequence, not by discovery order. Every one was reproduced live; the first five were
measured by the orchestrating session itself.

| # | Sev | Finding | Why it matters |
|---|---|---|---|
| 1 | **P0** | **The offline coachmark `#net-coach` covers page content on 16/16 surfaces at every viewport, and at 375 px it blocks interactive controls on 16/16 surfaces — including the top-bar buttons its own placement logic was written to protect.** On Governments at 375 px, Playwright's actionability check times out with *"#net-coach intercepts pointer events"*: the entire sub-tab strip is untappable until it is dismissed. **[hand-verified]** | A first-launch nudge makes parts of every screen unusable on a phone, for up to six launches, before the user has done anything wrong. It is also the mechanism by which a *caveat* gets hidden — on the Observatory it covers the sentence disclosing that the angle channel is meaningless. |
| 2 | **P0** | **A single hidden dropdown costs 714 KB on every page load.** The frontend calls `GET /api/sources` (no trailing slash) — a second, legacy, unpaginated handler at `main.py:2372` that **silently ignores `?limit=`** — instead of the correct paginated `GET /api/sources/`. Measured: `?limit=5` returns 714,399 B either way on the bare route, 1,687 B on the slashed one. **91.4 % of all boot API bytes** are for surfaces Home never shows, and 98.8 % of that waste is this one call. It then trips its own 100/hour rate limit. **[hand-verified]** | This is the whole boot budget spent on data nobody sees, on a local-first app whose corpus is meant to grow. At 10× the sources it is 7 MB per page load. |
| 3 | **P0** | **The Search surface can lock itself out for an hour.** `GET /api/articles` is rate-limited to 100/hour, and `api()` in `app-core.js` auto-retries a 429 up to 4 times — so **one user click can fire five requests**. Ordinary exploratory querying exhausts the budget, after which every search returns only a transient toast and an empty results table. The message *"Too many requests. Please try again later."* is also untranslated in all 12 locales. | The app's largest, most iterative surface (135 controls, 5 inputs, boolean syntax, five time-range presets) is designed for exactly the usage pattern that breaks it, and it fails quietly. |
| 4 | **P1** | **The whole WCAG-AA failure set reduces to five root causes, not 145 bugs.** Corrected 17-theme × 8-surface sweep: `--muted` is below AA against its own panel in **solar, paper, mist and dawn** (one token, ~100 elements); `--accent`-as-text on `--panel2` fails on the active sub-tab in ≥5 themes; `.lead-flip-hint.back` ("⟲ Back") keeps `--muted` on an accent-filled pill and measures **1.01:1 in 17/17 themes**; the trigger chips and the tier badge use fixed, theme-independent colours (1.47:1 in dawn); `.ag-dn` measures 1.56:1 in 17/17. **[hand-verified — `ui-visual-2026-09-08/contrast-corrected.csv`]** | The chips *are* the invariant-#9 "Why am I seeing this?" label; if the label is unreadable the card fails the honesty requirement it exists to satisfy. And "⟲ Back" is the only way out of a flipped card. |
| 5 | **P1** | **Two buttons are painted on top of each other on Insights, in every theme.** `.row > div { flex:1; min-width:140px }` plus `.seg-toggle button { flex:1 }` (basis 0) plus `overflow:visible` makes "Super-groups" render outside its own group box, 90 % covered by "Mind-map": a 60×67 px overlap at 1440 px, **2 overlaps in German, 3 at 1024 px**, also in Arabic. **[hand-verified]** | A control that cannot be read or clicked, on a flagship surface, in the default theme and locale, at the default width. |
| 6 | **P1** | **Custody verification is unreachable from the article it exists to verify.** The Custody form demands a raw `article:<id>` string; the reader offers no "verify" action and no copyable id. | Tamper-evidence is a core honesty-by-construction claim, and in practice a user cannot exercise it on a document they are reading. |
| 7 | **P1** | **The kill switch's own accessible name is permanently English in all 12 locales**, as is the collection-speed knob (both of its strings have no i18n key in *any* locale file), 15 of 17 theme names, 9 of 10 Help doc titles and all 10 blurbs, the Agenda's top consent caveat, and `order_explain` — the invariant-#23 visible caveat rendered under every Lead card. **Every Home briefing Lead's body text is server-generated English in all 12 locales.** Meanwhile `i18n_report.py` reports **3,151/3,151 = 100.0 % for all 12 languages**. | The maintainer-mandated "locale files stay 100 %" ritual is *true about the key files and false about the screen*. A green gate that cannot see the strings that matter most — consent, caveat, kill switch — is worse than no gate. |
| 8 | **P1** | **33.8 % of the backend has no UI.** 224 of 662 API operations have no frontend caller. 56 are self-declared internal diagnostics (correctly unsurfaced). The rest include an entire, complete **Source Groups + batch-operations + discovery feature (24 routes)** with zero UI trace, the **whole statistics router** (t-test/ANOVA/correlation/Mann-Whitney/CI, 9 routes, 100 % unwired), 3 of 4 Conjunction-lens analytics with no endpoint at all, and **a second, parallel backup-restore API** sitting unused beside the one the UI actually drives. | The cheapest wins in the entire report are here: the engine already computes things the user is being asked to do by hand, or cannot do at all. |
| 9 | **P1** | **A user who declines the network has no path to any content whatsoever.** There is no sample corpus, no demo mode, no bundled starter data. The first-launch flow asks for **~5,120 words of reading and four irreversible-ish decisions** before Home, and the legal gate (5,005 words) is **43× longer than the security decision it precedes**, with no scroll or read verification. | A local-first, consent-first app currently punishes the most privacy-conscious choice it offers with an empty screen. This is the single largest lever on both the complexity problem and the first-run problem. |

**And one that is not a defect but frames everything else:** `pytest tests/test_repo_invariants.py -k ui_invariants` **passes green** on this tree. Every finding above is invisible to it, because it checks *structure* — that a select exists, that a class is present, that a string appears in a file — and none of these are structural. **[hand-verified]** The gap this audit fills is precisely the gap between "the markup says so" and "the screen does so".

---

## 2. Findings the orchestrating session verified with its own hands

These are not agent claims. Each was measured directly, with the method stated, and the raw data is in
[`ui-visual-2026-09-08/`](ui-visual-2026-09-08/).

### 2.1 `#net-coach` occlusion matrix — 16 surfaces × 5 viewports

Method: load each surface fresh in a first-launch profile (ink/en, port 8010), then for every
`button/a/input/select/[role=tab]/[data-tab]` whose centre falls inside the coachmark's rect, call
`document.elementFromPoint()` at that centre and record it as *blocked* when the topmost element is the
coachmark. Text elements intersecting the rect are counted separately.
Raw: [`coach-occlusion.csv`](ui-visual-2026-09-08/coach-occlusion.csv).

| viewport | coach shown | surfaces with **blocked controls** | surfaces with covered text | examples of what is blocked |
|---|---|---|---|---|
| 375 × 812 | 16/16 | **16/16** | 16/16 (max 13 elements) | `#tm-open`, `#lang-switch`, `#app-shutdown` — the top-bar controls themselves |
| 768 × 1024 | 16/16 | 7/16 | 16/16 (max 10) | Insights "Super-groups"/"Map"; Governments "Statistics", `#gov-load-btn`; Agenda "Decade"/"List"; Indices "South America"/"Oceania" |
| 1024 × 800 | 16/16 | 7/16 | 16/16 (max 10) | Insights "Map"/"Convergence"; Agenda "List" |
| 1440 × 900 | 16/16 | 2/16 | 16/16 (max 10) | Governments `#gov-load-btn`; Analyze "Sources"/"Competitive" |
| 1920 × 1080 | 16/16 | 0/16 | 1/16 (max 2) | — |

The mechanism is in `app-core.js:_placeCoach()`. It is careful, well-commented code that already fixed a
recorded P0 (*"net-coach-blocks-topbar-buttons"*) by refusing to place the bubble above the button and
instead putting it **below the union rect of four top-bar buttons**. That guard holds at desktop widths
and **fails at 375 px**, where the final clamp
(`top = max(pad, min(top, innerHeight - h - pad))`, and the same for `left`) collapses the bubble back
over the very cluster the union rect was computed to avoid. The union rect also never considered page
content, which is why 1440 px shows zero blocked controls and still covers text on all 16 surfaces.

**Evidence:** [`evidence/01-netcoach-blocks-nav-375-governments.png`](ui-visual-2026-09-08/evidence/01-netcoach-blocks-nav-375-governments.png)
— the Governments sub-tab strip with "Cou…" clipped and everything after "Map" gone.

**Ethical dimension, not just layout.** The bubble's primary, accent-filled action is **"Go online"**;
the decline is a quiet secondary "Not now". In an app whose default and celebrated state is airplane
mode, the visually dominant action in an unrequested overlay is the one that starts egress. The
consent gate behind it is intact (`toggleNetwork()` → `ensureOnline`, verified), so this is a
presentation concern rather than a consent breach — but it is the wrong emphasis for this product.

### 2.2 Composited contrast, corrected, across all 17 themes

Method: 17 themes × 8 surfaces, composited colour with the element's own background included and the
full opacity chain resolved; elements with cumulative opacity < 0.02 excluded as invisible rather than
failing. 145 distinct (selector, text) pairs failed AA at least once.
Raw: [`contrast-corrected.csv`](ui-visual-2026-09-08/contrast-corrected.csv).

**They are five defects, not 145.** The tell is that dozens of unrelated elements share an *identical*
ratio within one theme — which only happens when they share a token.

| root cause | worst measured | themes affected | what it hits |
|---|---|---|---|
| `.lead-flip-hint.back` inherits `--muted` while sitting on an accent-filled pill | **1.01:1** (mint) / 1.04:1 (ink) | **17/17** | the "⟲ Back" control — the only way out of a flipped briefing card ([evidence](ui-visual-2026-09-08/evidence/03-flipback-contrast-1_04-ink.png)) |
| `.ag-dn` adjacent-month day numbers | **1.56:1** (paper) | **17/17** | the Agenda month grid ([evidence](ui-visual-2026-09-08/evidence/05-agenda-adjacent-day-contrast-paper.png)) |
| trigger chips use a fixed, hash-derived colour identical in every theme (`rgb(209,129,71)` etc.) | **1.47:1** (dawn, "recycled claim") | 5–12/17 depending on the chip | the invariant-#9 plain-words label on every Home Lead ([evidence](ui-visual-2026-09-08/evidence/04-trigger-chip-contrast-dawn.png)) |
| `.tier-badge` uses a fixed `rgb(59,130,196)` | **3.20:1** (solar) | **14/17** | "Developing corpus" — the corpus-maturity caveat |
| `--muted` below AA against its own panel; `--accent`-as-text on `--panel2` for the active sub-tab | 3.47–4.41:1 | solar, paper, mist, dawn | ~100 elements each: every sub-tab label, the whole Method/"The exact math" table, `div.k` stat labels, `p.sum` and `p.why-plain` card body text, the sidebar nav labels, `#version`, `#health`, `#lang-code` |

Two consequences worth stating plainly. First, **the failures concentrate on exactly the honesty
surfaces** — the caveat chip, the tier badge, the "Why am I seeing this?" block, the method tables, the
`n=` significance lines. Second, the fix is small: retune `--muted` and the accent-on-panel2 pair in four
themes, give the flip-hint an explicit on-accent colour, and derive the chip and badge colours from the
theme the way `--caveat` already is. The `--caveat` token is the model — it was tuned to clear AA on all
17 themes and it does.

### 2.3 The `.seg-toggle` overlap

Reproduced on Insights at `#mm-kit .row`. `.row > div { flex:1; min-width:140px }` gives each group a
`flex-basis: 0` share; `.seg-toggle button { flex:1 }` does the same to the buttons inside it; with
`overflow: visible` the buttons render *outside* their group's box and are painted over by the next
group.

| condition | overlaps | worst |
|---|---|---|
| ink / en / 1440 | 1 | Super-groups ↔ Mind-map, 60 × 67 px |
| ink / fr / 1440 | 1 | Super-groupes ↔ Carte mentale, 39 × 67 px |
| ink / de / 1440 | **2** | Obergruppen ↔ Mindmap, **102 × 43 px** |
| ink / en / 1920 | 1 | unchanged — not a width problem alone |
| ink / en / 1024 | **3** | Families ↔ Mind-map, Super-groups ↔ Mind-map, Super-groups ↔ Word cloud |
| paper / ar / 1440 | 1 | mirrored, same defect |

**Evidence:** [`evidence/02-insights-segtoggle-overlap.png`](ui-visual-2026-09-08/evidence/02-insights-segtoggle-overlap.png).

### 2.4 Boot and idle cost

Measured on port 8010, ink/en/1440×900, and cross-checked against an independent agent run.

- **25 script tags, 1,664 KB of JavaScript decoded, all eager.** The Home-relevant subset
  (`app-core`, `app-home`, `app-shell`, `app-boot`, `i18n`, `boot`, `sw-register`) is 305 KB — **18.4 %**.
  The other **81.6 %** belongs to surfaces a Home-only session never calls a function from.
- **No HTTP compression at all.** `curl -H 'Accept-Encoding: gzip, br'` on `app-map.js` returns
  `content-length: 158817` with **no `content-encoding` header**. Measured `gzip -9` on the app's own
  files: `app-map.js` −71.0 %, `app-core.js` −67.5 %, `app-home.js` −69.0 %, `index.html` −72.8 %.
  A single compression middleware would cut roughly 1.2 MB from every cold load. **[hand-verified]**
- **33–35 API calls in the boot window, ~792 KB**, of which Home renders 68 KB (8.6 %).
- **`/api/sources` — the dual-handler bug.** `GET /api/sources` → 714,399 B regardless of `?limit=`;
  `GET /api/sources/?limit=5` → 1,687 B. Two handlers: `src/api/main.py:2372` (`@app.get("/api/sources")`,
  legacy, unpaginated) and the paginated router the frontend never reaches. **[hand-verified]**
- **6,952 DOM nodes on Home; 759 CSS rules.** `index.html` is 268 KB and ships **all 16 tab panels in
  the DOM at once**.
- **Idle: 13 loopback requests per 20 s** (`scheduler/status` ×5, `system/network` ×4, plus
  `database/stats`, `briefing`, `insights/trending-windows`, `signals/alerts`) ≈ **2,340 requests/hour
  doing nothing**. Zero long tasks at idle — the cost is wakeups and battery, not jank.
- **Under 4× CPU throttling** (the honest number for a journalist's laptop): DCL ×2.46, FCP ×1.96,
  long-task count ×4.5, **long-task total duration ×8.1**.
- **Indices fires 26 parallel API calls just to open** (one per index/commodity, `Promise.all` in
  `app-markets.js:213`). **Help adds 3,755 DOM nodes and +3.87 MB of JS heap** for a single panel.

### 2.5 Design-token inventory

`app.css` is 1,718 lines / 717 selectors. `:root` defines 35 custom properties — 24 of them colour, and
the colour system is genuinely well engineered (per-theme, `color-mix`-derived, with measured worst-case
ratios left in the source as comments). What does not exist:

- **No type scale.** 150 `font-size` declarations resolve to **24 distinct values** (9.5 … 30 px);
  **56 of them (37 %) are below 12 px**; the two commonest are 12 px (36×) and 11 px (30×). Hierarchy is
  being carried by 0.5–1 px steps, which is not a hierarchy.
- **No spacing scale.** 125 `padding` declarations → **83 distinct shorthand strings**.
- **No radius scale.** 115 declarations → 19 distinct value-strings; **106 of 115 bypass the two existing
  tokens**; two different pill radii (99 px and 999 px) are used interchangeably.
- **No z-index scale.** 19 declarations, 14 raw values (`0,1,30,50,55,60,140,150,151,200×3,360,400,9998,99998`).
  `.sidebar` and `.vitals-pop` collide at 60 by coincidence; `.skip-link`, `#net-flash` and `#toast` at 200.
- **`--line` is referenced 41 times and defined nowhere.** Every one of those declarations is invalid at
  computed-value time. Confirmed live: `#oo-tip` (the invariant-#17 tooltip instrument) and `#net-coach`
  render with **no border in any theme**. `app.css:305–311` documents this exact failure for `<dialog>`
  and fixed only that one call site.
- **Nine independently authored chip components** for one visual atom, with 4 radii and 6 paddings
  between them.
- **Almost no motion:** 14 `transition` declarations and 8 `@keyframes` in the entire stylesheet.
  `prefers-reduced-motion` and `prefers-contrast: more` are both handled globally — those are positives.

### 2.6 Server memory, measured on one clean instance

A controlled run against a freshly booted instance (port 8038, nothing else touching it, corpus of 453
articles / 3,618 sources), reading `VmRSS` of the `uvicorn` process directly:

| moment | RSS |
|---|---|
| idle, straight after boot | **315 MB** |
| after loading Home | 376 MB |
| **after visiting all 16 surfaces once** | **922 MB** |
| after a further 20 s idle | 922 MB (no release) |

**Measured, not diagnosed.** Whether this is retained objects or allocator arenas that never return to
the OS needs a heap profile that was not run here, and a server process is not the same thing as a
desktop app's footprint. But the user-visible fact stands: a local-first tool aimed at a journalist's
laptop reaches ~1 GB resident after a single tour of its own tabs on a very small corpus, and does not
come back down. (Corroborating, from the sandbox rather than from the app: with 19 instances running,
the kernel OOM-killer took one of them out mid-audit.)

---

## 3. Corrections to the existing record

Every one of these was re-derived live against today's tree rather than trusted from the ledger or from
the previous audit. Recording them matters as much as the new findings: a backlog that carries a fixed
defect wastes the next session's time.

| claim on record | verdict today | how it was re-derived |
|---|---|---|
| *"Settings → Source qualification's two scope checkboxes silently fail to save and then visibly revert, right after a false 'Saved.' toast"* (10-audit §1 #6) | **Did not reproduce** | Two independent agents, change → save → full page reload → re-read against both the DOM and a direct `GET`, including single-click, uncheck and rapid-race variants |
| *"theme-select-lossy-overwrite"* — the `#set-theme` 3-way bucket destroying a full theme choice | **Fixed**, verified live | Picked a theme in the gallery, then touched `#set-theme`, then reloaded |
| *"eleven `ooViz` primitives remain unwired"* | **7 of 19**, not eleven | Read the 19 exports out of `ooviz.js:571-591` and traced both dot-access and aliased/destructured `V.` access in `oosky.js` |
| *"the retired temporal-map cluster is dead code interleaved with live helpers"* | **Already fully resolved** | Zero live callers and no `#tmap-*` DOM targets remain |
| *"`prefers-contrast` is unhandled"* / *"`.sr-only` is absent"* (already corrected in the backlog on 2026-09-07) | **Confirmed present** | `@media (prefers-contrast: more)` applies live under `emulate_media(contrast="more")`; `.sr-only` at `app.css:161` |
| *"~590 inline `on*=` handlers"* | **585 measured** (332 in `index.html`, 253 across `app-*.js`) against 135 `addEventListener` — the same order, restated with today's count | `grep -o` on both file sets |
| **This audit's own first contrast harness** | **Wrong, corrected mid-run** | See §0.1. One agent's `LAW-6` contrast finding (a claimed 1.08:1) was subsequently **REFUTED** by its verifier running the *corrected* harness on the identical surface, which returns an empty array |

One correction went the other way, and is the better story. An agent reported the Tracked-laws
"official ↗" links as **functionally dead** — click, nothing happens, no navigation, no local preview —
and reproduced it byte-for-byte. Its adversarial verifier reproduced the same symptom and then found the
diagnosis was wrong: the app-wide capture-phase `_externalLinkGuard` (invariant #7) intercepts the click
and raises a `confirm()`, which a headless browser with no dialog handler silently dismisses. The link is
not dead; it is gated. **But the verifier then found a real defect underneath**: that guard shows a
factually wrong *"this leaves the app"* warning on anchors whose own `onclick` already routes through the
local `openLinkPreview` path and therefore do not leave the app. A confirmed symptom, a refuted cause,
and a new finding — which is what the adversarial layer is for.
