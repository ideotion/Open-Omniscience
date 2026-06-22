# AUTONOMOUS SESSION BRIEF — 2026-06-22

**This document is the opening prompt for a fully autonomous build session.** It was
curated from a live field-test of the 0.0.9 build on a real **7,800-article corpus**,
combining maintainer UX feedback (23 items) with a thorough analysis of seven diagnostic
exports (benchmark, perf report, debug bundle, network preflight, date diagnostics,
keyword engine report, keyword log). Every finding below is evidence-cited.

---

## 0. How to work (read first)

- **Read `CLAUDE.md` in full before anything.** It is the single ledger of every maintainer
  ruling and all non-negotiables. This brief does **not** restate them — it assumes them.
  Record every new ruling you derive here back into `CLAUDE.md` in the same turn.
- **This session is fully autonomous. Do not ask the maintainer anything.** Make every
  decision yourself; pick the most honest, conservative default and proceed; record the
  choice. (Per the 2026-06-21 autonomy hardening.)
- **Working mode:** one PR per slice, **small + additive**, **draft onto `0.09`**, branches
  stacked, CI subscribed. `git fetch origin 0.09` immediately before cutting each branch
  (0.09 goes stale within minutes). The maintainer merges everything; nothing self-merges.
- **The non-negotiables still bind**, even under "fix it fast" pressure: local-first /
  loopback-only, airplane-mode socket guard, robots fail-closed, **no composite scores**
  (`assert_no_score_fields`), **caveats visible by default**, informed-consent popup on
  every offline→online transition, honesty-by-construction. A redesign may **never** drop a
  disclosure or a working tool (the "Desk lesson": make unreachable, gated by an absorption
  test — never silently delete).
- **Frontend is browser-unverifiable in CI** (fork-3 rule): ship conservative + flagged
  "browser-unverified, needs click-through", `node --check` every `<script>`, extend
  `tests/test_repo_invariants.py` / `test_ui_invariants`, keep i18n at 100%
  (`scripts/i18n_report.py --min 100`). New chrome strings may be English-fallback via `t()`
  and keyed later, but the gate must stay green.
- **Sequence by the priority tiers below: P0 (reliability/data-loss) first, always.** The
  app is accumulating a real corpus the maintainer cares about; correctness outranks features.

### Live environment the logs came from (so numbers are interpretable)
8-core / 20 GB RAM, Qubes (Fedora 41), Python 3.13.5, over Tor. Corpus at capture:
**7,828 articles, 3,178 sources, 229,869 keywords, 617,043 mentions, 100,331 price points**,
`corpus.db` **358 MB, unlocked-encrypted (SQLCipher)**. Scheduler: `continuous`, `mode: rss`,
**`collect_parallelism: 50`**, `collect_target_kbps: 500`. Columnar engine **unavailable
(in-memory)**; keyword counters **basis "estimated" (unreconciled)**; LLM **not installed**.

---

## P0 — CRITICAL RELIABILITY & PERFORMANCE (do these first)

### P0-1 — `database is locked` data-loss during ingest (single-writer gate is NOT covering all writes)
**Evidence (debug bundle, app_errors, dated 2026-06-17):** 149 lock-class failures, **all**
`sqlcipher3.dbapi2.OperationalError: database is locked`:
- **62× `src.ingest.pipeline: keyword indexing on ingest failed`**
- **87× `src.ingest.pipeline: link indexing on ingest failed`**
- several `src.analytics.store: when/where/who persistence failed for <id>` and
  `indexing article <id> failed`
- scheduler `recent_runs`: **a whole RSS pass rolled back** — *"This Session's transaction has
  been rolled back due to a previous exception during flush. Original exception was: database
  is locked."*

