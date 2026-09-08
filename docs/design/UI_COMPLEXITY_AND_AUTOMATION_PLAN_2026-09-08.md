# UI complexity & automation — findings and plan (2026-09-08)

> Produced by the live visual audit of 2026-09-08 —
> see [`docs/audit/11_VISUAL_UI_AUDIT_2026-09-08.md`](../audit/11_VISUAL_UI_AUDIT_2026-09-08.md) for the
> method, the fleet and the honest scope. **Report-only: nothing here was implemented, and nothing here
> is a maintainer ruling.**
>
> This document answers the strategic half of the commission, in the maintainer's own words:
>
> > *"We also need to address the app's current UI complexity. There are too much things the app can
> > currently offer, that it becomes difficult for a user to understand and be aware of all the current
> > functionalities. As a consequence, the user might miss some obvious things. In summary, the app
> > should automate more stuff, and it's for us to decide which stuff to automate so that it doesn't go
> > in the way of our high ethical standards and moral, and the app's core purpose to help investigate
> > and search for truthful, unbiased, and evidence based events to report to the overall population for
> > the sake of transparency, freedom of information and democracy."*
>
> **How it was produced.** Seven live inventories against a running, populated instance (capability map,
> backend-vs-frontend gap, settings inventory, first-run journey, a 24-goal task-based discoverability
> test, vocabulary/mental-model, docs-vs-reality), then a cognitive-load model, an automation-candidate
> pass and an adversarial ethical screen, then **three independent competing architecture proposals**
> scored by a **four-lens judge panel** (ethical / new user / power user / feasibility), then this
> synthesis, which takes the winner as the spine and grafts in — with attribution — the ideas the judges
> flagged from the runner-up.
>
> **Two honest notes about the process.** (1) One of the three proposal agents returned a placeholder
> (every field the literal string `test`). It was **not** quietly dropped: it went to the panel like the
> others and scored 2–3/100 on every lens, which is recorded here as evidence the judging pipeline
> discriminates rather than rubber-stamps. A replacement proposal for that angle (task-first / verb-first)
> was commissioned separately and, where it lands, is appended as §11. (2) The judges disagreed —
> the winner on three lenses lost the new-user lens — and §6 adjudicates that disagreement explicitly
> rather than averaging it away.
>
> **The single most transferable idea in this document** is §5 item 6: a *mechanically enforceable*
> grammar constraint on how the app is allowed to describe its own automated actions. It exists because
> the ethical judge's stated fatal flaw in the winning proposal was that its central promise was
> "enforced by nothing but prose" — and this project already has the machinery to do better
> (`CardSchemaError` enforces card shape the same way).

---

# UI complexity & automation — findings and recommendation

**Scope of this report:** synthesizes five live-audit inventories (capabilities-ui, capabilities-backend-unsurfaced, settings-inventory, plus a cognitive-load model and an automation-candidates pass grounded in direct source reads), three competing redesign proposals scored against each other by a four-lens judge panel (Ethical / New User / Power User / Feasibility), and this session's own adjudication of where the judges disagreed. The winning proposal, **Rings, not gates**, is the spine; two ideas the judges independently flagged from the runner-up, **Works While You Sleep**, are grafted in with attribution. The third submission (`test1`) contained no design content (every field was literal placeholder text) and is excluded from all synthesis below except as a data point that the judging pipeline worked (it scored 2–3/100 on every lens).

---

## 1. How complex is it, measured

**Capability count.** 258 distinct capability rows were catalogued from a live, populated-corpus instance (port 8017) plus source cross-read: 256 reachable + 2 orphaned/unreachable. Depth distribution from a cold `/` load: **depth 1 = 24, depth 2 = 96, depth 3 = 84, depth 4+ = 52.** The deepest reachable actions — including two entire surfaces, **Custody and Integrity** — sit at depth 4 (`Settings → Advanced → [fold] → action`), with a depth-2/3 shortcut available only through the command palette.

**Where the controls actually live.** `Settings → Advanced` alone, with all 11 `<details data-adv="...">` folds expanded, renders **≈1,684 controls** — 12× the next-largest ordinary surface (Search, at 135 buttons + 5 inputs). The single largest fold is Keywords at **1,317 buttons**; Sources is 162; Calendars is 124; Diagnostics is 27. By contrast the entire rest of the app outside Advanced — 15 other main surfaces — totals well under 1,000 controls combined.

**Cognitive Load Score (CLS), modeled 0–10 across six axes** (visible controls, affordance-type count, simultaneous independent decisions, information density, nesting depth, new-concept count): three surfaces break the pattern the other thirteen follow —

