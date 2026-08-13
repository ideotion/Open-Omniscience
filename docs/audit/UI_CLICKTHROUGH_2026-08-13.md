# UI Click-Through — 0.3 close gate row 8 — 2026-08-13

**Status:** executed. Brief of record:
[`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-08-13_UI_CLICKTHROUGH.md`](../design/AUTONOMOUS_SESSION_BRIEF_2026-08-13_UI_CLICKTHROUGH.md)
(the canonical, committed version — a copy of the same brief was also delivered as this
session's own task instructions; both agree in substance).
**Machine-readable companions:** [`findings.csv`](ui-clickthrough-2026-08-13/findings.csv)
(10 rows) · [`coverage.csv`](ui-clickthrough-2026-08-13/coverage.csv) (87 rows).
**Verification stamp:** the surfaces covered below graduate to **"Chromium-verified (remote
sandbox) · awaiting human UX pass"** — the same bar the 2026-07-22 systematic GUI test report
established, not the Gecko/VM-verified bar, and not a substitute for a maintainer click-through.
**§4–§6 below are the honest reconciliation against the brief's fuller matrix** — read them
before treating this report as complete coverage of every surface/axis the brief names.

---

## 0. What this session delivers

Row 8 of the 0.3 close gate asked for one of two things: a **standing** `ui_walk` runner, or a
defined human click-through. This session builds the first — a real Playwright-backed
`UiWalkDriver` implementation (`src/monitoring/ui_walk_playwright.py`), drives it against three
live app instances representing the brief's three test states, and produces the report below.
The harness is not a one-off script: it is merged source (`src/monitoring/ui_walk.py` +
`ui_walk_playwright.py`), covered by 31 passing regression tests
(`tests/test_ui_walk_playwright.py`, `tests/test_ui_walk.py`), and re-runnable by any future
session via `scripts/ui_clickthrough_run.py`.

### Methodology

Three separate app instances, each booted from a fresh `OO_DATA_DIR` with
`OO_NO_SCHEDULER=1 OO_LLM_AUTOSTART=0 OO_AIRPLANE_SOCKET_GUARD=1` (airplane mode engaged
throughout — no egress at any point in this run):

- **STATE A** (virgin, port 8001) — first-launch/lifecycle flow: language → legal → create
  passphrase. Genuinely wiped and relaunched fresh immediately before the FINAL walk in this
  session (a passing happy-path run permanently unlocks the store, so an earlier run's success
  silently degrades every later one into a no-op unless the store is wiped again — this bit the
  session twice mid-investigation before it was caught and controlled for; see §2).
- **STATE B** (empty, catalog-seeded, port 8002) — empty-state honesty pass. `OO_DB_PLAINTEXT=1`.
- **STATE C** (populated, port 8000) — a synthetic corpus seeded through the real ingestion
  chokepoint (`src/database/store.py::index_article` — real keyword extraction, When/Where/Who,
  sentiment, FTS), built by `scripts/ui_clickthrough_seed.py`: 450 articles across multiple
  languages including a zh (Chinese) cohort (for the CJK-keyword-pill re-check), a 3-source
  near-duplicate cluster, one disqualified source, one unqualified/never-judged source, one
  disabled discovery candidate, and a spread of publish dates. `OO_DB_PLAINTEXT=1`.

