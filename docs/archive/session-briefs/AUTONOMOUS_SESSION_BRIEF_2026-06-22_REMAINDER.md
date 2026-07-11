# AUTONOMOUS SESSION BRIEF — 2026-06-22 FIELD TEST, REMAINDER

**This document is the opening prompt for a fully autonomous build session.** It is the
*continuation* of `docs/archive/session-briefs/AUTONOMOUS_SESSION_BRIEF_2026-06-22.md`. The P0 reliability/
performance batch and several P1 items from that brief have already SHIPPED and MERGED into
`0.09` (PRs #439 + #441). This brief covers **everything that remains**, with the merged
work explicitly recorded in §0.5 so it is never redone. Every item is evidence-cited and
carries acceptance criteria.

The original field test ran on a real **7,828-article corpus** (3,178 sources, 229,869
keywords, 617,043 mentions, `corpus.db` 358 MB SQLCipher), 8-core / 20 GB Qubes (Fedora 41),
Python 3.13, over Tor. Numbers below are from that capture's seven diagnostic exports.

---

## 0. How to work (read first)

- **Read `CLAUDE.md` in full before anything.** It is the single ledger of every maintainer
  ruling and all non-negotiables; this brief assumes them and does not restate them. Record
  every new ruling you derive back into `CLAUDE.md` in the same turn (under invariants if
  shipped, the queue if pending; extend `tests/test_repo_invariants.py` for any new invariant).
- **This session is fully autonomous. Do not ask the maintainer anything.** Make every
  decision yourself; pick the most honest, conservative default and proceed; record the choice.
- **Working mode:** one PR per slice (or a coherent small batch), **draft onto `0.09`**, CI
  subscribed. The harness restricts pushes to ONE branch, so slices accumulate as commits on
  it and the PR may carry a coherent batch — the maintainer merges fast and takes multi-commit
  PRs. **`git fetch origin 0.09` then `git checkout -B <branch> origin/0.09` immediately before
  starting, and again after each merge** (0.09 goes stale within minutes; after a `git push`
  that prints `[new branch]`, the previous PR was merged → open a NEW draft PR onto `0.09`).
- **The non-negotiables still bind**, even under "fix it fast" pressure: local-first /
  loopback-only, the airplane-mode socket guard, robots fail-closed, **no composite scores**
  (`assert_no_score_fields`), **caveats visible by default**, the one informed-consent popup on
  every offline→online transition, honesty-by-construction. A redesign may **never** drop a
  disclosure or a working tool (the "Desk lesson": make unreachable + gate with an absorption
  test — never silently delete).
- **Frontend is browser-unverifiable in CI (fork-3):** ship conservative + flagged
  "browser-unverified, needs click-through", `node --check` every `<script>`/`app.js`, extend
  `tests/test_repo_invariants.py` / `test_ui_invariants`, keep i18n at 100%
  (`scripts/i18n_report.py --min 100`). New chrome strings may be English-fallback via `t()` and
  keyed later; the gate must stay green.
- **Verification environment note (from last session):** the package needs Python **3.13**
  (`requires-python>=3.13`); the container's default `python3` may be 3.11 — build the venv with
  `/usr/bin/python3.13`. Install `pip install -e ".[analysis]" pytest ruff "mypy==2.1.0"` to run
  the suite. CI runs the full suite on Linux (BLOCKING) + Core-only-install (BLOCKING) + win/mac
  **observation** lanes (non-blocking, but FIX real failures they catch — a flaky test reddens the
  blocking lane too).
- **LESSONS from last session (do not repeat):** never compare a hardcoded timestamp against a
  real-`now` marker in a test (it passes before noon UTC, flakes after); a SQLAlchemy session-event
  gate must cover bulk DML (`do_orm_execute`) not just `before_flush`; measure `EXPLAIN QUERY PLAN`
  on real data before adding a drift-prone rollup/cache; the field-test debug bundle can carry a
  STALE error window (errors dated days earlier) — check timestamps before treating them as live.
- **Sequence P0 residuals first, then P1 (backups → keyword → UI → data surfaces → onboarding),
  then P2.** Correctness/data-integrity outranks features.

---

## 0.5 ALREADY SHIPPED + MERGED this cycle — DO NOT REDO (PRs #439, #441)

| Area | Status |
|---|---|
| **P0-1** ingest-index data-loss | DONE — the 149 "database is locked" errors were STALE (pre-dated the merged `do_orm_execute` gate fix). Shipped defence-in-depth: `index_article` re-raises a lock from the WWW block; the best-effort keyword/link sub-writes run through `run_write_with_retry`. |
| **P0-5** trustworthy diagnostics | DONE — `errorlog` writes a BOOT marker + `summary()` reports `locked_errors_this_session` in the debug bundle; the Insights re-index poll storm (1,326 calls/369s) is bounded + cooled down. |
| **P0-2** restore UNIQUE collision | DONE — `article_mentioned_dates` merge dedup keyed on `precision` (was `snippet`) + `INSERT OR IGNORE`; `_restore_error` classifies a constraint clash vs a version gap. **The 236s SLOWNESS is NOT done** → §1 / §2. |
| **P0-3** empty Home | DONE — `get_briefing` recomputes when the corpus grew materially since the cache (boot-airplane left a stale cache). **Whether producers genuinely fire on the live 7.8k corpus is unverified** → §1. |
| **P0-4** read-path perf | PARTIAL — `warm_cache` aligned to the exact Home/Insights keys (it warmed keys nothing requested). Measured the covering index is already optimal; the 18s is SQLCipher decrypt. **The per-day rollup, persisted columnar engine, non-English cache, boot-cold, supergroups/map profiling are NOT done** → §1. |
| **#8** Browse buttons | DONE — `GET /api/fs/list` + `ooFolderPicker()` on the folder-backup destination + .eml folder import. |
| **#10** encryption auto-detect (restore) | DONE (restore side) — `v2DetectEncryption()` reads the file's OOENC1 magic client-side, shows the passphrase field only when encrypted. **The EXPORT-side "encrypt this backup?" in-flow toggle is NOT done** → §2. |
| **#11** restore collision | DONE (= P0-2). |
| **#15** remove "Updates automatically…" note | DONE. |
| **#19** two-letter→full names | PARTIAL — applied `ooRegionName`/`ooLangName` to the source-profile, map-mention readout, link-preview, source-competitive surfaces. **A full click-through sweep of any remaining code surfaces is NOT done** → §5. |
| **#21** empty Home | DONE (= P0-3). |
| **P1 keyword** hi/bn | DONE — the tokenizer (`_WORD_RE`) split Indic combining marks; fixed + hi/bn stoplists + promoted to managed. **The OTHER no_stoplist langs + zh/ja segmentation + date-vocab gaps are NOT done** → §3. |

Everything else from the original brief REMAINS, below.

---

## 1. P0 RESIDUALS (correctness/perf tails — most need the live corpus or a packaging decision)

### 1.1 — Restore slowness (P0-2 tail, folds into §2)
**Evidence:** `/api/backup/v2/restore/preview` 236s each (946s/4 reqs); `/restore/commit` 422s. It
blocks the request thread and contends for the single writer. **Do:** make restore a
**task-manager job** (build → preview/merge → report; pausable; off the request thread) and
profile the merge on a large corpus. Acceptance: a multi-GB restore never blocks the UI; progress
is visible (real counts, no fake ETA). *(Builds with §2 #12.)*

### 1.2 — Confirm Home producers fire on the live corpus (P0-3 tail)
The stale-cache recompute was the load-bearing fix, but verify on the real 7.8k corpus that
`run_all` actually yields cards (not just an honest empty state). If producers are gated too
tightly for a large corpus, loosen the gates with evidence. Acceptance: Home shows Leads on the
live corpus, or a genuine explained empty state — never blank.

### 1.3 — Read-path perf, the remaining levers (P0-4 tail)
- **`trending-windows` per-day rollup** — ONLY if the covering index proves insufficient on the
  live 2.4M-mention corpus. **Measure first** (`EXPLAIN QUERY PLAN` + timing on the real encrypted
  DB). If justified, a maintained `(observed_on, keyword_id) → SUM(count)` daily rollup makes the
  windows a bounded scan. Zero-drift discipline: maintain it at index time + a reconcile, like the
  keyword counters. *(Last session measured ~1s plaintext / 18s encrypted = decrypt-bound, so the
  rollup's benefit is data-distribution-dependent; do not add the drift surface speculatively.)*
- **Non-English cache** — the insights cache key includes `tl` (target language), so a non-English
  UI recomputes the expensive aggregation per language. Decouple the cheap translation annotation
  from the expensive aggregation cache (cache the untranslated result, annotate after the cache read).
- **Boot-cold** — the in-memory insights cache is lost on restart; the first Home/Insights open
  after a restart pays the cold query. Consider a background warm shortly after boot (non-blocking).
- **Profile `supergroups` (≈15s) and `map_data` (≈5s)** — heavier than they should be.
- **Reconcile the counters** — the benchmark showed the keyword counters `basis: "estimated"`
  (unreconciled, 177,398); `top_terms`/`supergroups` read stale values. `warm_cache` already calls
  `maybe_reconcile_counters` (self-throttling) — confirm it actually runs on the live corpus and the
  freshness envelope (`{value, basis, as_of, method, n}`) reaches the UI so the disclosure is honest.
- **Polling** — confirm the adaptive backoff is engaged on the Home polls (`/api/scheduler/activity`
  ×3,997, `/api/system/vitals` ×3,995 since boot); make `trending-windows` lazy so it never blocks
  first paint. Acceptance: Home poll endpoints < 1s warm; no Home interaction blocks > 2s.
- **Persisted columnar engine** — still blocked on the per-OS httpfs crypto-extension packaging
  decision (in-memory = no cross-session gain). Make the decision + bundle the per-OS extension so
  the derived DuckDB store persists encrypted. *(The decade-scale structural lever.)*

---

## 2. P1 — IMPORT / EXPORT (BACKUPS) REDESIGN (#7, #9, #12 + the #10 export half + P0-2 slowness)

Treat all of backups as **one redesign**. Organizing rule: **export ↔ import symmetry; one
elegant, homogeneous, space-efficient UI; the user never sees the two-mechanism split** (encrypted
`oo-backup-2` artifact for DB-row categories + the folder copy for big blobs). The Browse picker
(#8) and restore encryption auto-detect (#10) already landed — build the rest on them.

- **#7 — Redesign "What to include" (it's ugly) + make it comprehensive.** The selectable list must
  span **everything downloaded/derived**: articles, **newsletters**, **scraped/internet articles**,
  **law data**, **indexes**, **agenda/events**, **commodities**, plus the big blobs (Wikipedia
  dumps, Offline maps, LLM models). Principle: *anything downloaded should be backup-selectable.*
  Route DB-row categories → per-category include/exclude on the encrypted artifact (extend the
  newsletter-exclude disposable-snapshot drop pattern per category, with careful dependent-row
  handling, additive-restore-safe); big-file categories → the folder copy. Wire the "coming soon"
  wiki/maps rows for real (they need the ruled-but-pending additive-restore **file-member
  placement** — build it, don't fake it).
- **#9 — Redesign "What to restore" (visually wrong) + unify.** Kill the "use the separate X above /
  restore from the Y panel above" cross-references (they leak the implementation). One restore UI
  mirroring the export UI. Don't over-complicate.
- **#10 (export half) — encryption as an in-flow option.** Export offers "encrypt this backup?" as a
  toggle in the same flow (restore-side auto-detect already shipped). Keep the at-rest plaintext
  warning + the no-recovery passphrase note.
- **#12 — Drop the forced preview; report results after; progress bars both directions.** Replace
  mandatory preview→commit with **direct import that shows what was actually imported** (safe:
  restore is additive-only). Keep preview as an OPTIONAL power-user affordance. Add **honest progress
  bars (#20-style: real bytes/counts, no fake ETA)** to import AND export — which requires the
  encrypted backup/restore to become a **task-manager job / streamed op** (resolves §1.1). Unify the
  progress UX across all import/export paths.

**Acceptance:** one coherent Backups section, no cross-panel pointers, Browse everywhere (done),
encryption optional on export + auto-detected on import, direct-import-with-summary, real progress
bars, every category selectable on both sides, the maintainer's backup round-trips, restore never
blocks the UI.

---

## 3. P1 — KEYWORD ENGINE & EXTRACTION QUALITY (log-derived; the maintainer's optimization loop)

**Evidence (engine report + date diagnostics, live corpus):**
- **52,548 zero-mention orphan keywords** (23% of 229,869) — run the existing
  `prune_orphan_keywords` (curation-safe) + the one-click "re-index then prune" cleanup. Consider
  making a bounded, NON-destructive top-up automatic; auto-PRUNE (destructive) stays a deliberate
  maintainer-gated choice unless ruled otherwise.
- **Tag coverage 0.0%** (0 of top-500 tagged) — the baseline-tag backfill was never run on this
  corpus. Run it (the backfill endpoint + the auto-backfill when the Keywords explorer opens empty
  both exist). *(Needs the live corpus to show effect.)*
- **Translation coverage 13.6%** (68/500 in a ring; 550 rings) — grow rings via the corpus-driven
  loop (`generate_wikidata_rings.py --from-log` on the gap digest, vet the ~6% mis-resolution rate,
  commit, re-measure). *(Needs a networked machine — Wikidata is 403 in the sandbox.)*
- **`no_stoplist` languages still leaking junk** — hi/bn are DONE (tokenizer + stoplists + managed).
  REMAINING: **tr, ro, th, fi, ur, uk, cs, ca, sk, et, vi, fa, bs, az, sw**. Grow evidence-based
  stoplists from the exported per-language keyword logs (`scripts/analyze_keyword_log.py` reads the
  `.zip`). Follow the hi/bn precedent: VERIFY the tokenizer handles each script (Indic/Thai/Arabic
  combining marks may split words like Devanagari did — fix `_WORD_RE` additively before adding a
  stoplist, or the stoplist is dishonest); promote a language to `MANAGED_LANGUAGES` only once it
  genuinely extracts whole words; add `selftest.py` cases (assert a content noun survives + ≥3-char
  grammar is filtered = non-vacuous). Don't disable UI-language sources — give them stoplists.
- **`zh` unsegmented (4,990 broken keywords); `ja` same class** — the standing CJK segmentation gap.
  Decide + ship a segmentation path (e.g. a bundled local segmenter); a stoplist cannot fix missing
  segmentation. This is a genuine design decision — pick the lightest local-first option.
- **Date extraction:** 52.5% coverage; **no month vocabulary for vi/et/th/ur/uk** (zh handled via
  CJK 年月日); CJK 年月日 only 26 hits; **280 articles have date-like text but zero extraction**;
  2,425 bare-years. Add native month vocab for the missing languages (follow the el/sl precedent:
  distinct scripts are collision-free; Latin scripts need accented/unambiguous forms only) + improve
  CJK date handling. *(uk Cyrillic months are distinct from Russian — safe; vi uses "tháng N" not
  month names — needs a pattern, not a table; th has Buddhist-era years — handle carefully.)*

**Acceptance:** orphans pruned, tag coverage > 0, ring coverage rising, more UI/corpus-languages
managed (each genuinely extracting, not just stoplisted), a zh/ja segmentation decision shipped,
date coverage up for the gap languages. Re-export the engine report and diff to prove each lever
landed.

---

## 4. P1 — UI / LAYOUT & NAVIGATION (frontend, browser-unverifiable — conservative + flagged)

Cross-cutting directive: **space-efficient, data-dense, clearly-sectioned, fill-the-viewport layouts.**

- **#13 + #14 — Markets twin-board responsive graph grid (binding for BOTH Commodities and Indices).**
  Every subtab (incl. "All") renders its graphs in a **responsive multi-column grid that adapts to
  screen width** (auto-fit/auto-fill); each category subtab shows **per-commodity / per-index** graphs
  in that grid. Reuse `dashChartSvg`; keep invariant #16 (full-resolution, n<10→bars). Keep the boards
  identical (twin-board ruling).
- **#16 — Agenda: every view fills the screen with data + is visually distinct.** Month / trimester /
  year each **designed for their scale** (not one grid rescaled) and **filling the viewport**; the
  **week view's vertical-days layout is good — keep it** but expand it to cover the visible area. No
  cramped grids in empty space. Keep agenda invariants (#13) intact.
- **#17 — Settings: fuse Appearance + GUI into one clearly-sectioned section** (themes + typeface +
  the 8 alternative-interface skins), space-optimized. **Remove the "Tools shown in the sidebar"
  checklist entirely** — it's outdated (lists moved/dissolved tabs) and useless. Remove the
  sidebar-visibility feature + its persistence; ensure nothing becomes unreachable; reconcile the
  ACTUAL current sidebar set.
- **#22 — Left sidebar: remove the section headers** ("Investigate" / "Collect" / …); present **all
  tabs as one flat list.** Invariant #2 stays (lists all tabs, visible, collapsible to a rail) — just
  de-grouped. Land #17 + #22 together (both touch the sidebar) so it ends up one clean, current, flat
  list.

---

## 5. P1 — DATA SURFACES & TABS

- **#5 — Task manager: show the actual queued languages & tags.** The Queue preview says "stratified
  by language and tag" — also DISPLAY the actual strata. `stratified_interleave` knows them.
  **Caveat (last session's reasoned skip):** `plan_preview` is per-poll and was specifically optimized
  (it was the #1 endpoint by server time) — do NOT add unbounded `SELECT DISTINCT` scans there.
  Derive the strata cheaply (e.g. from the bounded sample plan_preview already fetches, labelled
  honestly, OR a cheap cached/indexed distinct), no fabrication, keep the randomisation caveat.
- **#6 — Settings → AI: one-click "Install AI support".** A single button automates **download +
  install of Ollama → activate → first model pull**, hardware-driven. Detect + SHOW the hardware +
  explain the hardware→quality relationship, then branch (GPU ~5GB→`mistral:7b`; ~8GB→`mistral-nemo:12b`;
  ~16GB→`mistral-small:22b`; CPU 8–16GB→`mistral:7b`+slow warning; CPU <8GB→no auto-pull, offer "proceed
  anyway"; plus GPU<5GB→a 3B/4B model, 24GB+→bigger, Apple-Silicon unified-memory branch, free-disk
  preflight, already-installed skip). **Constraints (binding):** the binary auto-install needs **real
  per-OS Ollama installer URLs + checksums verified on a networked machine** (forbidden to fabricate);
  download → verify checksum/signature → run via the guarded factory with a **visible OS elevation step
  (never silent)**; **verify the exact model tags + sizes** against ollama.com; install+pull **egress
  clearnet via the Ollama process (not Tor)** → one consent + clearnet disclosure; **progress bar** with
  real byte progress (Ollama `/api/pull`), honestly indeterminate during elevation.
- **#18 — World Law tab: full revamp + automatic scraping + cover all UI-language countries.** The tab
  is under-specified and near-empty in the field DB (`law_track`: 0 documents/baselines). Apply the
  established design language (content-first, data-dense, fill-the-screen, analysis-window/corpus
  integration, version-tracking like wiki, no verdicts). Wire law sources into the **scheduler pass**
  (auto-scrape, airplane-gated, via EthicalFetcher). Build a **languages→countries map** + a curated
  sourced legal-source catalog **per country for every UI language** (Arabic→its countries,
  Spanish→Spain+LatAm, Portuguese→PT+BR, …), seeded disabled, honest provenance — reinforces
  de-US-centring.
- **#19 (tail) — two-letter codes → full localized names, full sweep.** The clear NAME surfaces are
  done; do a click-through sweep for any remaining code-as-name surface (using `ooRegionName`/
  `ooLangName`); the flag-emoji computation, URL anchors and provenance/tags correctly KEEP the code.
- **#20 — Move "Evidence & custody" into Settings (→ Safety subtab) + make it foolproof.** Completes
  the Trust-group dissolution (Source integrity already moved). Simplify the expert crypto (ML-DSA/
  FIPS-204, OpenTimestamps, Merkle, "actor") into plain-language controls; push detail into `#oo-tip`
  hovers. Don't lose functionality (export/verify, auto-log-on-ingest ON by default, OTS/Bitcoin OFF by
  default); keep verify/export reachable from content (absorption-test-gated, the Desk lesson).
- **#23 — Settings → Sources: multi-select dropdown filters + keep title search.** Convert Language /
  Country / Type / Tags to **dropdown filters** with **additive multi-select** (French *and* English,
  multiple tags). Keep the free-text title search. Localize option labels to full names (#19). Make
  combination semantics explicit (within-filter OR; across-filter AND; an explicit AND/OR toggle for
  tags). Feed the dropdowns from real distinct catalog values (a cheap facets endpoint).

---

## 6. P1 — ONBOARDING & FIRST-RUN (frontend; encryption-by-default ordering is sacred)

- **#1 — Add a "Back" button to the install/first-launch screens** (language → legal/consent →
  passphrase). Back preserves entered state (chosen language persists) and must not skip the
  encryption-by-default ordering — it only re-navigates.
- **#2 — Collapse "go online" to one screen / one step.** Today: a full initial screen + a second
  screen + the top-right coachmark balloon (`#net-coach`). Merge the redundant layers INTO the single
  informed-consent screen (invariant #14 stays — the one remaining step IS the consent: names the
  action, shows local interface IPs, honest public-IP wording). Consent isn't removed; the duplication
  around it is.
- **#3 — New-user UI tutorial (~8-step visual walkthrough).** Orients the user to UI elements +
  navigation (sidebar, top bar, omnibar, airplane, language switcher, task manager, Leads, analysis
  window). **Dismissible forever** (a user-visible Settings toggle like `oo_guide_v1`, never a hidden
  flag) and **replayable from Settings.** Distinct from the first-launch *setup* wizard — this
  *orients*. Ride existing conventions: ×12 i18n, `#oo-tip` styling, a11y, anchor steps via
  `getBoundingClientRect`.

---

## 7. P2 — DATA / SOURCE HOUSEKEEPING (log-derived)

- **#4 — World map: completeness, detail, neutral borders.** Some countries don't render (NE 110m
  drops ~75 microstates to centroid points). **Recover the maintainer's prior list of missing
  countries from session history/issues AND guarantee complete coverage** (finer base / OSM
  boundaries) so the list is moot. **Much more detail by default** (NE 50m, or 10m / OSM on-demand —
  balance against bundle size). **Politically-neutral disputed borders (ruling):** where border data
  conflicts, use a NEUTRAL visual strategy (dashed/hatched/fuzzy zone, or show all claims) — never a
  single hard line that implies a verdict. Drive it from Natural Earth's disputed-areas layers.
- **Dead calendar feeds wasting preflight.** All `google-hol-*` editions are robots-disallowed,
  `webcal.guru` disallowed, `raw.githubusercontent.com` undetermined → all dead. **TENSION (resolve
  honestly):** `configs/calendar_feeds.yml` documents these as a deliberate "stays-listed-with-honest-
  verdict" choice, so do NOT silently delete them (that drops a disclosure). The reconciliation:
  EXCLUDE known-robots-disallowed providers from the automatic preflight SAMPLE (stop wasting cycles)
  while KEEPING them listed with their honest verdict. Working set to prefer: `worldpublicholiday.com`
  (wph-*), `pirate.monkeyness.com` moons, `cantonbecker.com` astro, `space.floern.com` launches,
  `ose-calendar`.
- **Dead FRED commodity series.** gold `PGOLDUSDM`, silver `PSILVUSDM`, sawnwood `PSAWMUSDM` → HTTP 404
  (`dead-series`). Source + verify replacement FRED ids **on a networked machine; never fabricate.**
  *(Blocked in-sandbox; they already surface honestly as dead-series.)*

---

## 8. CROSS-CUTTING FOLLOW-UPS DISCOVERED LAST SESSION (not in the original brief)

- **Insights cache `tl` dimension** (see §1.3) — non-English UIs recompute the expensive aggregation
  per language because `tl` is in the cache key; decouple translation annotation from aggregation.
- **Boot-cold insights cache** (see §1.3) — warm in the background shortly after boot.
- **Tokenizer portability for the remaining no_stoplist langs** (see §3) — verify `_WORD_RE` per
  script before stoplisting (the hi/bn matra bug will recur for other combining-mark scripts).
- **The wiki/maps additive-restore file-member placement** (see §2 #7) — the ruled-but-unbuilt
  prerequisite for backing up Wikipedia dumps + offline maps; build it with the backups redesign.
- **Restore-as-a-task-manager-job** (see §1.1 / §2 #12) — the shared mechanism behind progress bars +
  the 236s slowness fix.

---

## 9. VERIFICATION — complete feedback-item map (#1–#23), nothing omitted

| # | Item | Status | Covered in |
|---|---|---|---|
| 1 | Back button (install/first-launch) | REMAINING | §6 |
| 2 | One-step go-online | REMAINING | §6 |
| 3 | UI tutorial | REMAINING | §6 |
| 4 | World map completeness/detail/neutral borders | REMAINING | §7 |
| 5 | Task-manager strata | REMAINING | §5 |
| 6 | AI one-click install | REMAINING | §5 |
| 7 | Backups "what to include" | REMAINING | §2 |
| 8 | Browse buttons | **DONE (#441)** | §0.5 |
| 9 | Backups "what to restore" | REMAINING | §2 |
| 10 | Encryption auto-detect | **DONE restore; export half REMAINING** | §0.5 / §2 |
| 11 | Restore collision | **DONE (#439, = P0-2)** | §0.5 |
| 12 | Drop forced preview + progress + restore-as-job | REMAINING | §2 |
| 13 | Markets grid (commodities) | REMAINING | §4 |
| 14 | Markets grid (indices) | REMAINING | §4 |
| 15 | Remove auto-update note | **DONE (#439)** | §0.5 |
| 16 | Agenda views | REMAINING | §4 |
| 17 | Settings Appearance+GUI / remove sidebar list | REMAINING | §4 |
| 18 | World Law revamp + auto-scrape + per-country | REMAINING | §5 |
| 19 | Two-letter→full names | **DONE clear surfaces; full sweep REMAINING** | §0.5 / §5 |
| 20 | Custody → Settings | REMAINING | §5 |
| 21 | Empty Home | **DONE (#439, = P0-3)** | §0.5 |
| 22 | Flatten sidebar | REMAINING | §4 |
| 23 | Sources multi-select filters | REMAINING | §5 |

| Tier | Status |
|---|---|
| P0-1 / P0-5 | **DONE (#439)** |
| P0-2 collision | **DONE (#439)**; slowness REMAINING (§1.1/§2) |
| P0-3 | **DONE (#439)**; live-corpus producer check REMAINING (§1.2) |
| P0-4 | PARTIAL (#439); rollup/columnar/non-English/boot-cold/profiling REMAINING (§1.3) |
| P1 keyword | hi/bn DONE (#439); the rest REMAINING (§3) |

---

## 10. Suggested sequencing
1. **P0 residuals (§1)** — restore-as-a-job (also unblocks #12 progress), then the read-path tails;
   verify Home producers on the live corpus.
2. **Keyword engine quick wins (§3)** — orphan-prune + tag-backfill runs, then per-language stoplists
   (cheap, reduces the data the slow aggregations chew); CJK + date-vocab as their own slices.
3. **Backups redesign (§2)** — the maintainer's largest UX pain; builds on the merged picker + auto-detect.
4. **UI / layout (§4)** — ship #17 + #22 together (sidebar), then markets grids + agenda views.
5. **Data surfaces (§5)** — AI install, law revamp, sources filters, custody move, task strata, #19 sweep.
6. **Onboarding (§6)**, then **P2 housekeeping (§7)**.

**Every slice: draft PR onto a freshly-fetched `0.09`, CI subscribed, tests + invariants extended,
i18n 100%, `node --check`, record any new ruling into `CLAUDE.md`. Diagnose every CI failure the PR's
own lanes surface and fix it (a flaky/observation-lane failure still gets fixed). P0/correctness first.**