**Impact:** articles are stored but their **keywords / links / dates fail to index** → silent
degradation of every downstream surface (Home, Insights, When/Where/Who, search relevance).
This is the same data-loss class the ledger claims the single-writer gate (`src/database/writer.py`,
keystone #1) fixed; the **end-to-end test proved it in isolation but the gate does not cover the
live paths.** Runs with **50 parallel collect workers** against one encrypted writer.

**Diagnosis to confirm + fix direction (you do the real diagnosis):**
- The Article write takes the gate, but the **best-effort sub-steps** (`index_article`'s keyword
  indexing, link indexing, when/where/who persistence) and/or **post-pass housekeeping writers**
  (auto-reindex top-up, briefing refresh, auto-on-ingest AI, stats, columnar maintenance) appear
  to write **outside** the gate or on connections **without `busy_timeout`**, so they collide
  under parallel load.
- **Make every write path go through the single-writer gate** AND set **`busy_timeout`** (≥30 s)
  on **every** connection in the pool (so even a gate-handoff race waits instead of failing).
  Wrap the best-effort indexing sub-writes in `run_write_with_retry` (already exists for
  `import_points`) so a transient lock retries instead of dropping data.
- Audit for **any** `SessionLocal`/engine/raw-SQL/FTS-trigger/columnar write that bypasses the
  gate. The torture suite proves the merge engine; add an **ingest-under-parallel-load** test that
  reproduces the 50-worker contention and asserts **zero** dropped keyword/link/date writes.
- Re-run the data-loss proof (`tests/test_write_gate_dataloss.py`) extended to cover ingest
  sub-writes + housekeeping concurrency, not just `import_points`.

**Acceptance:** under simulated parallel collection + concurrent housekeeping, **no
`database is locked` reaches a logged failure**; every stored article has its derived rows; a
re-index backfills the articles that lost indexing in past sessions.

### P0-2 — Restore preview/commit fails on a UNIQUE collision + is pathologically slow (feedback #11)
**Evidence:** maintainer hit *"Preview failed: could not read this backup (it may be from an
incompatible version): UNIQUE constraint failed: `article_mentioned_dates.article_id,
article_mentioned_dates.mentioned_on, article_mentioned_dates.precision`"* on their **own latest
backup**. Perf report (current boot): `/api/backup/v2/restore/preview` **4 requests, 946 s total
(236 s each), p95 > 10 s**; `/restore/commit` **1 request, 422 s**.

**Two bugs:**
1. **The collision (root cause):** when an imported article **deduplicates to an existing local
   article** (same hash → remapped to the local `article_id`), the merge then inserts that
   article's **derived child rows** (`article_mentioned_dates`, and **audit the siblings**
   `article_mentioned_places`, `article_entities`, keyword mentions, anything with a per-article
   natural key) under the already-occupied local id → UNIQUE violation. Fix = **robust
   dedup / skip-if-exists on every derived child table's natural key**, and/or **don't
   verbatim-copy core-engine-derived rows at all** (they're recomputed on import by the P0-4
   reindex anyway — see ledger). Add a regression test: merge with a deduped-article-carrying-
   derived-children + duplicate-derived-rows-in-source.
2. **The misleading error:** a constraint collision is reported as *"may be from an incompatible
   version."* Fix the **error classification** so a merge constraint failure says what it is.

