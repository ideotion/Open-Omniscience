# Systematic GUI Test & Critical Review — 2026-07-22

**Status:** executed. Brief of record: [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-22_GUI_SYSTEMATIC_TEST.md`](../design/AUTONOMOUS_SESSION_BRIEF_2026-07-22_GUI_SYSTEMATIC_TEST.md).
**Machine-readable companions:** [`findings.csv`](gui-test-2026-07-22/findings.csv) (72 merged findings) · [`coverage.csv`](gui-test-2026-07-22/coverage.csv) (179 rows) · [`killed_findings.csv`](gui-test-2026-07-22/killed_findings.csv) (7 refuted).
**Verification stamp:** the surfaces covered below graduate to **"Chromium-verified (remote sandbox) · awaiting human UX pass"** — this is explicitly NOT the queued Gecko-verified(VM) bar, and it does not replace a maintainer click-through.

---

## 0. What actually ran

A 100-agent orchestrated test pass drove a real Chromium browser (`/opt/pw-browsers`, pinned build 1194) against the live application, booted three separate times to represent the brief's three test states, each on a synthetic corpus seeded through the real ingestion chokepoint (`index_article` — real keyword extraction, When/Where/Who, sentiment, FTS):

- **STATE A** (virgin, port 8001) — first-launch/lifecycle flows.
- **STATE B** (empty, catalog-seeded, port 8002) — empty-state honesty pass.
- **STATE C** (populated, port 8000) — 490 articles across 8 languages (en/fr/de/ru/ar/zh/es/it), a 3-year publish-date spread, a seeded 3-source near-duplicate cluster with a shared outbound link, one nav-soup specimen, one mislabeled-language specimen, one empty-body specimen, a dense (60-point) and a sparse (7-point) commodity price series, and one sample each of law/wiki/newsletter provenance.

14 agents ran the coverage matrix, lifecycle flow, cross-cutting axes (themes/locales/breakpoints/a11y), and performance instrumentation in parallel; their 86 raw findings were deduplicated, then put through an **independent adversarial refutation pass** — a fresh skeptic agent re-reproduced every single candidate finding against a clean page load before it was allowed to survive. 7 were killed (see §7). I then **hand-verified all 5 P0s myself** with independent evidence beyond the automated skeptic pass (source-code citations and fresh live reproduction), plus a sample of 4 consequential P1s. All 9 confirmed with zero false positives. Total: 100 agents, 2,245 tool calls, ~33M tokens, run over multiple hours of wall-clock (heavily parallelized).

### The one honesty-critical result, stated first

**Across the entire run — thousands of captured network requests, every one of the 100 agents independently asserting it — zero requests reached any host other than `127.0.0.1`.** The airplane-mode socket-level guarantee held perfectly under adversarial, concurrent, multi-agent load. This is not a footnote; it is the app's core non-negotiable, and it survived the most aggressive test this app has likely ever been subjected to.

### Critical methodology caveat: read this before the findings below

**"384 total JS errors" is a misleading headline number if taken at face value — every one of the 8 walk groups plus the 3 cross-cutting groups that reported js-error counts independently confirmed that 100% of them were `console.error` "Failed to load resource: 429 (Too Many Requests)" lines, not JavaScript exceptions.** Zero `pageerror` (uncaught exception) events occurred across the entire test run, on any of the 100 agents, on any surface. The 429s themselves are real — `slowapi`'s fixed-window rate limiter (e.g. `100/hour` on `/api/articles`, `src/api/main.py:1116`) — but the STORM behavior is an artifact of this test's own design: 14 parallel agents, each running its own Playwright browser, all hammering the *same single server instance* on port 8000 simultaneously, generated request volume no real single user would ever produce. The in-workflow skeptic pass correctly killed 5 of 7 refuted findings for exactly this reason (§7). Where a genuine, single-agent-reproducible rate-limit finding survived (§2, `tight-rate-limit-cascading-429-retries`, P2), it is flagged as an OPTIMIZATION candidate (the limit may be tighter than normal navigation warrants), not a correctness bug — and the app's own behavior under this load was uniformly graceful: every group independently confirmed the UI degraded LOUDLY with a visible "The app is busy — retrying shortly…" toast, never silently or blank. That is a genuine FAILURE-lens pass, not a defect.

**One disclosed departure from the test brief:** the lifecycle agent, while testing the first-launch wizard's "Go online & start collecting" step on the fully isolated STATE A/D sandbox (no real corpus, no real user), actually completed the online transition once (rather than only cancelling the confirm step) in order to verify the wizard's consent-disclosure design end-to-end, then manually restored the instance to offline before finishing. This was necessary to produce finding `LC-WIZARD-ONLINE-NO-SEPARATE-CONFIRM` (§2) and is disclosed here rather than hidden.

---

## 1. Executive summary — top findings

| # | Severity | Finding | One-line impact |
|---|---|---|---|
| 1 | **P0** | Reader's "Related in your corpus" + near-dup badge query a **dead legacy DB table** (`article_keyword_association`), never written by the modern ingest pipeline | Silently, permanently non-functional for every article in any corpus built on the current pipeline — 100% reproduction rate |
| 2 | **P0** | The airplane-mode onboarding coachmark (`#net-coach`) **visually overlaps and pointer-blocks** the airplane toggle, language switcher, task-manager, and shutdown buttons | The exact control the coachmark exists to teach is itself unclickable while it's showing |
| 3 | **P0** | Any rejected passphrase (too short / mismatched) on first launch **hides the entire form**, leaving a blank white screen with the error message written into now-invisible DOM | A brand-new user's very first interaction with the app can dead-end at a blank page |
| 4 | **P0** | At 375px width, the airplane toggle, language switcher, task-manager, and shutdown button are **pushed off-screen** with zero visual affordance that a horizontal scroll exists | The sole informed-consent gate is unreachable on a phone-width viewport without an undiscoverable gesture |
| 5 | **P0** | The Settings text-size slider has **no accessible label whatsoever** (axe: `label`, critical) | A screen-reader user hears "slider, 88 to 124" with no indication of what it controls |
| 6 | P1 | A boot-ordering race (`_hydrateCardCorpus` runs before `_anRestoreTabs`) **destroys the persisted multi-tab analysis workspace** on every omnibar search opened in a new browser tab | The flagship "parallel named analysis tabs" feature never actually accumulates more than 1 tab via its real, documented entry point |
| 7 | P1 | Saving unrelated Settings → General preferences **silently collapses any of the 17 named themes down to plain Ink**, discarding the user's actual theme choice with no warning | A user who picked "Midnight" loses it the moment they save an unrelated setting |
| 8 | P1 | Browser Back while the Export/Backup dialog is open leaves the app **invisibly frozen** — the native `<dialog>` backdrop stays active while nothing renders it, blocking every click; only an undocumented Escape recovers | Reads as a total app hang with zero visual cue |
| 9 | P1 | The Governments → Law discoverability pointer reads "**0 tracked**" on a corpus with 23 real tracked documents, because it counts only baselined docs while the sibling subtab uses the same word to mean something else | Actively tells the user the law vertical is empty when it is not — the exact confusion this pointer was built to prevent |
| 10 | P1 | Insights → Convergence's window-days field allows up to 3650 but the backend caps at 90, and the error path renders literal text `[object Object]` | A confusing dead-end for a value the input field itself invites |
| 11 | P1 | Double-clicking a Home Lead card's "Open corpus" opens **two duplicate browser tabs** at the identical URL | A trivial, common accidental-repeat-click bug on the flagship entry point |
| 12 | P1 | `var(--warn)` pill text (LLM-offline pill, ~15 warning badges app-wide) falls to **1.87–2.42:1 contrast** in Dawn/Paper/Solar themes — badly below WCAG AA 4.5:1 | Same class of regression the caveat-color fix (invariant #23) was built to prevent, on a sibling color variable it didn't cover |

**Positive, explicitly-verified results worth recording** (the brief asked for a critical *view*, which includes what already works): the zero-egress airplane guarantee (above); Home's empty-state honesty (STATE B renders an explicit "No Leads yet" card, never blank, 0 console errors); the card-flip → caveat → "Open corpus" → exact-article-set spawn mechanism works exactly as documented; three previously-flagged known-open items were independently found **already fixed** — the Families "kind" dropdown no longer offers non-existent people/orgs/places options (it now has an honest hint explaining why), the "three contradictory moon-phase glyphs on one day" bug is gone (zero double-glyph days found in a full scan), and the post-import results headline is now Articles-first with a labeled breakdown (not a cross-table sum) on the primary corpus-restore path.

---

## 2. Findings (72 merged, most-severe first — full detail in `findings.csv`)

### P0 — 5 findings

All five were independently hand-re-verified by the orchestrating session with fresh evidence beyond the in-workflow skeptic pass (source-code citations and/or live DOM reproduction). See the executive summary for one-line descriptions; full repro/expected/actual/evidence is in `findings.csv` rows 1–5. Root-cause detail worth stating here since it changes the fix:

- **Reader Related/dup-badge (finding `reader-dead-legacy-table-related`):** confirmed via source that `article_keyword_association` (`src/database/models.py:748`) has **zero writers** anywhere in the live ingest path — `src/analytics/store.py`'s `index_article` (the actual per-article extraction chokepoint) only ever writes `KeywordMention` rows. The table is referenced only in its own model definition, the reader's broken query (`src/api/main.py:1763`), and `src/backup/merge.py` (carrying legacy rows through a restore, never creating new ones). The fix is to point the reader's query at `KeywordMention` (already the source of truth for every other keyword-driven surface in the app), not to repopulate the dead table.
- **net-coach overlap (finding `net-coach-blocks-topbar-buttons`):** confirmed by bounding-rect math (`coach rect x:1122-1392,y:8-181` fully contains the `#net-toggle` rect) and a real Playwright `click()` timing out. The coach is meant to be an "invitation layer" (invariant #14) that never blocks the button it points at.
- **Unlock blank-screen (`LC-VIEW-HIDDEN-ON-ERROR`):** root-caused in `src/static/unlock.html`'s `go(btn, fn)` — `_startPrep()` unconditionally hides `view-unlock`/`view-create`/`view-open` *before* the passphrase POST runs; its `catch` block writes the error text into `#msg2` and hides `view-preparing`, but never un-hides `view-create` again. Confirmed live: after a short-passphrase submit, `document.body.innerText.trim()` is the empty string.
- **375px overflow (`topbar-overflow-mobile-375-net-toggle-unreachable`):** confirmed via `getBoundingClientRect()` — all four controls report `left ≥ 375` (clientWidth), `scrollWidth` 862 vs `clientWidth` 375.
- **Font-size slider label (`font-size-slider-missing-label`):** confirmed via DOM inspection — `<input type="range" id="dr-font" ...>` carries no `label[for]`, `aria-label`, `aria-labelledby`, or `title`; the visible "TEXT SIZE" text sits in a sibling, unassociated `<div>`.

### P1 — 24 findings

Full detail in `findings.csv`. Notable clusters (each still a distinct row in the CSV, grouped here only for readability):

- **Architecture/state:** the analysis-tab-workspace race (#6 above, fully root-caused via `src/static/app.js:15293-17497`); the ghost-modal-after-Back freeze (#8); a double-click producing duplicate analysis tabs (#11); double-clicking "Add watch" creating duplicate watches.
- **Data honesty:** the convergence window/cap mismatch + `[object Object]` error (#10); the Law-tracked "0" pointer misreading its own baseline-vs-total semantics (#9).
- **Settings integrity:** the theme-select lossy overwrite (#7), confirmed via `src/static/app.js:4959-4970` — `syncThemeSelect()` buckets all 17 named themes into just light/dark/system for the General panel, and `saveSettings()` maps that 3-way bucket back through a hardcoded `{dark:"ink", light:"light", system:"system"}`, discarding the specific theme.
- **Accessibility/contrast:** `pillwarn-severe-contrast` (#12; measured across all 18 themes: 7 of 18 fail WCAG AA, ranging 1.87:1 in Dawn to 3.51:1 in Mint — the same `.pill.warn` class used on ~15 warning badges app-wide, including the persistent "LLM offline" pill).
- **i18n reactivity:** `home-i18n-mixed-language-glance` (switching UI language leaves part of the Home glance strip in the prior language), `home-lead-title-frozen-locale` (Lead card titles don't retranslate on a language switch), `hazard-caveat-untranslated` (a core honesty/consent disclosure paragraph has zero translation in any locale), `insights-landscape-headers-hardcoded`, `reader-i18n-dynamic-content-untranslated` (reader.js never calls the translation function — 3 of 10 tab labels and all dynamically-injected caveat/method text stay English regardless of language).
- **Layout:** `topbar-overflow-mainstream-widths` (the top bar overflows off-screen at 1024/768/601px too, not just 375 — body-level horizontal scroll on every mainstream breakpoint), `chip-button-color-contrast` (white text on accent-blue backgrounds at 2.88:1, nested count numbers at 1.04:1), `evidence-links-contrast-and-no-underline` (axe: link-in-text-block, serious, 24 nodes), `lead-card-nested-interactive` (axe: nested-interactive, serious, 23 nodes — the flip-card's outer `role=button` container contains further interactive controls), `home-recent-panel-hidden-on-error`, `insights-map-cjk-sentence-keywords` (unsegmented Chinese "top keywords" render as whole concatenated sentences on the Map view), `worldmap-fullscreen-hides-legend-caveat`, `mkt-002-stale-caveat-scale-toggle`, `help-md-linebreak-bug`, `an-mindmap-wrong-corpus-scope`, `home-opencorpus-recipe-promise-seed`, `netcoach-blocks-lang-switch` (a second, distinct button blocked by the same coachmark overlap as the P0).

### P2 — 38 findings (after merging cross-group duplicates)

Full detail in `findings.csv`. **Four clusters of near-identical reports were merged** here (a genuine cross-validation signal — the same defects were independently rediscovered by 2–4 different test groups working different surfaces):

- **`governments-tab-defaults-to-countries-not-law`** — reconfirms the standing known-open item #3 (§4): the Governments sidebar tab still opens on Countries, not Law, with only a small pointer chip hinting the law vertical exists. Independently found by 4 separate groups.
- **`llm-triage-airplane-mode-off-required-for-local-inference`** — the LLM/Ollama UI copy in more than one surface tells users to disable airplane mode for what should be loopback-only local inference (the standing known-open item #2). Found by 2 groups. One group additionally confirmed the *live* symptom does not reproduce today (a real `ECONNREFUSED` to `127.0.0.1:11434` rather than an airplane-block message on the bulk-summarize path) while another confirmed the UI *copy* and `src/llm/ollama.py`'s `_check_kill_switch` gate still show the blanket wording/gate the ledger tracks as pending — recorded as a mixed, not-yet-fully-resolved signal.
- **`mkt-007-adv-badge-unexplained`** — three distinct technical defects on the same "adv" badge (Commodities nav item), found by 3 groups: no tooltip anywhere, the literal string is never translated, and it concatenates directly onto the accessible name with no separator (`"Commoditiesadv"`, an axe violation). Kept as one entry since one fix (a translated, tooltipped, properly-separated label) addresses all three.

The remaining 35 are a genuine long tail, spanning: i18n coverage gaps on specific surfaces (Library storage panel, Collect panel + AI "Install Ollama" box, dialog intros, restore-checklist bidi-mixing in Arabic, theme-name translation collisions, the "N articles indexed" status line) — a *systemic partial-coverage pattern*, not isolated bugs, worth a dedicated i18n sweep rather than 10 individual fixes; a11y (reduced-motion ignored by the Leads carousel, the universal `#oo-tip` tooltip missing an accessible name, focusable-while-visually-hidden card-back content); Markets/Diagnostics UI debt (a "Compare" feature that's implemented but unreachable, per-feed verdicts with no live UI path, 6 stray download buttons the one-button-bundle ruling should have removed, the Storage footprint panel silently omitting the promised Ollama-store row instead of an honest unavailable state); and a handful of first-launch/wizard nits (`LC-TRENDS-KIND-GHOST-OPTIONS`, `LC-WIZARD-ONLINE-NO-SEPARATE-CONFIRM` — see §0's disclosed-departure note for full context, `LC-ERROR-TEXT-UNTRANSLATED`).

### OPT — 5 findings (each with a real measurement)

1. **`ins-subtabs-chatty-rate-limit`** — a single fast pass over all 9 Insights subtabs fires ~89 requests in <2s, 17% (15) throttled 429 (client retry recovers all within ~4s, no corrupted state).
2. **`reader-dupbadge-n-plus-1-decrypt-risk`** — a forward-looking risk flag: fixing the P0 dead-table bug above (recommended) will re-expose an N+1-style full-body decrypt (up to 40 articles per reader page view) unless the fix also bounds/caches the candidate query.
3. **`imp-password-field-warning`** — the standing known-open seed item #10b, confirmed present (3 Chromium DOM advisories on `/unlock`; not counted toward the JS-error tally since it's a `verbose`-level advisory, not an error).
4. **`boot-dupe-dbstats-schedstatus`** — Home boot fires duplicate concurrent identical GETs: `/api/database/stats` ×4 (3 at the exact same millisecond), `/api/scheduler/status` ×3 (2 simultaneous) — at least 2–3 independent code paths calling the same endpoint with no de-duplication.
5. **`library-and-insights-slower-first-paint`** — measured first-paint (fresh `page.goto`, networkidle): Home 1674ms, Insights **2614ms**, World map 1423ms, Governments 1504ms, Agenda 1439ms, Indices 1442ms, Commodities 1479ms, Library **2834ms**, Settings 1434ms. Library and Insights are ~1.8–2× the ~1400–1500ms baseline the other 7 tabs share.

---

## 3. Coverage matrix

179 rows total: **123 verified, 47 partial, 9 blocked** (full list in `coverage.csv`). Every partial/blocked row carries an explicit reason — no silent skips. The 9 blocked rows are all structural (a fresh-server-restart requirement, a genuinely absent fixture in the synthetic corpus, or a dead-code path with no live caller), never an "I didn't get to it."

Representative honest gaps (not defects, disclosed so they aren't mistaken for coverage): `#wiki-tc` dialog untestable (0 watched Wikipedia pages in the synthetic corpus); relock/wrong-passphrase on an already-unlocked instance untestable without a server restart (substituted with a direct API-level equivalent check, which passed); the `OO_DB_PLAINTEXT=1` legal-acceptance-bypass seed question (§4, item 1) genuinely could not be tested against the three long-running fixed instances provided.

---

## 4. Known-open cross-check (from the brief's §11 list)

| # | Item | Status |
|---|---|---|
| 1 | Post-import headline may sum cross-table rows | **Improved, not fully closed.** The primary corpus-restore path is confirmed fixed (Articles-first, labeled breakdown). One residual gap survives (`imp-fallback-unit-mix`, P2): a fallback path can still mix file-count and article-count under one unlabeled number. |
| 2 | Airplane mode may block loopback Ollama generation | **Mixed signal, not fully resolved** — see §2's P2 cluster note. |
| 3 | Governments tab discoverability (opens Countries, not Law) | **Confirmed still present**, independently by 4 groups. Merged into one P2 finding. |
| 4 | Inline `on*=` handler count is large | **Confirmed** (~309 via a rough grep), not itemized further per the brief's own scope. |
| 5 | i18n: untranslated chrome strings, roughly per surface | **Confirmed and quantified per-surface** (§2's i18n cluster; ~30 strings on Home in Arabic alone, plus specific per-surface counts recorded in the coverage notes). |
| 6 | Retired dead temporal-map JS unreachable | Not directly re-tested this pass (out of the assigned surface list); no evidence it became reachable. |
| 7 | Settings→Leads preview modes not graded onto Home | Not contradicted; no new evidence either way. |
| 8 | Conjunction-lens deeper views not surfaced in its payload | Not directly tested this pass. |
| 9 | El Niño agenda banners parked | Consistent with expectation — no banners rendered (no El Niño data in the synthetic corpus; this is expected, not a finding). |
| 10a | Does `OO_DB_PLAINTEXT=1` env-init bypass the legal-acceptance step? | **Blocked** — untestable against the three long-running fixed servers without a differing-env restart (§3, blocked rows). Still an open question. |
| 10b | `[DOM] Password field is not contained in a form` console verbosity | **Confirmed present** (OPT finding, 3 occurrences on `/unlock`; also on several Settings/backup dialogs elsewhere — `password-fields-outside-form-elements`, P2). |
| 10c | Families "kind" dropdown offering unpopulated kinds | **Resolved.** Confirmed via source: the dropdown now offers only `entities`/`all`, with an explicit honesty hint explaining the omission. Not a defect anymore. |

---

## 5. Performance measurements (full detail in the workflow's perf-agent notes; summarized here)

**Idle-poll census (Home, 60s window):** 44 requests total — `/api/scheduler/status` ×13 (~1/4.6s, somewhat denser than its own adaptive-poll model predicts for a confirmed-idle scheduler — flagged OPT-adjacent, not a fresh regression), `/api/system/network` ×9 (matches the documented adaptive fast=5s/slow=20s/quiet=45s model exactly), `/api/database/stats` ×4, `/api/briefing` ×4, `/api/insights/trending-windows` ×4, `/api/signals/alerts` ×4, `/api/articles` ×4 (rate-limited in a follow-up sample — the shared-server artifact, §0), `/api/sources` and `/api/sources/unmanaged-languages` ×1 each (one-shot at boot). No polling-storm regression beyond the known, documented cadences.

**First-paint per tab:** see OPT finding #5 above.

**Long tasks (50ms threshold):** zero long tasks recorded opening World map, spawning an analysis window via search, or switching a Settings theme — a clean, positive result on this 490-article corpus.

**DOM node count:** Home 4157, Insights 2959, World map 3333 — none in an alarming range at n=490 articles; flagged only as an untested scale-extrapolation question (not a current defect; a deeper investigation refuted the speculative "risk" framing of one killed candidate finding, see §7).

**Request waterfall (Insights → Trends, first load):** 24 distinct requests, ~5.99s wall-clock span but only ~1.3s summed individual duration — the gap is non-network idle time between three sequential batches (~1.04s, ~1.61s, ~1.94s gaps), a parallelization opportunity worth a follow-up look, not a broken feature.

---

## 6. Cross-cutting axes

- **Themes (18):** `.card-caveat` contrast is clean across all 18 (6.29–10.5:1, matching the shipped invariant #23 fix). Broadening to the sibling `.pill.warn` class (also explicitly in scope) surfaced the real gap in §1/§2.
- **Locales (12) + RTL:** the core "one click retranslates the whole UI" promise holds for primary chrome in all 12. Arabic RTL correctly sets `dir=rtl`, mirrors the sidebar, and reverses the subtab strip; the World map's 15 in-map controls don't overlap but also don't mirror their physical position (a P2 finding). Untranslated-string counts were quantified per surface (not exhaustively enumerated, per the brief's own scope) and feed the i18n cluster in §2.
- **Breakpoints (5) + a11y:** the app degraded loudly and gracefully under a self-inflicted rapid-navigation rate-limit storm (a genuine FAILURE-lens pass). Keyboard focus order, `#ins-subtabs` roving-tabindex, and Escape-closes-palette-with-focus-restored all worked correctly. `prefers-reduced-motion` is honored by static CSS but NOT by the Leads carousel's JS auto-rotation timer (P2).
- **Import/Export:** zero true JS exceptions across ~20 script runs; the zero-egress guarantee held explicitly through both the export run and a state-abuse (dialog-stacking) test.

---

## 7. Skeptic-killed findings (7 — full reasoning in `killed_findings.csv`)

All 7 were genuinely reproduced at the symptom level by the skeptic agent but refuted at the causal-claim level:

- **5 of 7** trace to the shared-test-server rate-limit artifact described in §0 (a fixed-window `100/hour` limiter on hot endpoints, exhausted by 14 concurrent agents' traffic against one server instance — real rate-limiting, but not a single-user-reproducible bug): `articles-endpoint-persistent-429-silent-degradation`, `worldmap-429-during-lens-exploration`, `mkt-001-boot-rate-limit-storm`, `rate-limit-429-storm-on-idle`, `activity-poll-cadence-near-5s-floor` (this last one was root-caused precisely: TWO independently-documented pollers both hit `/api/scheduler/status` while Home is active, explaining the "denser than predicted" cadence honestly rather than as a regression).
- **1** (`insights-trends-slow-settle-nonnetwork-gaps`) was refuted by direct re-measurement: the actual Trends-subtab endpoints resolved in 64–140ms, an order of magnitude faster than the original claim.
- **1** (`dom-density-extrapolation-risk`) had its raw numbers confirmed (same order of magnitude) but its speculative "scale risk" conclusion refuted after a deeper tag/role breakdown of the DOM.

---

## 8. What this run does NOT establish

Per the brief's own definition of done: this is a Chromium-in-a-remote-sandbox pass, not the human UX click-through, and not the Gecko/VM-verified bar. It ran against a 490-article synthetic corpus, not the maintainer's live corpus (by design — the real corpus must never enter an agent session). Several coverage gaps are structural and disclosed (§3, §4): the `OO_DB_PLAINTEXT` legal-acceptance-bypass question stays genuinely open, and a true relock/wrong-passphrase click-through on an already-running instance was substituted with an equivalent API-level check. No `UiWalkDriver` implementation for `src/monitoring/ui_walk.py`'s row-8 harness was built this pass (skipped without guilt per the brief's own allowance, given the scope already delivered) — that remains a clean follow-up.

---

## 9. Suggested next steps (not built this pass — report-first per the brief's anti-scope)

Ordered roughly by severity × ease:

1. Fix the reader's Related/dup-badge query to read `KeywordMention` instead of the dead `article_keyword_association` table (P0, isolated one-file fix per the root-cause above).
2. Fix `unlock.html`'s `go()` catch handler to re-show `view-create`/`view-unlock` instead of leaving them hidden (P0, isolated).
3. Fix `#net-coach`'s CSS so it never overlaps a clickable control it doesn't own — either a `pointer-events: none` on everything but its own buttons, or repositioning logic that respects neighboring elements' rects (P0, shared root cause with the P1 `netcoach-blocks-lang-switch`).
4. Add a responsive strategy for the top bar below ~1024px (an overflow menu, or wrapping) — currently every mainstream mobile/tablet breakpoint loses reachability to the airplane toggle (P0+P1, one fix covers both).
5. Add a label to `#dr-font` (P0, one-line fix).
6. Fix the analysis-tab boot-ordering race (`_anRestoreTabs()` before `_hydrateCardCorpus()`'s spawn, or merge rather than overwrite) (P1, restores a flagship feature).
7. Stop `syncThemeSelect()`/`saveSettings()` from lossily bucketing themes (P1).
8. Close the dialog (or block Back) on `popstate` while any `<dialog>` is open (P1, likely fixes it for every dialog in the app at once given the shared native-modal mechanism).
9. A dedicated i18n sweep, given the pattern in §2/§6 is systemic across many surfaces rather than isolated.
10. The `var(--warn)` contrast fix, mirroring the invariant #23 precedent already applied to `var(--caveat)`.