- **Settings → Advanced, all folds expanded: CLS 9.4, off-scale** — every axis maxes at once.
- **Search: CLS 6.8** — driven entirely by *entry-point depth*, not on-surface load; once reached it's a modest 5-affordance-type, depth-2 surface. It is confirmed to be the app's **one and only palette-exclusive capability** — no sidebar or top-bar equivalent exists anywhere (capability #207).
- **Settings → Cards: CLS 6.6** — driven by **D** (simultaneous decisions), not raw control count: 37 independent, non-mutually-exclusive Lead on/off toggles live on one screen at once, alongside 18 numeric tunables the app already computes safe defaults for.
- Runners-up: Observatory (6.1, driven by 5 unglossed new nouns — galaxy/nebula/orbit/constellation/reference-star — with **zero coverage in any of the 4 shipped docs**) and Help (5.9, driven by density — 167,022 characters, the largest content mass in the app).

**Settings inventory.** ≈144 individually-addressable rows across 9 subtabs: **6 ETHICAL, 6 A11Y, ~10 LOAD-BEARING, ~90 AUTOMATABLE, ~6 DECORATIVE, 13 DEAD** (the Quality-gates fold's 13 "tunables" are rendered as read-only `<span>`s styled identically to the 55 genuinely-editable Cards controls — a user cannot tell, by looking, which numbers can move).

**Backend-vs-frontend gap.** Of 662 total API operations (618 paths), **224 (34%) have zero frontend caller.** 56 of those are self-declared maintainer-only diagnostics (correctly unsurfaced). Of the remaining ~168, most are complete, tested, production-looking features with no click path at all — not an obscure one, none.

**Duplication and the palette's own gap.** 9 confirmed duplicate entry points (task-manager open, sidebar-collapse, Observatory reset, 5 paths into Analyze, source-profile lookup, Help docs, "Track Wikipedia now," "Collect now," "Export/Back up") — mostly benign. In the opposite direction, the command palette's static Pages list (`NAV`, `app-shell.js:21-42`) **omits Feed and Observatory** — the two largest sidebar surfaces by button count (101 and 98 respectively).

---

## 2. Where awareness actually breaks — the 15 things a user will never find

Ranked by **value forgone = (how substantial/unique the capability is) × (how completely it is hidden)**.

| # | What's missed | Why it matters | Why it's missed |
|---|---|---|---|
| 1 | Full inferential-statistics engine (t-test/ANOVA/Pearson/Spearman/Mann-Whitney/CI) | 9 complete, honesty-compliant (method+n+p, no composite score), tested endpoints | Zero frontend caller anywhere — `src/api/analysis.py:67-124` |
| 2 | Source Groups + Batch Ops + Discovery (24 routes) | Largest single unsurfaced feature by route count; exactly what an operator of 3,618 sources needs | Zero UI trace; the app's own "batch" button hits a different, unrelated endpoint — `src/api/source_management.py:781-1397` |
| 3 | 3 of 4 Conjunction-Lens views (per-article intensity, conditional trend, vocabulary contrast) | Pure, unit-tested functions; the 4th sibling (corpus-algebra) is wired and proves the UI pattern | **No endpoint exists at all** — `src/analytics/conjunction.py:163-294` |
| 4 | 6 manipulation-pattern detector cards (copypasta, flooded-topics, headline-body-mismatch, manufactured-emergence, recycled-claims, source-laundering) | Fully-built, honesty-compliant ("names the structure, never intent"), numbered #3/#4/#7 implying an existing convention | Not wired into any Insights subtab |
| 5 | Custody/tamper verification for the article you're reading | Core honesty-by-construction feature | Reachable only at depth 4 or via palette; the reader has **zero** custody references and no id display to even use it with |
| 6 | Leads 2.0 (evidence chips, prominence sort, `card_deltas` lifecycle diff) | Home's own stated design, mostly built (`GET /api/insights/leads-view`); default output is byte-identical to today's, so wiring is near-zero-risk | Home never calls `leads-view`; only one field reaches a hover tooltip |
| 7 | The Observatory tab itself | Full main-nav, invariant-protected, novel whole-corpus view | Missing from the palette's Pages list; zero coverage in any of the 4 shipped docs |
| 8 | The FDR-corrected "bury" signal (topics with almost no sources) | Directly answers "what am I under-covering" | Only a raw JSON-download button in a collapsed Advanced→Stats fold; 3 plausible dashboards checked, none answers the question |
| 9 | Task Manager's Coverage subtab (per-tag scraping reach, PR #534) | Ledgered as shipped, tested, invariant-protected | The **reachable** `/tasks` page's tab set (Processes/Performance/Queue/Schedule/Sessions) doesn't include it — it only exists in a dead, orphaned `#vitals-pop` dialog nothing opens |
| 10 | A second backup-restore pathway (staged preview→commit, resumable reindex-backlog) | Both APIs claim in their own docstrings to back "the unified Import dialog" | Entirely unreferenced by frontend; ambiguous whether it's dead code or an unmigrated newer path |
| 11 | Loaded-language inline highlighting | Engine returns exact char-offset spans "so a reader surface can highlight exactly what was flagged" | Deliberately deferred (offset-drift risk); reader shows only a density number + chip list |
| 12 | Two-commodity price-vs-coverage comparison | Parallels Indices' working multi-select pattern | `_anCommodity` is hard-coded single-value; no multi-select ported over |
| 13 | Self-verifying the no-telemetry claim in-app | Answers the exact question a skeptical user should be able to ask | Only checkable via an external JSON debug-bundle download; no in-app network-activity view |
| 14 | Insights → Lunar correlation screen (FDR-corrected moon-phase/keyword correlation) | Complete, rigorous, self-contained | Zero doc coverage; sits behind a sibling tab-label collision ("Trends" vs. "Explore") that already costs backtracking clicks |
| 15 | Read-only quality-gate tunables that *look* editable, styled identically to Cards' 55 genuinely-editable tunables — inversely, the fillable "Add a source" form nobody reaches because it's subtab 8 of 9 | Double-sided miss stemming from the same seam | `settings-inventory` F2 + `task-based-discoverability` task #5 |

**Diagnosis, in one sentence:** awareness does not degrade gradually with rising complexity — it breaks at **exactly one seam**: the boundary of the `<details data-adv="...">` fold, at `Settings → Advanced`, 9th of 9 Settings subtabs, itself collapsed by default, guarding 11 further-collapsed folds named after implementation concerns (Sources, Collect, Qualification, Stats, Keywords, Calendars, Diagnostics, **Safety**, Uninstall, Bulletin) rather than user goals. "Safety" alone hides Custody, Integrity, at-rest encryption, corpus-integrity-checking, and fetch-mode — five distinct, differently-audienced concerns collapsed under the one word in the whole Settings nav most likely to make a non-technical user's eyes slide past it.

---

## 3. What is already built and simply not surfaced — the cheapest wins in the report

These require **zero new backend logic** — pure wiring or restoration of an already-computed, already-tested engine:

| Item | Engine | Effort | Fix |
|---|---|---|---|
| Coverage subtab restoration | `src/scheduler/coverage.py`, `GET /api/scheduler/coverage` | **S** | Port `_renderCoverage`'s already-correct logic from the dead `#vitals-pop` markup (`index.html:160-189`) into `taskmanager.html` as a 6th tab. Zero backend work. |
| Bury-signal table | `/api/signals/bury` (FDR-corrected) | **S** | Render the existing payload as a sortable Insights table instead of a `window.open(...,'_blank')` JSON-download button |
| Indices/Markets manual refresh | `loadIndicesData()` / `loadMarketData()`, `app-markets.js:395-411,1393-1406` | **S** | Both functions are complete, correctly `ensureOnline`-gated, and have zero callers — their trigger buttons were removed in a past restructuring, leaving `#idx-status`/`#mkt-dash-status` permanently empty. Re-add one button each. |
| `card_deltas` lifecycle badge | `src/briefing/leads.py:182-216` | **S** | Pure, tested function, called by nothing — not even by `assemble_leads_view` itself. Store the prior briefing run, call it, badge the card back. |
| Leads-view evidence chips + prominence sort | `GET /api/insights/leads-view`, `src/briefing/leads.py:91-131,233-291` | **S** | Endpoint's own docs state `sort=default` is byte-identical to today's Home output — swap Home's fetch target, render chips on the flip-card back. |
| Custody auto-verify + reader bridge | Existing hash/signature check + Custody surface | **M** | Add a "Verify" tab to the reader, pre-filled with the open article's id; badge pass/fail, never a fabricated "tampered" claim. Ranked #1 by the discoverability audit's own priority list. |
| 3 unwired Conjunction-Lens functions | `src/analytics/conjunction.py:163-294` | **M** | Mirror the existing `corpus_algebra` endpoint pattern (`src/api/insights.py:910-925`) for the other three; add matching Analyze panels. |
| Mini trend-chart x-axis fix | `app-corpus.js:1290` (`X = i => ...` index-positioned) vs. `_window_daily_series` (`queries.py:1756-1770`, zero-count days omitted) | **S** | Switch to `ooViz.linearScale` (already shipped, already used elsewhere) over the real date range — a genuine honesty violation under invariant #16, currently silent |
| Command-palette Pages list gap | `app-shell.js:21-42` `NAV` array | **S** | Add Feed and Observatory; better, generate the list from the live sidebar registry so this class of drift can't recur |
| `#vitals-pop` / `#corpus-win` dead markup | — | **S** | Both are self-documented in-code as retired/superseded; delete outright |

Everything in this section is Small-to-Medium effort, ships independently, and touches no invariant that needs amending except the task-manager one (§7).

---

## 4. The automation set

Columns: what the app decides on its own · what it must still disclose · verdict · effort · engine already computing it.

| Candidate | App decides | Must disclose | Verdict | Effort | Engine |
|---|---|---|---|---|---|
| Qualification/re-qualification ride-along made **visible** | Nothing new (already runs) | Live count judged/admitted/rejected this pass | 🟢 GREEN | S | `src/scheduler/settings.py` (already automatic, budget=5/pass) |
| Scale `qualification_per_pass` to measured backlog (5–25 band) | The per-pass number, within a disclosed band | "Currently judging N/pass (backlog: M unqualified)" | 🟢 GREEN | S/M | Admission gate already returns backlog size |
| Coverage-biased discovery/qualification ordering | Which under-covered tag goes first | "Next up: `<tag>` (12% reach)" in Coverage tab | 🟢 GREEN | M | `src/scheduler/coverage.py` |
| Baseline keyword tagging on qualification | Tag assignment (deterministic, fixed taxonomy — not a judgment) | Source profile: "tags: auto-applied at qualification" + one-click re-tag | 🟢 GREEN | S | Existing "Apply baseline tags" handler, re-triggered |
| Never auto-enable a discovered/promoted source | — (explicit non-automation) | — | **Hard boundary, not a candidate** | — | `src/catalog/discover.py:10` — "never enables… the free pass" |
| Silent auto-throttle of ride-alongs under measured contention | Per-pass budget reduction | One-line log entry every time it fires, never silent | 🟢 GREEN | M | `collect_perf.py`'s existing contention signal, second consumer |
| Auto-resume a **system**-paused (never operator-paused) download | Resuming, once contention clears | Auto-resume event logged in the job row | 🟡 AMBER | S | `DumpDownloadManager.resume`/`OsmDownloadManager.resume` already exist |
| Insights auto-indexing extended with a velocity readout | Nothing new | "Indexed N in the last pass, M remaining" (no ETA) | 🟢 GREEN | S | Already shipped (invariant #21); pure disclosure add |
| 3 unwired Conjunction-Lens views wired live | Nothing (pure read computation) | Method+caveat per panel (co-occurrence, never causation) | 🟢 GREEN | M | `conjunction.py` |
| Near-dup/echo cluster auto-collapse in Feed/Search (+expand chip) | Grouping only, never hiding | "measures text overlap, not meaning, truth or quality" verbatim on the chip | 🟢 GREEN | M | `src/signals/near_dup.py` (MinHash+LSH, already used elsewhere) |
| `leads-view` wired into Home (chips + prominence sort) | Nothing (default output = today's, byte-identical) | Chips ARE the disclosure | 🟢 GREEN | S | `leads.py` |
| 6 manipulation-pattern detectors, opt-in "Patterns" lens | Which structural pattern crossed its own threshold | "Names the structure, never intent" on every card | 🟡 AMBER — **ship default-OFF, field-validate before default-on** | M | 6 fully-built `/api/insights/*` endpoints, unvalidated at corpus scale |
| Custody auto-verify on article open | Pass/fail hash/signature check (deterministic) | "Confirms this copy matches what was logged at ingest — does not confirm the original source was truthful" | 🟢 GREEN | M | Existing custody verify mechanism |
| Full stats engine surfaced via a seeded "Compare two selections" panel | Nothing (arbitrary array input, no corpus judgment) | Method+statistic+p-value+n; explicit "significance is a math fact about the sample you chose, not proof of a claim's truth" | 🟡 AMBER (real new UX, not a wire-up) | M/L | `src/api/analysis.py:67-124` |
| Idle-triggered VACUUM/integrity check | Timing only | One-line post-hoc disclosure ("Housekeeping ran while idle") | 🟢 GREEN | S/M | Existing manual buttons, gated on scheduler-idle state |
| Auto-scheduled local backup on growth threshold | Timing only, same export format/path | Opt-in confirmation + visible backup history list | 🟡 AMBER | M | Existing export mechanism |
| "Automatic" AI backend pre-selection with reasoning shown | Backend choice | "Chose Ollama: no GPU detected. Change in Backend below." | 🟢 GREEN | S (verify preflight runs proactively first) | Implied by existing `llm_allow_impractical_hw` |
| Background AI sweeps default-ON (langdetect/keyword-triage/source-tags/perception-extract) | Nothing (local-only measurement, no score) | First-run wizard disclosure naming local compute cost | 🟢 GREEN | S | 4 existing sweep checkboxes, currently default-off |
| Watch **suggestion** from a recurring Lead pattern | Nothing — suggestion only, one-click create or dismiss | "This topic reappeared in 3 of your last 5 briefings" | 🟡 AMBER | S/M | `card_deltas`' identity-matching, reused |
| Auto-promote a discovered/qualified source | — | — | 🔴 **RED** | — | Crosses `discover.py:10`'s explicit boundary |
| Auto-collapse a detected coordinated-actor network | — | — | 🔴 **RED** | — | Governance rule 6 — de-amplification must stay user-applied and reversible |
| Auto-prune keywords from the index | — | — | 🔴 **RED** | — | A standing content decision with no per-instance human click |
| Acting on a qualification score (stopping collection) rather than displaying it | — | — | 🔴 **RED** | — | No composite/derived score may drive a standing action |
| OpenTimestamps anchoring firing per-ingest without its existing one-time transition consent | — | — | 🔴 **RED** | — | Would violate invariant #14f, already hard-won |
| Removing the 37 per-Lead-type ON/OFF switches (only numeric tunables may Ring-defer) | — | — | 🔴 **RED** | — | A content-inclusion category must stay individually disable-able |
| Scheduler autostart-at-boot bypassing per-session online consent | — | — | 🔴 **RED**, and currently **dead+misleading** | — | Nothing in the boot path has read `settings.autostart` since the airplane-mode-by-default ruling; the checkbox persists but does nothing — **delete it**, don't reactivate it |

**14 GREEN, 6 AMBER, 7 RED** (rulings inherited from the automation-candidates and ethical-screen analyses; adjudicated here where the source evidence disagreed — see §5, item 6, on the one correction made to the source report's own scheduler-autostart finding).

---

## 5. The decision test for future automation

Applicable by any engineer, without asking the maintainer, before wiring a new automatic behavior:

1. **Same-outcome test.** Does the default (`sort=default`, baseline behavior) produce output byte-identical, or provably equivalent, to what a human would get today without the automation? If yes, lean GREEN regardless of scale.
2. **Content-judgment test.** Does the action decide *what is true, trustworthy, important, or safe to include* (a score, a promotion, a collapse, a prune)? If yes → RED, no matter how well-tested the underlying measurement is. Measurement and judgment are different acts even when the same function computes both.
3. **Consent-boundary test.** Does the action cross from local compute into a network egress the user has not already consented to for this exact transition? If yes, it needs its own one-time, transition-scoped, explicitly-worded confirm (the `#14f` OpenTimestamps pattern is the template) — never a re-ask per occurrence, never a silent pass-through.
4. **Reversibility + inspectability test.** Can the specific action be individually found, explained (method + exact threshold/rule + n), and undone by the user, without needing to understand every *other* automated action the app has taken? If the action can only be undone in bulk or is invisible until something goes wrong, it is not yet safe to automate.
5. **Honesty-composition test.** Does disclosing the action require inventing a new composite number, or can it be stated in the app's existing method+caveat+n vocabulary? An automation that needs a new score to explain itself has smuggled judgment back in under measurement's name.
6. **Vocabulary-grammar constraint** *(grafted from Works While You Sleep — see §6)*. Any log/disclosure string describing an automated action in the source-admission, keyword-pruning, or coordination categories is **mechanically forbidden** from ending in a decision-verb (*enabled, removed, deprioritized, decided*) — only measurement-verbs are permitted (*staged, surfaced, proposed, flagged, measured*). This is enforceable the same way `CardSchemaError` already enforces card shape, and it exists specifically because tests 1–5 above are judgment calls a reviewer makes once, while this one is a string a test suite checks on every commit — it is the only item on this list that survives a maintainer not being in the room.

Rule of application: an automation passes only if it clears 1 **or** passes 2–4 together; nothing in §4's GREEN column needed 3 independently (all GREEN items are either fully local or ride inside an already-consented online pass) — this is a load-bearing fact, not a coincidence: **no proposal in this report introduces a new autonomous network-consent dial.**

---

## 6. The recommended architecture

**Spine: Rings, not gates** (ranked #1 on Ethical 78/100, Power User 68/100, and Feasibility 64/100 — 3 of 4 judge lenses). Its core idea: **Rings control what is *pinned*, never what is *reachable*.** Reachability (command palette, Search, a permanent "Show more" row) is 100% complete at every tier from second one; pinning (what's sitting in the sidebar or expanded in Settings by default) is what grows on explicit, reversible, one-click request. Ethical and safety surfaces are pinned identically at every tier with zero exception — this is what let it win the Ethical lens despite the New User judge preferring the runner-up's flatter always-everything-visible layout (see adjudication below).

**Two ideas grafted in from Works While You Sleep**, the runner-up that won the New User lens (66/100) specifically by removing the app's two worst navigation cliffs:

- **Graft 1 — the Explore merge.** *(New User judge, verbatim: "the single most valuable idea to steal.")* Today, Search has no sidebar entry at all — it is the app's one confirmed palette-exclusive capability — and reaching Analyze requires either a 4-click Search round-trip through a **separate browser window**, or one of four other fan-in paths (Home card, Feed chip, palette typed-live shortcut). Merging them into one first-class sidebar surface, **Explore** — a query box at top, the same Analyze subtabs (Overview/Keywords/Trend/Mindmap/Articles/When-Where-Who/Links/Related/Sentiment/Sources/Competitive/Advanced) rendering inline the moment results return, no second window — removes both cliffs at once and gives the app's single largest surface (135 buttons) a real, one-click home for the first time.
- **Graft 2 — the Ledger's grammar-enforced vocabulary.** *(Ethical judge's stated fatal flaw in Rings-not-gates: its "navigation only, never judgment" promise for the promotion-suggestion banner "is enforced by nothing but prose"; the Power User and Feasibility judges independently named the same mechanism as "the single most portable honesty-by-construction technique in the whole panel.")* Every automated action anywhere in the app — not just Ring promotions — writes one entry to a small, append-only Activity Ledger in a fixed shape (`what_happened / why / touched / caveat / budget / reversible / undo`), and that string is mechanically barred from ending in a decision-verb for the three judgment-reserved categories (§5, item 6). This closes the exact gap the Ethical judge identified without importing the rest of Works While You Sleep's architecture (its "Needs You" triage queue and its default-on backend automations were rejected — see §9).

### Surface-by-surface disposition of all 16 current surfaces + Task Manager

```
NOW        Home
EXPLORE    Feed · Explore (merged Search+Analyze) · Insights · Observatory · World map · Governments · Agenda
DATA       Indices · Commodities · Library
TRUST      Trust (merged Custody + Integrity)
SYSTEM     Settings · Help
```
plus a permanent **Activity** entry hosting the Ledger (§6, Graft 2) and the restored Coverage tab.

| Surface today | Ring | Change |
|---|---|---|
| **Home** | 0 (pinned always) | Unchanged shape (invariant #19, #23 flip-card). Gains: `card_deltas` badge + leads-view evidence chips + prominence sort on the card back (§3); vocabulary fix — Overtold/Undertold/Keep-watching/Context tab buttons finally get the `title=` the manual already has written for them, closing a confirmed zero-hover-text gap for free. |
| **Feed** | 0 (pinned always) | Unchanged. Gains a palette entry (straight omission fix) and near-dup cluster grouping (§4). |
| **Trust** (new — Custody + Integrity merged) | **0 (pinned always, every Ring, no exception)** | Promoted from depth-4-inside-a-Settings-fold to a top-level sidebar entry. Reader gains a "Verify" tab pre-filled with the open article's id (§3). |
| **Search + Analyze → Explore** | 1 | Merged per Graft 1. Hosts the 3 newly-wired Conjunction-Lens panels and the seeded stats-engine "Compare two selections" panel (§4) once built. |
| **Insights** | 1 | Same 9 subtabs. Rename `#ins-trends` → "Rising now" to stop colliding with Explore's own per-term trend chart (a confirmed mislabeling costing backtracking clicks). Bury-signal table lands here as a real subtab, not a download button. |
| **Observatory** | 1 | Unchanged mechanics. Palette-list fix (§3). One-time orientation card the first time it's opened, closing the 5-unglossed-nouns gap without adding persistent chrome. |
| **World map, Governments, Agenda, Indices** | 1 | Unchanged. Agenda gains the deduced-date recurrence note (worded as measurement, never narrative — "this date has shifted 3 times across your corpus"). |
| **Commodities** | 1 | Gains the multi-select "Compare (n)" pattern already proven on Indices (§2, item 12). |
| **Library** | 1 | Promoted conceptually to the "corpus health" home: absorbs the restored Coverage view, the bury-signal's sibling composition view. |
| **Settings** | 0 dial, 1/2 content | Nine tabs collapse into five goal-named sections (Appearance, General, Collect & sources, AI & models, Data & backup) plus an always-expanded Safety block (no fold) for encryption/fetch-mode/consent. **The word "Advanced" is deleted** — not renamed. A new **"Maintainer tools"** link (the 56 self-declared diagnostics routes) stays outside the Ring ladder entirely, reachable only via palette + one link, because it is a different audience, not a power tier. |
| **Settings → Cards** | 1 (families) / 2 (tunables) | 8 family toggles always visible at Ring 1, each with its own "Fine-tune →" to the underlying producer toggles (2 clicks, same depth as today); the 18 numeric tunables move one layer deeper, never removed. |
| **Task Manager** | 0 (pinned, via Activity) | The pop-up-window (`/tasks`, taskmanager.html) and the orphaned in-page `#vitals-pop` **consolidate into one implementation**: a permanent sidebar tab, Right-now lens (live job/queue/schedule state) + Ledger lens (Graft 2). Coverage restored (§3). |
| **Help** | 0/1 | Unchanged content. TOC anchor-link bug fixed (headings never emit `id=`, so the first click currently ejects the user to Home). |

**Automation defaults set per §4's GREEN list ship inside this architecture from day one** (qualification-ride-along visibility, coverage-biased ordering, baseline tagging, near-dup grouping, leads-view chips, background-AI default-on where hardware preflight allows) — Rings reduce *clutter*, this automation set reduces *manual triggering*; they are complementary, not substitutes, which is why both survive into the recommendation together.

---

## 7. Which UI invariants this touches, and the exact amendments proposed

**Invariant #2** (*"Left sidebar lists all tabs and stays visible... may collapse to an icon rail, but must never disappear off-canvas above 600px width"*) — **amended, not broken.** New text: *"The left sidebar lists every tab available at the user's current Ring, grouped by intent, plus — at Ring 0 only — a permanent, always-visible, never-abbreviated 'Show more (N surfaces)' row naming what it expands. It may collapse to an icon rail... but must never disappear off-canvas above 600px width, and 'Show more' must never collapse into an icon with no text label."* Justification: the original rule exists to stop a surface vanishing into unlabelled chrome (the historical Wikipedia-dropdown regression); a permanent, named, one-click "Show more" row satisfies that intent while letting default population vary by Ring.

**Invariant #4's task-manager clause** (*"the top bar keeps a persistent task-manager access, `#tm-open`, since `#activity` is hidden when idle"*) — **struck.** A permanently-visible sidebar Activity entry (invariant #2, amended) already gives the constant-access guarantee this clause existed to provide; a redundant top-bar icon pointing at a relocated surface is exactly the second-competing-entry-point pattern that produced Finding #2 (two divergent task managers) in the first place.

**Invariant #13** (calendar directory belongs in Settings→Advanced, not Agenda, per the 2026-07-31 amendment) — **location wording only, ruling unchanged.** Since "Advanced" as a destination is deleted (§6), the amended text reads: *"...the directory lives in Settings → Collect & sources (its Ring-2 'Fine-tune' row), never in the Agenda tab itself."* The reasoning (it's the catalogue that *feeds* the agenda, not agenda configuration) is untouched.

**Invariant #20/#20b–e** (task manager is a window with tabs Active·Queue·Schedule·Coverage·System) — **amended.** The rule today enforces the *dead* `#vitals-pop` markup, while the live, reachable `/tasks` page has a different tab set that never included Coverage at all — the test that's supposed to catch exactly this class of regression (CLAUDE.md rule 4) has been silently watching dead code. New text: *"Activity is a permanent, always-visible sidebar tab (never a secondary browser-tab window or an orphaned in-page popover) with two lenses — Right now (live job/queue/schedule/coverage state) and Ledger (a chronological, undoable record of every automated decision). `test_ui_invariants` must assert against the single live implementation, never a superseded markup fragment."*

**Invariant #22** (Analyze "never a sidebar entry, retired 2026-06-20") — **superseded by the Explore merge, not merely amended.** Since Search and Analyze combine into one first-class Explore surface (Graft 1), the 2026-06-20 retirement's actual target (a standalone Analyze *window*) no longer exists to retire from. New text: *"Explore is the merged query+analysis surface: a query box with the former Analyze subtabs (Overview/Keywords/Trend/Mindmap/Articles/When-Where-Who/Links/Related/Sentiment/Sources/Competitive/Advanced) rendering inline as soon as results return — never a second browser window or dialog."*

**No other numbered invariant requires amendment.** Specifically confirmed compatible as written: #8 (UI shows data, never plumbing — the Ledger is a record of decisions, i.e. data; configuration stays in Settings), #14/#14f (one consent popup per online transition — nothing in §4's GREEN or AMBER set crosses that boundary autonomously), #16 (detailed curves — the mini-chart x-axis fix in §3 *fulfills* this rather than changing it), #18 (ooSubtabs — the Ledger's lenses and Trust's two subtabs reuse it unchanged), #19/#23 (Home content-first, flip-card caveat placement — the exact pattern reused for `card_deltas`/evidence chips), #21 (Insights auto-indexes, no button — the precedent this whole automation set generalizes).

---

## 8. Migration path

**Phase 1 — Disclosure only, zero behavior change, zero invariant amendment yet.** Regenerate the command palette's Pages list from the live sidebar registry (fixes Feed/Observatory omission structurally, not as a one-time patch). Delete `#vitals-pop` and `#corpus-win` (both already self-documented as dead in five+ code comments). Fix Help's TOC `id` bug and the net-coach overlay's protected-elements guard array (extend it past the top bar to cover every facet-subtab strip — the exact bug class the team already paid to fix once, recurring one DOM layer down). Fix the mini trend-chart's index-vs-date x-axis. Ship the §3 "cheapest wins" table in full: Coverage restoration, bury-signal table, Indices/Markets refresh buttons, `card_deltas` badge, leads-view chips+sort.

**Phase 2 — The Ring dial and sidebar regroup.** Ship `Settings → General → "Interface depth: Essentials · Standard · Full"` — existing installs default to **Full** (nothing pinned today is un-pinned on upgrade); only a genuinely new first-run defaults to Essentials, and only if the onboarding wizard's optional depth question is answered (skipping it also defaults to Essentials, per the design's own rule — flagged as an open question in §10). Ship the grouped sidebar layout (NOW/EXPLORE/DATA/TRUST/SYSTEM) with Trust promoted and pinned at every Ring. Land the Activity sidebar entry (Ledger, Graft 2) as a read-only Right-now/Ledger view wired to data the scheduler ride-alongs already return — this is the safest possible first behavioral-visibility change because nothing it displays is new.

**Phase 3 — Explore merge (Graft 1).** Combine Search and Analyze into one sidebar surface. This is real UX design work (the two currently have different result models per the source audit) and should not be rushed into Phase 2's sidebar reshuffle.

**Phase 4 — Settings reorganization.** Collapse nine tabs into five goal-named sections; delete "Advanced" as a destination; move Cards to the family-first/tunable-deferred layout. This is explicitly the highest-regression-risk phase (the settings-inventory audit already found one subtle defect class here — the qualification-scope checkboxes — and the reorg touches ~1,700 controls and their 12-locale translation keys) and should ship with the existing change→save→reload→re-read persistence-test discipline re-run against every relocated control before merge.

**Phase 5 — Automation defaults.** Turn on the §4 GREEN list one category at a time, each with its exact disclosure string live *before* its behavior is: qualification-ride-along visibility, coverage-biased ordering, background-AI default-on (gated by the hardware preflight from J1), leads-view sort control. AMBER items (Patterns lens, auto-scheduled backups, Watch suggestions) ship default-OFF and require a second, explicit maintainer sign-off before flipping to default-ON, per §9.

Each phase is independently shippable and leaves the app in a coherent, fully-tested state; none blocks or is blocked by a later phase except where noted (Phase 3 should follow Phase 2's sidebar work, Phase 5's AMBER items should follow field-validation data Phase 1–4 don't produce on their own).

---

## 9. What I would NOT do, and why

**The 7 RED automations (§4) stay hard-refused, not deferred:** auto-promoting a discovered source, auto-collapsing a coordinated-actor network, auto-pruning keywords, acting on a qualification score rather than displaying it, per-ingest OpenTimestamps firing without its transition consent, removing any of the 37 per-Lead-type category toggles, and reactivating scheduler autostart-at-boot. Each one crosses from *measuring* into a standing content or network judgment with no per-instance human click — exactly the line "the app gathers and measures; the user judges" exists to hold. The scheduler-autostart item gets a positive fix instead of a refusal: **delete the dead checkbox** (nothing has read `settings.autostart` since the airplane-mode-by-default ruling; it currently persists a promise the app cannot keep) and replace it with one static sentence in Settings: *"The app always starts offline. You choose to go online each time you open it — that choice is never remembered."*

**Works While You Sleep's full architecture was not adopted as the spine, despite winning the New User lens (66/100).** Two of its structural choices were rejected on their merits, not merely out-scored:
- Its **"Needs You" triage queue** trades an invisible qualification/keyword backlog (today: 42,600–66,700 unqualified sources sitting silently) for a *counted, badged, mandatory* one — its own cost analysis admits this is "a genuine new chore that the status quo's invisibility accidentally spared" the user. That is a real, not hypothetical, new-user cost the New User lens itself did not fully price in, and the Power User lens (44/100) flagged it as the design's fatal flaw: an operator returning after a week could face "dozens or hundreds of items" with no opt-out beyond risky batch actions.
- Its **"accept the N uncontested ones" bulk keyword-merge action** was independently flagged by two judges (Ethical, 60/100 score; Feasibility) as a composite judgment wearing a single click as camouflage — something has to compute "uncontested," and that computation gets no method+caveat+n treatment anywhere in the design. Per the decision test's item 5 (§5), an automation that needs an unshown pre-filter to decide which items even reach the human as a batch has smuggled judgment back in under measurement's name. This report takes the same underlying idea (batched review) and demotes it to **manual, per-item Advanced-fold review, unchanged from today**, until a specific merge-confidence metric can itself be method+caveat+n disclosed.
- Its full sidebar-restructuring away from any Ring/tier concept (flat, always-everything-visible) scored best for a first-time journalist but worst on Feasibility (44/100): it stacks automation-default changes, a new Ledger enforcement test suite, the Explore merge, and a from-scratch statistics UI into one release, which the Feasibility judge estimated at "two or three release cycles of work presented as one proposal."

**The Patterns lens (6 manipulation-pattern detectors) ships default-OFF, not default-ON,** contrary to a plausible reading of "surface everything already built" — because these are unvalidated at real corpus scale (per their own status as never-yet-triggered endpoints) and a false-positive rate on a live corpus would be a genuine new-user trust cost, not a convenience win. Field-validate before flipping the default, exactly per the automation-candidates analysis's own AMBER ruling.

**No proposal here introduces a new autonomous network dial, a composite trust/quality score, or a silent schedule/default change a returning user wouldn't see disclosed.** This was checked explicitly against §5's test 3 and 6 for every item in §4 and §6 — nothing survived synthesis that required either.

---

## 10. Open questions only the maintainer can rule on

1. **Two parallel backup-restore APIs** (`v2/restore/preview→commit→discard`, `legacy/restore`, `reindex-backlog` vs. the live `import-queue/*` flow the UI actually drives) — both sets of docstrings claim to back "the unified Import dialog." Static+live audit cannot disambiguate whether this is dead code (safe to delete) or an unmigrated newer implementation (worth wiring, and possibly the fix for the 2026-07-29-ruled invisible-reindex-backlog concern). **Needs a one-line maintainer triage before either deletion or Phase-4/5 wiring.**
2. **Onboarding default for a skipped Ring question.** The Rings design defaults a skipped first-run depth-choice to Essentials (Ring 0), which the New User judge flagged as hiding Search, Insights, Observatory, and 6 other investigative surfaces from exactly the population most likely to skip an optional step. Should the skip-default instead be **Standard (Ring 1)**, reserving Essentials only for an explicit choice? This is a genuine, unresolved tension between the Ethical lens's "quieter first screen" argument and the New User lens's "real investigative value in ten minutes" argument, and the report does not adjudicate it — it is a product call, not a technical one.
3. **Should the Trust group's two permanent Ring-0 sidebar slots (Custody + Integrity) be worth their footprint for a purely casual reader who will never use them?** The Ethical case for pinning them everywhere is made in §6; a maintainer optimizing for the absolute minimum Ring-0 footprint could reasonably want them one tier deeper instead, at the cost of re-opening the discoverability gap this report ranks #5 in value forgone.
4. **Does the "Automatic" AI-backend selector's hardware preflight actually run proactively today**, or only on-demand? The J1 automation candidate's effort estimate (Small) depends on this; if it only runs on-demand, the item moves to Medium and needs its own trigger-timing design.
5. **Field-validation bar for the Patterns lens.** What corpus size / false-positive rate, measured how, justifies flipping the six manipulation-pattern detectors from default-off to default-on? No inventory in this evidence base establishes one; it should be set before Phase 5 reaches this item, not decided ad hoc when the toggle is being flipped.
6. **Qualification-scope checkbox defect status.** The originally-reported bug (the two "Also scrape sources not yet judged" / "Only scrape shipped sources" checkboxes silently failing to save) did **not** reproduce under single-click, uncheck, or rapid-double-click race conditions on the audited instance — reported as DISPROVED-HERE, not confirmed-fixed. Before Phase 4 touches this exact fold, the maintainer should confirm whether this was already fixed, is state-dependent in a way this audit didn't trigger, or was specific to a different build.