**Slowness:** 236 s/preview is unacceptable and blocks the request thread (contending for the
writer → feeds P0-1). Make restore a **task-manager job** (see P0-3/feedback #12) and profile the
merge on the live corpus.

**Acceptance:** the maintainer's backup imports cleanly; an audit proves no derived-child table can
collide on restore; restore runs as a visible, non-blocking job.

### P0-3 — Home tab is empty despite ~7,800 articles (feedback #21)
**Evidence:** Home shows no Leads; previously **500 articles produced cards**. But the data exists:
`/api/briefing` is **160 ms** and the benchmark shows `top_terms` (50 rows), `supergroups` (84),
`associations` (20), `trending_windows` (3) **all return**. So this is **dysfunction, not "no leads."**

**Ranked hypotheses (confirm empty-state-vs-blank first, then fix):**
1. **Slow-endpoint timeout/abort blanking the render (leading suspect).** `loadHome` fires heavy
   parallel calls; the Home poll `trending-windows` is **12–40 s** (P0-4). If a `Promise.all`
   rejects, a fetch aborts/times out, or the trends-glance render throws, the **whole Home panel
   blanks** even though `/api/briefing` returned fast. Make Home **resilient**: render the briefing
   cards independently of the slow glance sections; each section degrades to its own honest
   empty/loading state; never let one slow/failed call blank the page. Confirm the **fail-safe
   empty state actually renders** ("Home must never go blank-and-silent").
2. **Stale/empty briefing from a rolled-back pass.** A pass that rolled back on `database is locked`
   (P0-1) before `refresh_briefing` ran leaves a stale/empty briefing. Fixing P0-1 + ensuring
   `refresh_briefing` runs even after a partial pass addresses this.
3. **Degraded producers from lost indexing (P0-1)** — fewer keywords/links → thinner signal.
4. **Counter staleness (P0-4)** — producers reading "estimated" counters.

**Acceptance:** on the live large corpus, Home renders Leads (or a genuine, explained empty state —
never a blank div); a regression test asserts the briefing yields cards on a large corpus and that a
slow/failed glance section cannot blank the briefing.

### P0-4 — Home/Insights read-path performance is unusable at 7.8k articles
**Evidence (benchmark, warm medians unless noted):**
| endpoint | cold | warm-median | max | note |
|---|---|---|---|---|
| `trending_windows` (the Home poll) | 12.4 s | **18.2 s** | **22.1 s** | selftest run hit **40.7 s** |
| `trending` | 8.7 s | 11.2 s | 14.3 s | |
| `supergroups` | 14.8 s | 12.8 s | 14.9 s | slowest case |
| `top_terms_grouped` (Home) | 5.1 s | 4.6 s | 5.2 s | counter path, still 5 s |
| `map_data` | 4.8 s | 3.9 s | 5.7 s | |
| `layered_graph_keyword` | 4.1 s | 2.5 s | | |
| `keyword_export_streamed` | 54 s | 24 s | | 31.5 MB |

`scaling_context`: **counters `basis: "estimated"` (unreconciled, 177,398)**; **columnar engine
`available: false` / `mode: "unavailable"` (in-memory)**.

**Fix directions (measure on the live DB first — don't add drift speculatively):**
- **`trending-windows` / `trending` are the #1 hotspot** and are `observed_on`-windowed, so the
  corpus-wide counters can't serve them. The covering index `ix_mention_date_keyword` added last
  session is **demonstrably insufficient** here. Verify the index is actually built + used
  (`EXPLAIN QUERY PLAN`) on the live encrypted DB; if it's used and still 12–40 s, the per-day
  **rollup table** is now justified (the ledger deferred it pending this evidence — the evidence
  is here). A maintained `(observed_on, keyword_id) → count` daily rollup makes the windows a
  bounded scan.
- **Reconcile the counters.** They're "estimated" — `top_terms`/`supergroups` read stale values.
  Ensure background reconciliation actually runs and the freshness envelope reaches the UI.
- **Reduce Home polling load.** Perf report: `/api/scheduler/activity` **3,997 reqs**, `/api/system/vitals`
  **3,995**, `scheduler/status` 1,186, `llm/health` 460, `health` 449, `jobs` 396, `system/network` 329
  since boot. Confirm the adaptive backoff is engaged and consider consolidating Home's heavy polls;
  make `trending-windows` lazy/deferred so it never blocks first paint.
- **Persisted columnar engine** is still blocked on the per-OS httpfs crypto-extension packaging
  decision (in-memory = no cross-session gain). Make the packaging decision and bundle the per-OS
  extension so the derived store persists encrypted — this is the structural decade-scale lever.
- Profile `supergroups` (15 s) and `map_data` (5 s) — both heavier than they should be.

**Acceptance:** Home's poll endpoints return in **< 1 s warm** on a 7.8k-article corpus; counters
report `exact`; no Home interaction blocks > 2 s.

### P0-5 — Reindex hammering + diagnostic bundle captured stale errors
- **`/api/insights/reindex` was called 1,326 times / 369 s** in one boot — the auto-index top-up is
  hammering. Make it a single bounded background pass, not a per-tick storm.
- The **debug bundle merged a stale `app_errors` window** (all errors dated 2026-06-17 though the
  bundle is 2026-06-22) — the live errors weren't captured. Fix the bundle to capture the **current**
  error log so diagnostics are trustworthy.

---

## P1 — IMPORT / EXPORT (BACKUPS) REDESIGN (feedback #7–#12, one cohesive workstream)

Treat all of backups as **one redesign**. Organizing rule: **export ↔ import symmetry; one elegant,
homogeneous, space-efficient UI; the user never sees the two-mechanism split.**

- **#7 — Redesign "What to include" (it's ugly) + make it comprehensive.** The selectable list must
  span **everything downloaded/derived**: articles, **newsletters**, **internet/scraped articles**,
  **law data**, **indexes**, **agenda/events**, **commodities** — plus the big blobs (Wikipedia
  dumps, Offline maps, LLM models). Principle: *anything downloaded should be backup-selectable.*
- **Architecture (hide it from the user):** DB-row categories (articles/newsletters/law/indices/
  agenda/commodities) → per-category include/exclude on the **encrypted `oo-backup-2` artifact**
  (the newsletter-exclude disposable-snapshot drop pattern, extended per category with careful
  dependent-row handling, additive-restore-safe). Big-file categories (wiki/maps/models) → the
  **folder copy**. Route each category to the right mechanism under one UI. Wire the "coming soon"
  wiki/maps rows for real (they depend on the ruled-but-pending additive-restore **file-member
  placement** — build it, don't fake it).
- **#9 — Redesign "What to restore" (visually wrong) + unify.** Kill the *"use the separate X above /
  restore from the Y panel above"* cross-references — those leak the implementation. One restore UI
  mirroring the export UI. **Don't over-complicate.**
- **#8 — Browse buttons, never manual path typing.** Server-side paths (folder-backup destination,
  newsletter import source) need a **server-side directory browser** (loopback-gated, read-only,
  traversal-safe backend dir-listing + a navigable picker) — the browser's native dialog can't
  return a host path. Client uploads (.eml, restore-from-file, CSV) use the **native picker**. Keep
  the type-a-path field as a fallback; Browse is primary.
- **#10 — Encryption as an in-flow option + import auto-detects.** Export offers "encrypt this
  backup?" as a toggle in the same flow. Import **auto-detects** the `OOENC1` header
  (`read_artifact`'s `was_encrypted`) and **only then** prompts for the passphrase (plaintext → no
  prompt). Keep the at-rest warning (plaintext on disk) + no-recovery passphrase note.
- **#12 — Drop the forced preview; report results after; progress bars both directions.** Replace
  mandatory preview→commit with **direct import that shows what was actually imported** (safe: restore
  is additive-only). Keep preview as an **optional** power-user affordance. Add **honest progress bars
  (#20: real bytes/counts, no fake ETA)** to import AND export — which requires the encrypted backup/
  restore to become a **task-manager job / streamed op** (it blocks synchronously today and contends
  for the writer). Unify the progress UX across all import/export paths.
- **#11 — fix the restore collision** (covered in P0-2; it's the same workstream).

**Acceptance:** one coherent Backups section, no cross-panel pointers, Browse everywhere, encryption
optional + auto-detected, direct-import-with-summary, real progress bars, the maintainer's backup
round-trips, every category selectable on both sides.

---

## P1 — KEYWORD ENGINE & EXTRACTION QUALITY (log-derived; the maintainer's optimization loop)

**Evidence (keyword engine report + date diagnostics, live corpus):**
- **52,548 zero-mention orphan keywords** (23% of 229,869) — prunable. Run the existing
  `prune_orphan_keywords` (curation-safe) + the one-click "re-index then prune" cleanup.
- **Tag coverage 0.0%** (0 of top-500 tagged) — the **baseline-tag backfill was never run** on this
  corpus. Run it (and the auto-backfill when the Keywords explorer opens empty).
- **Translation coverage 13.6%** (68/500 in a ring; 550 rings). Grow rings via the corpus-driven
  loop (`generate_wikidata_rings.py --from-log` on the gap digest, vet ~6% mis-resolution, commit,
  re-measure). Target the gap languages.
- **`no_stoplist` languages leaking junk** — and critically these include **UI languages Hindi (`hi`)
  and Bengali (`bn`)**, plus tr, ro, th, fi, ur, uk, cs, ca, sk, et, vi, fa, bs, az, sw. Grow
  evidence-based stoplists from the exported per-language keyword logs (`scripts/analyze_keyword_log.py`
  reads the .zip). Don't disable UI-language sources — give them stoplists.
- **`zh` unsegmented (4,990 keywords broken); `ja` same class** — the standing **CJK segmentation**
  gap. Decide and ship a segmentation path (e.g. a bundled local segmenter) so zh/ja extraction works.
- **Date extraction:** 52.5% coverage; **no month vocabulary** for `vi/et/th/ur/uk/zh/?`; CJK 年月日
  only 26 hits; **280 articles have date-like text but zero extraction**; 2,425 bare-years. Add native
  month vocab for the missing languages + CJK date handling.
- Already fixed (confirm it stays): **markup leak = 0** (markup-strip works); elision backlog 222 +
  mostly-digits 678 clear on re-index.

**Acceptance:** orphans pruned, tag coverage > 0, ring coverage rising, UI-language stoplists in place
(hi/bn no longer `no_stoplist`), a zh/ja segmentation decision shipped, date coverage up for the gap
languages. Re-export the engine report and diff to prove each lever landed.

---

## P1 — UI / LAYOUT & NAVIGATION

Cross-cutting directive the maintainer repeated for Backups, Agenda, and Settings: **space-efficient,
data-dense, clearly-sectioned, fill-the-viewport layouts.**

- **#13 + #14 — Markets twin-board responsive graph grid (binding for BOTH Commodities and Indices).**
  Every subtab (including "All") renders its graphs in a **responsive multi-column grid that adapts to
  screen width** (auto-fit/auto-fill); each category subtab shows **per-commodity / per-index graphs**
  in that same grid. Reuse `dashChartSvg`; keep invariant #16 (full-resolution, n<10→bars). Keep the
  boards identical (twin-board ruling).
- **#16 — Agenda: every view fills the screen with data + is visually distinct.** Month / trimester /
  year must each be **designed for their scale** (not one grid rescaled) and **fill the viewport**;
  the **week view's vertical-days layout is good — keep it** but expand it to cover the whole visible
  area. No cramped grids floating in empty space. Keep agenda invariants (#13) intact.
- **#17 — Settings: fuse Appearance + GUI into one clearly-sectioned section** (themes + typeface +
  the 8 alternative-interface skins), space-optimized. **Remove the "Tools shown in the sidebar"
  checklist entirely** — it's outdated (lists moved/dissolved tabs: Search, Collect, Sources, Wikipedia,
  Evidence & custody, Source integrity) and useless. Remove the sidebar-visibility feature + its
  persistence; ensure nothing becomes unreachable; reconcile the **actual current sidebar set** while
  you're in there.
- **#22 — Left sidebar: remove the section headers** ("Investigate" / "Collect" / etc.); present **all
  tabs as one flat list.** Invariant #2 stays (lists all tabs, visible, collapsible to a rail) — just
  de-grouped. Land this with #17 and #20 so the sidebar ends up one clean, current, flat list.

---

## P1 — DATA SURFACES & TABS

- **#6 — Settings → AI: one-click "Install AI support".** A single button automates **download +
  install of Ollama → activate → first model pull**, hardware-driven. Detect + **show the user the
  hardware** and explain the **hardware → output-quality** relationship, then branch:

  | hardware | action | alert |
  |---|---|---|
  | GPU ~5 GB VRAM | pull `mistral:7b` (~4.4 GB) | other models in the GUI |
  | GPU ~8 GB VRAM | pull `mistral-nemo:12b` (~7 GB) | other models in the GUI |
  | GPU ~16 GB VRAM | pull `mistral-small:22b` (~13 GB) | other models in the GUI |
  | CPU-only, 8–16 GB RAM | pull `mistral:7b` | AI will be **slow** |
  | CPU-only, <8 GB RAM | **no auto-pull** | likely insufficient; offer "proceed anyway" + let user choose |

  Complementary scenarios to add: GPU <5 GB → a 3B/4B model not nothing; GPU 24 GB+ → offer bigger;
  Apple-Silicon/unified-memory branch; VRAM headroom margin; already-installed/already-present skip;
  free-disk preflight. **Constraints (from your own rulings):** the binary auto-install needs **real
  per-OS Ollama installer URLs + checksums verified on a networked machine** (forbidden to fabricate);
  download → verify checksum/signature → run via the guarded factory with a **visible OS elevation step
  (never silent)**; **verify the exact model tags + sizes** (`mistral-nemo:12b`, `mistral-small:22b`)
  against ollama.com; install + pull **egress clearnet via the Ollama process (not Tor)** → one consent
  + clearnet disclosure; **progress bar** with **real byte progress** (Ollama `/api/pull`), honestly
  indeterminate during elevation.
- **#18 — World Law tab: full revamp + automatic scraping + cover all UI-language countries.** The
  tab is broadly under-specified — apply the established design language (content-first, data-dense,
  fill-the-screen, analysis-window/corpus integration, version-tracking like wiki, no verdicts). Law
  is currently **near-empty in the field DB** (`law_track`: documents 0, baselines 0). Wire law sources
  into the **scheduler pass** (auto-scrape, airplane-gated, via EthicalFetcher). Build a **languages →
  countries map** + a curated sourced legal-source catalog **per country for every UI language**
  (Arabic→its countries, Spanish→Spain+LatAm, Portuguese→PT+BR, etc.), seeded disabled, honest
  provenance — reinforces de-US-centring.
- **#19 — Two-letter codes → full localized names, everywhere (ruling, supersedes "codes stay").**
  Named instance **Insights → Map** still shows 2-letter codes. App-wide sweep using the existing
  **`ooRegionName`** (countries) / **`ooLangName`** (languages) CLDR helpers; full name is the visible
  label, code only as secondary hover; re-render on `oo:langchange`. Internal codes (URL anchors,
  provenance, API params) stay codes.
- **#20 — Move "Evidence & custody" into Settings (→ Safety subtab) + make it foolproof.** Completes
  the Trust-group dissolution (Source integrity is already there). Simplify the expert crypto
  (ML-DSA/FIPS-204, OpenTimestamps, Merkle, "actor") into plain-language controls; push detail into
  `#oo-tip` hovers. Don't lose functionality (export/verify, auto-log-on-ingest ON by default,
  OTS/Bitcoin OFF by default). Keep verify/export reachable from content.
- **#23 — Settings → Sources: multi-select dropdown filters + keep title search.** Convert Language /
  Country / Type / Tags to **dropdown filters** with **additive multi-select** (French *and* English,
  multiple tags). Keep the free-text **title** search. Localize option labels to full names (#19).
  Make combination semantics **explicit** (within-filter OR; across-filter AND; an explicit AND/OR
  toggle for tags). Feed dropdowns from real distinct catalog values.
- **#5 — Task manager: show the actual queued languages and tags.** The Queue preview describes
  *"stratified by language and tag"* — also **display the actual strata** (the languages + tags in this
  pass's rotation). `stratified_interleave` already knows them — surface them, no fabrication. Keep the
  randomisation caveat.
- **#15 — Remove "Updates automatically in the background" app-wide.** It's implicit. Grep the string
  (markets boards + anywhere), remove the elements/keys, keep i18n 100%.

---

## P1 — ONBOARDING & FIRST-RUN

- **#1 — Add a "Back" button to the install/first-launch screens** (language → legal/consent →
  passphrase). Back must preserve entered state (chosen language persists) and must not skip the
  encryption-by-default ordering — it only re-navigates.
- **#2 — Collapse "go online" to one screen / one step.** Today: full initial screen + a second
  screen + the top-right coachmark balloon (`#net-coach`). Merge the redundant layers **into the single
  informed-consent screen** (invariant #14 stays — the one remaining step *is* the consent: names the
  action, shows local interface IPs, honest public-IP wording). Consent isn't removed; the duplication
  around it is.
- **#3 — New-user UI tutorial (~8-step visual walkthrough).** Orients the user to UI elements +
  navigation (sidebar, top bar, omnibar, airplane, language switcher, task manager, Leads, analysis
  window). **Dismissible forever** (user-visible Settings toggle like `oo_guide_v1`, never a hidden
  flag) and **replayable from Settings.** Distinct from the first-launch *setup* wizard — this *orients*.
  Ride existing conventions: ×12 i18n, `#oo-tip` styling, a11y, anchor steps via `getBoundingClientRect`.

---

## P2 — DATA / SOURCE HOUSEKEEPING (log-derived)

- **#4 — World map: completeness, detail, neutral borders.** Some countries don't render (NE 110m base
  drops ~75 microstates to centroid points). **Recover the maintainer's prior list of missing countries
  from session history/issues AND guarantee complete coverage** (finer base / OSM boundaries) so the
  list is moot. **Much more detail by default** (NE 50m, or 10m / OSM on-demand — balance against
  bundle size). **Politically-neutral disputed borders (ruling):** where border data conflicts, use a
  **neutral visual strategy** (dashed/hatched/fuzzy zone, or show all claims) — never a single hard line
  that implies a verdict. Drive it from Natural Earth's **disputed-areas / disputed-boundary** layers.
- **Dead calendar feeds wasting preflight** (network preflight): **all `google-hol-*` editions are
  robots-disallowed**, `webcal.guru` disallowed, `raw.githubusercontent.com` undetermined → all dead.
  Drop the guaranteed-fail feeds from defaults. Working set: `worldpublicholiday.com` (wph-*),
  `pirate.monkeyness.com` moons (2,623 events), `cantonbecker.com` astro (191), `space.floern.com`
  launches (78), `ose-calendar` (159).
- **Dead FRED commodity series** (field_test/imports): **gold `PGOLDUSDM`, silver `PSILVUSDM`,
  sawnwood `PSAWMUSDM` → HTTP 404** (`dead-series`). Source + verify replacement FRED ids on a networked
  machine; never fabricate.

---

## Reference: feedback-item → work-item map

| Feedback | Where it lands |
|---|---|
| #1 back button | P1 Onboarding |
| #2 one-step go-online | P1 Onboarding |
| #3 UI tutorial | P1 Onboarding |
| #4 world map | P2 Housekeeping |
| #5 task-manager strata | P1 Data surfaces |
| #6 AI install | P1 Data surfaces |
| #7/#8/#9/#10/#11/#12 backups | P1 Import/Export (+ P0-2 for #11) |
| #13/#14 markets grids | P1 UI/Layout |
| #15 remove auto-update note | P1 Data surfaces |
| #16 agenda views | P1 UI/Layout |
| #17 Settings Appearance+GUI / remove sidebar list | P1 UI/Layout |
| #18 law revamp | P1 Data surfaces |
| #19 two-letter→full names | P1 Data surfaces |
| #20 custody → Settings | P1 Data surfaces |
| #21 empty Home | **P0-3** |
| #22 flatten sidebar | P1 UI/Layout |
| #23 sources filters | P1 Data surfaces |

## Suggested sequencing
1. **P0-1 → P0-2 → P0-3/P0-4** (reliability + the empty-Home + the read-path perf — these are coupled
   and they're what makes the app currently feel broken on a real corpus).
2. **P1 Keyword engine** quick wins (prune orphans, run tag backfill, stoplists) — cheap, high-value,
   reduce the data the slow aggregations chew.
3. **P1 Import/Export redesign** (the maintainer's largest UX pain).
4. **P1 UI/Layout** (sidebar flatten + Settings fuse + markets/agenda grids — ship together where they
   touch the same files).
5. **P1 Data surfaces** (AI install, law, sources filters, two-letter names, custody move, task strata,
   remove note).
6. **P1 Onboarding**, then **P2 Housekeeping**.

**Every slice: draft PR onto a freshly-fetched `0.09`, CI subscribed, tests + invariants extended,
i18n 100%, `node --check`, record any new ruling into `CLAUDE.md`.**
