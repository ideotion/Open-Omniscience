# UI Click-Through — 0.3 close gate row 8 — 2026-08-13

**Status:** executed. Brief of record: the "Autonomous session brief — the UI click-through
(0.3 gate row 8)" issued 2026-08-13 (not committed as a standalone design doc — its full text is
reproduced in intent by this report and by the driver's own module docstrings).
**Machine-readable companions:** [`findings.csv`](ui-clickthrough-2026-08-13/findings.csv)
(10 rows) · [`coverage.csv`](ui-clickthrough-2026-08-13/coverage.csv) (86 rows).
**Verification stamp:** the surfaces covered below graduate to **"Chromium-verified (remote
sandbox) · awaiting human UX pass"** — the same bar the 2026-07-22 systematic GUI test report
established, not the Gecko/VM-verified bar, and not a substitute for a maintainer click-through.

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
Settings (10), Library (6), and the World map's 4 lenses — 53 walk steps, 86 coverage rows in
total — plus theme-contrast checks (5 themes × 2 selectors), breakpoint-overflow checks (4
widths), locale/RTL checks (3 locales including Arabic), and an opacity-composited
pseudo-element spot-check (the invariant #23/`--caveat` contrast-fix pattern, checked live
rather than re-derived from source).

### The one honesty-critical result, stated first

**Across the entire run, zero requests reached any host other than `127.0.0.1`.** The
airplane-mode socket-level guarantee held throughout — every state booted and stayed offline for
its whole walk; nothing in this session's scope required (or attempted) going online.

---

## 1. The harness itself: five real bugs found and fixed in the driver, not the app

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

A sixth, distinct class of bug — **wrong anchor, not wrong timing** — recurred three times while
building the World-map and Keywords/super-groups checks specifically:

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
(3 consecutive full re-runs after the last fix, identical outcome each time).

---

## 2. A methodology note: state A's virginity is single-use

State A's happy-path check (submit a rejected short passphrase, then a strong one) genuinely
unlocks the encrypted store on success — a real, working create-passphrase flow, exactly as
intended. That means **every subsequent walk run against the same data directory silently
degrades the state-A checks into no-ops** (the create-passphrase view is simply never shown
again, since the store is no longer locked). This was caught live: an intermediate walk run in
this session showed `state_a_first_launch` axes reading `"blocked"` in `coverage.csv` rather
than `"verified"`, traced to exactly this cause, and the final report below was produced only
after wiping `/tmp` state and relaunching state A fresh immediately before the last walk. A
future re-run of this harness against state A must do the same, or its two positive
confirmations will silently stop meaning anything.

---

## 3. Findings — final, stable run

Three consecutive identical walk runs after the last driver fix (§1); the numbers below are from
the last of them, on a freshly-wiped state A.

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

## 4. What this run does NOT establish

Per the brief's own honesty rails: this is a Chromium-in-a-remote-sandbox pass against a
450-article synthetic corpus, not the maintainer's live corpus (which never enters an agent
session by design), and not the queued Gecko/VM-verified bar. It does not re-litigate any
2026-07-22 finding beyond the two explicitly re-checked here (the topbar breakpoints and the CJK
keyword pills) — every other 2026-07-22 finding's disposition stands as that report left it. It
does not touch the Observatory, the inline-handler retirement backlog, or any of the five new
verticals — all explicitly out of scope for this session. And it does not exercise anything
requiring a local LLM/Ollama/GPU, or any networked path — airplane mode stayed engaged for the
entire run, by design.

---

## 5. Suggested next steps (not built this pass)

1. The 375px top-bar overflow (#7 above) — a design-scoped responsive-layout pass (collapse,
   overflow-menu, or reflow strategy for the sub-1024px top bar), building on the
   already-confirmed-working fix at 768px+.
2. A real, non-destructive import fixture the harness can trigger to exercise the post-import
   screen's actual content-rendering path (today it can only confirm the dialog *opens*).
3. Extend the driver's subtab drill to the World map's in-panel lens sub-controls one level
   deeper (each lens exposes its own overlay/granularity toggles not yet walked here).
4. Graduate this harness from a manually-invoked script to a scheduled/CI-triggerable job once
   the AppVM recursive-improvement runner (R3, `docs/design/RECURSIVE_IMPROVEMENT_RUNBOOK_2026-07-13.md`)
   is standing — the two share the same "real browser, real app, never the live corpus" posture.