The driver walked: the 5 gate-row-8 "flagship" surfaces (Home Leads, the analysis window, the
post-import screen, source management, the diagnostics panel), 9 backlog surfaces from the
harness's known-gap list, then a full drill of every subtab under Analysis (11), Insights (8),
Settings (10), Library (6), and the World map's 4 lenses — 53 walk steps, 87 coverage rows in
total — plus theme-contrast checks (5 themes × 2 selectors), breakpoint-overflow checks (4
widths), locale/RTL checks (**4 locales — en, fr, ar, zh, the brief's own stated axis floor**),
and an opacity-composited pseudo-element spot-check (the invariant #23/`--caveat` contrast-fix
pattern, checked live rather than re-derived from source).

### The one honesty-critical result, stated first

**Across the entire run, zero requests reached any host other than `127.0.0.1`.** The
airplane-mode socket-level guarantee held throughout — every state booted and stayed offline for
its whole walk; nothing in this session's scope required (or attempted) going online.

---

## 1. The harness itself: six real bugs found and fixed in the driver, not the app

Building the "standing runner" surfaced a navigation-grammar gap between the app's *current*
click-through paths and what the harness's `Surface` definitions assumed — evidently written
against an earlier iteration of the SPA's chrome. Each was found by driving the real app,
confirmed with a standalone reproduction, then fixed with a regression test before the next was
chased. None of these are application defects; they are corrections to the test harness so its
verdicts can be trusted. Recorded here because a future session extending this driver needs to
know the shape of each trap.

1. **`"analyze"`/`"settings"` have no `.nav-item[data-tab=...]` at all.** Only 7 of the sidebar's
   sections are reachable that way (home/insights/timemap/law/agenda/indices/library). Settings
   opens via a gear button in the sidebar footer (`button[onclick="showTab('settings')"]`);
   Analysis has **no click target whatsoever** — it opens only via the `openAnalysisFor(query)`
   JS function, the same one the omnibar's Enter key and every keyword chip call. A
   `page.click('.nav-item[data-tab="analyze"]')` burns Playwright's full 30s action timeout
   before failing loudly — the first symptom was an 8-minute hang. Fixed by special-casing both
   in `goto()`.
2. **A leftover open `<dialog>` blocks every click after it.** A `trigger` click (e.g. "Import…")
   can open a native `<dialog>` via `.showModal()`, which installs a page-wide modal backdrop
   that intercepts pointer events on everything else — including the *next* surface's own
   navigation click. Fixed with `_close_any_open_dialog()` (Escape, the native way a user closes
   one), called at the top of every `goto()`.
3. **`#subtab-strip` accumulates stale siblings.** `_relocateSubtabs` (app.js) moves each tab's
   own subtab nav into one shared strip on every `showTab()` — but it APPENDS rather than
   replaces, hiding the prior tab's nav via `display:none` and leaving it in the DOM. Two
   different tabs share the `data-tab="advanced"` value (Analysis and Settings), so
   `#subtab-strip button[data-tab="advanced"]` can resolve to two elements at once. Fixed by
   scoping every subtab click with Playwright's `:visible` selector extension.
4. **A `url`-based surface (`/tasks`) never gets restored.** Navigating to the standalone task
   manager is a real full-page navigation away from the SPA; nothing brought the driver back to
   it before the next `nav_tab`-based surface, and the failure mode was silent — `goto()`'s
   "analyze" branch calls `openAnalysisFor` through a defensive `typeof x === 'function'` guard
   in `page.evaluate()`, so on a page where that function is undefined the call does nothing and
   `evaluate()` returns clean. An entire subtab drill passed through reading `visible=False` with
   no error at all. Fixed with `_ensure_on_spa()`.
5. **A fixed 200ms settle window is not enough for every surface, under a long walk.** After
   dozens of prior surfaces (real network fetches, real DB queries), a handful of
   async-rendered surfaces (the Agenda month grid; the Advanced→Keywords section) were still
   mid-fetch at the 200ms mark, reading as a false `visible=False`. Fixed with a bounded
   (2s) `wait_for_function` polling the surface's own `dom_id` for non-empty content, which never
   changes the verdict for a surface that stays genuinely empty (it degrades to a no-op after the
   timeout) — it only gives a genuinely-rendering-but-slow surface room to finish before the
   snapshot is taken.

6. **State A's own client-side view-toggle sequencing races the harness's fixed settle
   timeouts under real launch contention — not a state-A-only quirk of the fixed timing in
   bug #5, but its most consequential recurrence.** Found live, twice, the same way: two
   full walk runs against a freshly-relaunched state A (immediately after all three app
   instances were launched together, matching the harness's normal setup shape) reported
   `state_a_first_launch`'s entire sequence as `"partial"`/`"blocked"` — `#view-language`
   itself reading `visible=False` at the very first check, 300ms after `domcontentloaded`.
   An isolated re-run of the identical driver function against the identical URL, with
   nothing else launching or navigating concurrently, passed every one of its seven axes
   cleanly on the first try — proving the app itself was never broken. The root cause: the
   fixed sleeps (300ms/300ms/400ms) between navigation and each visibility check gave the
   client's own language → legal → create view-toggle script no margin under contention
   from the other two app instances mid-startup (each still seeding ~3,400 catalog sources).
   Fixed by replacing every fixed sleep in `investigate_state_a` with a bounded (2–5s)
   `wait_for_selector(..., timeout=...)` for the view the app is *about* to show — a
   Playwright `:visible`-scoped selector, so it can never force a hidden view open early,
   only wait for whichever one the app itself is genuinely about to render — plus a
   pre-flight HTTP readiness poll (`_wait_for_server`) before any state's browser navigation
   starts. Re-verified: three subsequent full 3-state runs launched together from cold,
   with zero warm-up delay beyond the new guard, all passed state A's full seven-axis
   sequence cleanly, with the identical (now-stable) findings/coverage totals reported in
   §3. This is the fix that produced the report's final, stable numbers.

A seventh, distinct class of bug — **wrong anchor, not wrong timing** — recurred three times
while building the World-map and Keywords/super-groups checks specifically:

- The World map's lens picker (`#oomap-lenses`) is its **own separate nav**, never moved into
  `#subtab-strip` — a `subtab=` click was reaching nothing. The real render target is
  `#oo-coverage-map`, a *sibling* of the near-vestigial `#oomap-lens-bar` the harness had been
  checking (confirmed live: 162–178K chars of rendered SVG in the correct element across all four
  lenses, versus 0 in the wrong one, on every lens).
- The known-open `ins-map-cjk-sentence-keywords` P1 (2026-07-22 audit) was being re-checked
  against the wrong surface entirely — the original finding's surface was **Insights → Map**
  (`#map-countries .pill`), not the top-level World map tab, which doesn't even render keyword
  text (its place labels live only in SVG `<title>` tooltips, never as visible text). Fixed by
  retargeting the check to the real surface.
- `Settings → Advanced → Keywords`'s own `dom_id` (`#kx-keywords`) is a **drill-down target**
  that `loadKeywordExplorer()` explicitly clears and leaves empty until a facet chip is clicked —
  checking it reports a false failure on a perfectly healthy section. `#sgc-list` (the
  super-group curation cards — "the concept map" the surface's own label names) renders
  substantial real content (595K+ characters against the seeded corpus) on the same open. Fixed
  by retargeting the anchor.

Every fix above is source-commented in place (`ui_walk_playwright.py`, `ui_walk.py`,
`ui_clickthrough_run.py`) with the live evidence that motivated it, and is covered by the
regression suite (31 tests, all passing) or by the walk's own repeated, now-stable green result
(multiple consecutive full re-runs after the last fix, identical outcome each time, including
three full 3-state cold-launch runs after bug #6 above — the harness's own reliability is no
longer a variable in the numbers reported in §3).

---

## 2. A methodology note: state A's virginity is single-use

*(A real operational constraint, now correctly guarded against — not a caveat on the final
numbers below.)*

State A's happy-path check (submit a rejected short passphrase, then a strong one) genuinely
unlocks the encrypted store on success — a real, working create-passphrase flow, exactly as
intended. That means **every subsequent walk run against the same data directory silently
degrades the state-A checks into no-ops** (the create-passphrase view is simply never shown
again, since the store is no longer locked). This bit the session twice during investigation:
once as the state-single-use trap itself (a passing run against a data dir already consumed by
an earlier successful create-passphrase), and once — the more consequential one — as bug #6
above (a *fresh* state A read as broken purely from launch-contention timing, which briefly
looked like the same single-use trap but was not). Both are now controlled for: a future
re-run of this harness must wipe and relaunch state A's data dir fresh before each run that
needs its checks to mean anything (the single-use fact does not change), and the harness itself
no longer needs generous manual warm-up sleeps to get a reliable read once it is fresh (bug #6's
fix). The final report below reflects a genuinely fresh, cleanly-relaunched state A.

---

## 3. Findings — final, stable run

Multiple consecutive identical walk runs after the last driver fix (§1, bug #6), including three
full 3-state cold-launch runs with no manual warm-up delay; the numbers below are from the last
of them, on a freshly-wiped state A, all three app instances launched together immediately
before the walk began (the exact contention shape that previously exposed bug #6).

| # | Severity | Finding | Status |
|---|---|---|---|
| 1 | POSITIVE | `LC-VIEW-HIDDEN-ON-ERROR` (2026-07-22 P0) stays fixed: a rejected short passphrase leaves the create-passphrase form visible, with a readable error, never a blank page | Re-verified live |
| 2 | POSITIVE | The first-launch create-passphrase happy path reaches the app: a strong passphrase submitted after a rejected short one succeeds and lands on Home | Re-verified live |
| 3 | POSITIVE | Home's empty-state honesty holds on a catalog-seeded, zero-article corpus: an explicit "No Leads yet" message, zero console errors | Verified |
| 4 | **P0 (expected, not a defect)** | The post-import screen's summary (`#ux-imp-summary`) is empty because no import ran in this walk | **By design** — see below |
| 5 | P2 | Governments tab still defaults to Countries, not Law | Re-confirmed still present (2026-07-22, known-open, deliberate/documented) |
| 6 | P1 | `ins-map-cjk-sentence-keywords` (2026-07-22) could not be reproduced against the seeded zh corpus, checked against its correct surface | Honest non-reproduction, not a verified fix — see below |
| 7 | **P1 (new)** | Top bar overflows horizontally at 375px (`scrollWidth=452` vs `clientWidth=375`) | New finding — see below |
| 8 | POSITIVE | Top bar has no overflow and every core control (`#net-toggle`, `#lang-switch`, `#tm-open`, `#app-shutdown`) stays on-screen at 768px | Re-verifies the fixed `topbar-overflow-mobile-375` / `topbar-overflow-mainstream-widths` P1s (2026-07-22) |
| 9 | POSITIVE | Same, at 1024px | Re-verified |
| 10 | POSITIVE | Same, at 1440px | Re-verified |

### #4 — the post-import screen "failure" is expected, by design

This check is deliberately unable to pass in this walk. `Surface("post_import_screen", ...)`
carries its own note: *"the dialog opens with an EMPTY summary until an import actually
completes — `is_visible()` here only proves the surface is reachable, not that a real import
rendered."* This session's scope explicitly excludes destructive/mutating operations beyond what
seeding requires, so no real import was run. The dialog itself opens correctly
(`export_import_dialog` — the sibling check — passes); only the post-import *content* is
untested here. The dedicated post-import redesign is tracked separately in `CLAUDE.md`'s open
queue and is unaffected by this session.

### #6 — the CJK-keyword-pill gap: honest non-reproduction

Checked against the corrected surface (Insights → Map, `#map-countries .pill`, `country=cn`),
against a seeded zh corpus of the same rough shape as the 2026-07-22 run: 60 pills sampled,
several genuinely short un-segmented multi-character Chinese phrases present (e.g. `分析人士指出`,
`独立观察员表示` — 6-7 characters, the ongoing, already-documented CJK segmentation gap in a mild
form), but none matching the original finding's severe symptom (a 40+ character run
concatenating two full sentences into one "keyword"). This is recorded as an **honest
non-reproduction**, not a verified fix: the seeded corpus's zh keyword yield for `country=cn` may
simply be thinner than the original run's, and nothing here confirms or denies whether the
underlying segmentation gap has narrowed. Per the session's scope fence, this finding is **not
re-litigated or investigated further** — it stays open exactly as the 2026-07-22 triage left it.

### #7 — top bar overflow at 375px (new, not fixed this session)

`document.documentElement.scrollWidth` (452px) exceeds `clientWidth` (375px) at a 375×900
viewport — a genuine, reproducible horizontal overflow. The four specifically-named controls
this check also probes (`#net-toggle`, `#lang-switch`, `#tm-open`, `#app-shutdown`) are each
individually still within the viewport bounds at this width (none of the four themselves reads
`left < 0` or `right > 375`), so the overflow is cumulative across the bar's contents rather than
one single control protruding. The SAME check at 768/1024/1440px shows **zero** overflow and
**zero** off-screen controls — confirming the 2026-07-22 audit's `topbar-overflow-mainstream-widths`
P0/P1 fix genuinely holds at every mainstream breakpoint; only the narrowest (true mobile,
375px) breakpoint still overflows. This is a **narrower-scope regression of a known, previously
much broader issue**, not a fresh unrelated defect.

**Not fixed in this session.** `CLAUDE.md`'s own ledger records the top-bar responsive fix as an
explicit scope exclusion from an earlier fix session ("the top-bar responsive fix (that report's
item 4)"), consistent with this session's own fix policy: layout/CSS work at this level typically
needs a real design decision (which controls collapse, hide, or reflow at extreme narrow widths)
rather than a mechanical, provably-safe change, and touching the shared top-bar CSS risks
regressing the now-confirmed-fixed 768/1024/1440px cases. Recorded with full reproduction
evidence (`coverage.csv` row `topbar_overflow,375x900`) for a future, design-scoped session.

---

## 4. Surface coverage against the brief's §6 — the 15 named surfaces

The brief's §6 names 15 surfaces (its own table, reproduced with status here). "Default axis"
means: the surface was navigated to and its render target confirmed non-empty at the app's
default theme/locale/breakpoint — the walk's baseline pass, per §6's own sequencing ("every
surface × the default axis, then every axis × a representative surface").

| # | Surface (brief's wording) | Default-axis status | What was actually walked |
|---|---|---|---|
| 1 | Home / Leads · the Overview lens | ✅ covered | `home_leads` (flagship) |
| 2 | The analysis window (all subtabs) | ✅ covered | `analysis_window` + all 11 subtabs individually drilled |
| 3 | The post-import screen + corpus-delta view | ⚠️ partial | `post_import_screen` opens (dialog reachable); its **content** cannot render without a real import, which this session's scope excludes (§7 below) — see finding #4 |
| 4 | Source management + the qualification panel | ✅ covered | `source_management` (flagship) |
| 5 | The one-button diagnostics panel | ✅ covered | `diagnostics_panel` (flagship) |
| 6 | Export / Import (unified dialog) | ✅ covered | `export_import_dialog`; the compartmented-export selection itself was not separately exercised (its choices weren't clicked, only the dialog's default open) |
| 7 | Library — the five views + graphs | ✅ covered | 6 subtabs walked (overview/activity/tracked/composition/storage/coverage) — the axis-honesty pass (hide-flat-zero, window switcher) was **not** independently verified beyond render-non-empty |
| 8 | World map — dimensions · granularity · signals · Server-IP layer | ⚠️ partial | all 4 top-level lenses walked (`worldmap_coverage/stories/places/servers`); **the in-panel dimension/granularity/signal sub-controls within each lens were not drilled** — this was already flagged in the prior draft's "suggested next steps" #3, unchanged here |
| 9 | Settings — all ten subtabs incl. Cards and Advanced | ✅ covered | all 10 walked individually |
| 10 | Settings → AI — pill, backend panel, roster install | ⚠️ partial | `settings_ai` opens and renders; the pill's third state and the roster-install flow specifically were **not** separately exercised |
| 11 | Keyword / group / super-group surfaces + the concept map | ✅ covered | `keyword_supergroups` (→ `#sgc-list`, "the concept map"), `insights_families`, `insights_supergroups` |
| 12 | Agenda — month grid, glyphs, deduced events | ⚠️ partial | `agenda_month` + `settings_agenda` render; the glyphs and deduced-events provenance pills specifically were **not** independently verified |
| 13 | Reader — tabs, provenance classes, Loaded-language | ❌ **not covered at all** | no `Surface` for the standalone article reader exists in `ui_walk.py`'s current `FLAGSHIP_SURFACES`/`BACKLOG_SURFACES`, and none was added this session — the single largest named-surface gap in this run |
| 14 | Task manager — Active · Queue · System · Schedule | ⚠️ partial | `task_manager` opens and renders (default tab only); the four named sub-panels were **not** individually drilled |
| 15 | Bulletin — review screen + the Settings section | ⚠️ partial | `bulletin` opens and renders (default view only); the review screen and its Settings-section counterpart were **not** separately walked |

**9 of 15 fully covered at the default axis, 5 partially covered (the surface opens and renders,
but a named sub-capability within it was not independently drilled), 1 — the Reader — not
covered at all.** The gate's own "Closes when" clause (§8 of the design doc) asks specifically
for the **5 gate-row-8 flagship surfaces** (rows 1, 2, 3, 4, 5 above) to carry a verification
stamp — all five do, including the deliberately-partial post-import screen (which carries an
honest, documented reason, not a silent gap). The wider §6 matrix's remaining 10 surfaces are a
**stretch target beyond the gate's own literal bar**, not a condition of it; see §8 for what a
follow-up session should prioritise there.

## 5. Axis coverage against the brief's §6

The brief states four axes with explicit minimums: **17 themes** (at minimum ink, paper,
contrast, and six light themes that failed `--warn`), **12 locales** (at minimum en, fr, ar,
zh), **breakpoints** 375/768/1024/1440, and **a11y** (axe, keyboard-only traversal, focus
visibility, `prefers-contrast`).

| Axis | Brief's stated floor | What this run did | Status |
|---|---|---|---|
| Themes | ≥9 (ink, paper, contrast + 6 named light themes) for the contrast-focused checks; 17 for full coverage | 5 (`ink`, `paper`, `contrast`, `mint`, `dawn`) — 2 of the 6 named light themes | ❌ **below the stated floor** — 4 more light themes owed even at the minimum |
| Locales | ≥4 (en, fr, ar, zh) for the floor; 12 for full coverage | 4 (`en`, `fr`, `ar`, `zh`) | ✅ **meets the stated floor exactly** — full 12-locale sweep is the stretch target |
| Breakpoints | 375/768/1024/1440 | all four | ✅ **fully covered** |
| a11y (axe, keyboard traversal, focus visibility, `prefers-contrast`) | all four checks | none | ❌ **not covered at all** — no axe integration, no keyboard-only traversal test, no focus-visibility test, no `prefers-contrast` media-query check were built or run this session |

The theme gap is the one that matters most given §5's own opening finding (`.ag-cal` failing
WCAG AA on 16 of 17 themes purely from `opacity` compositing): this run's `contrast_pill.warn`
and `contrast_card-caveat` checks passed cleanly (4.87:1–10.50:1, all above the 4.5:1 AA bar)
across the 5 themes actually sampled, but **that says nothing about the other 12 — including
the specific light-theme cluster the brief calls out by name** (paper/dawn/solar/mist/light/
mint are the six named in the standing `--warn` ledger fix; this run sampled only paper/dawn/
mint of those six). This is recorded as an open gap, not papered over as coverage.

## 6. The §5 honesty-rule checks actually exercised

The brief's §5 names nine specific honesty-critical verification techniques, each tied to a
real, previously-shipped defect. Two were built and run this session; seven were not.

| # | Honesty rule (brief §5) | Exercised this session? |
|---|---|---|
| 1 | Composited-pixel contrast (`getComputedStyle`, element + pseudo-element, never declared tokens) | ✅ yes — `contrast_pill.warn`/`contrast_card-caveat`, real RGB triples read live |
| 2 | `::after` inheritance-leak spot-check | ✅ yes — `opacity_pseudo_spotcheck` on `#net-toggle::after` and `.nav-item.adv .badge`, both read clean (no unintended opacity/size inheritance found) |
| 3 | "A class with no rule is a lie the markup keeps telling" | ❌ no — not checked this session |
| 4 | Greyscale filter, captured mid-interaction | ❌ no — not checked this session |
| 5 | "An untested path is not a pass" (say so, add the specimen) | ⚠️ partial — honored as a *discipline* (finding #6's honest non-reproduction is framed exactly this way), but not as a systematic per-surface audit |
| 6 | RTL bidi isolates verified by rendered character x-position | ❌ no — this run's `locale_switch` check confirms `dir="rtl"` is set for Arabic and that zero console errors occur on switch, which is a **much weaker check** than verifying isolate characters actually reorder a punctuation-joined run correctly |
| 7 | `uppercase` no-op in ar/zh/ja/hi/bn (five of twelve locales) | ❌ no — not checked this session |
| 8 | i18n walker exact-text-node matching (value-welded strings can never key) | ❌ no — not checked this session |
| 9 | Adversarial critics reading screenshots | ❌ no — no subagent screenshot-review pass was dispatched this session |

This is the honesty-critical gap this report is most explicit about: **2 of 9 named techniques
were actually run.** The two that were are also the two the brief's own §5 opens with (the
composited-opacity family), which is not a coincidence — they were chosen because the fix
policy (§7 of the brief) favours mechanical, cheap, provably-safe checks, and those two are the
cheapest to automate against the live DOM. The remaining seven need either new instrumentation
(bidi character-position reading, an axe integration) or a genuinely different verification
posture (adversarial screenshot review needs a human or a vision-capable subagent pass, not a
DOM query) — recorded as follow-up work in §8, not silently absorbed into "coverage."

---

## 7. What this run does NOT establish

Per the brief's own honesty rails: this is a Chromium-in-a-remote-sandbox pass against a
450-article synthetic corpus, not the maintainer's live corpus (which never enters an agent
session by design), and not the queued Gecko/VM-verified bar. It does not re-litigate any
2026-07-22 finding beyond the two explicitly re-checked here (the topbar breakpoints and the CJK
keyword pills) — every other 2026-07-22 finding's disposition stands as that report left it. It
does not touch the Observatory, the inline-handler retirement backlog, or any of the five new
verticals — all explicitly out of scope for this session. And it does not exercise anything
requiring a local LLM/Ollama/GPU, or any networked path — airplane mode stayed engaged for the
entire run, by design.

**Restated precisely from §4–§6 above, so it is not lost in the prose:** the Reader surface
(tabs, provenance classes, Loaded-language) was not walked at all; the World map's in-panel
lens sub-controls, the AI pill's third state and roster install, the Agenda's glyphs/
deduced-event pills, the Task manager's four named sub-panels, and the Bulletin's review screen
were each opened and confirmed to render but not independently drilled; theme coverage sampled
5 of the stated ≥9-theme floor (2 of the 6 named light themes); and the a11y axis (axe,
keyboard-only traversal, focus visibility, `prefers-contrast`) and 7 of the brief's 9 named
honesty-rule checks were not run at all. None of this was silently dropped — it is the explicit
subject of §4–§6.

---

## 8. Suggested next steps (not built this pass)

**Findings-driven:**

1. The 375px top-bar overflow (#7 above) — a design-scoped responsive-layout pass (collapse,
   overflow-menu, or reflow strategy for the sub-1024px top bar), building on the
   already-confirmed-working fix at 768px+.
2. A real, non-destructive import fixture the harness can trigger to exercise the post-import
   screen's actual content-rendering path (today it can only confirm the dialog *opens*).

**Matrix-driven, from §4–§6's reconciliation, roughly in the order a follow-up session should
tackle them:**

3. **Add a `Surface` for the Reader** (the single largest named-surface gap — tabs, provenance
   classes, Loaded-language) — the offline reader is a standalone server-rendered page reached
   via `/api/articles/{id}/view`, not the SPA, so this needs its own navigation path in the
   driver rather than the existing `nav_tab`/`subtab` grammar.
4. Widen `THEMES_TO_CHECK` to the full named light-theme cluster (paper/dawn/solar/mist/light/
   mint — currently only paper/dawn/mint sampled) to actually clear the brief's own stated
   ≥9-theme floor, then toward the full 17.
5. Drill the World map's in-panel lens sub-controls (dimension/granularity/signal toggles
   within each of the 4 lenses already walked) one level deeper.
6. Drill Settings → AI's pill third state and roster-install flow, the Task manager's four
   named sub-panels (Active/Queue/System/Schedule), the Bulletin's review screen vs. its
   Settings-section counterpart, and the Agenda's glyph/deduced-event provenance pills — each
   currently only confirmed to open and render at its default state.
7. Build the a11y axis from scratch: an axe-core integration (bundled locally, per the
   local-first/no-CDN posture the rest of the app already follows), a keyboard-only traversal
   walker, a focus-visibility check, and a `prefers-contrast` media-query pass.
8. Build the remaining 7 of 9 §5 honesty-rule checks: a class-with-no-rule sweep, a
   greyscale-mid-interaction capture pass, RTL bidi-isolate verification by rendered character
   x-position, the `uppercase`-no-op check across the five affected locales, and an i18n
   walker exact-text-node-match verification. The ninth (adversarial critics reading
   screenshots) needs a different posture entirely — a vision-capable subagent fan-out over
   this run's own evidence screenshots, or a human pass, not more DOM instrumentation.
9. Extend theme/locale coverage from "the stated floor" toward the brief's full 17×12 ambition,
   guided by §6's own sequencing rule ("every axis × a representative surface... where a defect
   family predicts one").
10. Graduate this harness from a manually-invoked script to a scheduled/CI-triggerable job once
    the AppVM recursive-improvement runner (R3, `docs/design/RECURSIVE_IMPROVEMENT_RUNBOOK_2026-07-13.md`)
    is standing — the two share the same "real browser, real app, never the live corpus" posture.
