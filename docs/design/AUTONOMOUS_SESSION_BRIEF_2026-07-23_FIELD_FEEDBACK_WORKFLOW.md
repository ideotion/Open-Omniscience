# Autonomous session brief — 2026-07-23 field-feedback workflow

**Status: PENDING execution.** This is the operating manual for one (or several
consecutive) autonomous CLI session(s) executing the maintainer-ruled workflow from the
2026-07-23 field-feedback round (seven impressions → twelve answered questions → two
all-diagnostics exports analyzed → this program). The binding record is the ledger entry
**"FIELD FEEDBACK 2026-07-23"** in `CLAUDE.md` (Open queue) — read it in full first; this
brief expands it into buildable slices. Nothing here overrides the ledger; on any
discrepancy the ledger wins.

---

## §0 Mission + evidence base

The maintainer runs several OOS instances (all over Tor) and delivered:

1. Seven field impressions (import reporting · import-time article screening · Library
   live graphs · scraping stalls · Downloaded-section tidy-up · ~50k sources vs ~5k
   articles · throughput too slow, want ≥10×).
2. Twelve answered questions (A1–A12, verbatim rulings in the ledger entry).
3. A sources CSV (46,213 rows) + TWO all-diagnostics zips from instances launched at the
   same time on very different hardware (AMD 3020e 2c/3.2 GB vs i7-13620H 4c/9.7 GB).

**The measured verdicts this program executes against** (full numbers in the ledger
entry's "DIAGNOSTICS EXPORT ANALYZED" + "SECOND-INSTANCE COMPARISON" sections):

- The "50k sources" = 42,612 (slow box) / 66,697 (fast box) DISABLED
  `via:wikidata-discovery` world-catalog **candidates**, blended with ~3,599 enabled
  sources into one Library "Sources" count. A display problem + a funnel-throughput
  problem, not a registration bug.
- Throughput is **three stacked causes**, hardware-ranked by the two-instance experiment:
  (a) **duty cycle** — 3–8 min inter-pass gaps on BOTH machines (fast box: 48% fetching /
  52% gap) from single-core briefing analytics + serial Tor ride-along fetches; fixing it
  ≈ 2× on modern hardware and helps every machine; (b) **supply** — ~90% feed duplicate
  rate on both; 2,766 enabled feeds yield ≈2 new/day/feed on average; 10× needs the
  candidate backlog qualified + enabled; (c) small-box **memory floor** — the governor
  parks permits at median 2 on 3.2 GB RAM (`mem-low`); hardware-dependent, only lever is
  headroom-aware behaviour, not promises.
- **NEW measurement**: the fast box hits `writer-bound` pass verdicts at permits ~27 —
  the live evidence the deferred COLLECTOR write-batching was explicitly gated on
  (ledger P1.3 deferral, 2026-06-25). It is now evidence-justified.
- The rate-mode default flip + top-bar knob + version-under-logo already SHIPPED on PR
  #748 (this brief's own PR). Both field instances still run `"target"` from saved
  settings — flipping them is a maintainer click on the knob, not a session task.

**STALENESS GUARD — verified-current state (2026-07-23, main + PR #748 tip). This
program was bitten twice in ONE session by stale "unbuilt" beliefs; re-verify each of
these against the tree before building anything:**

| Capability | State | Anchor |
|---|---|---|
| Qualification lifecycle | **BUILT + LIVE** (admission gate, trial fetch, stamps, 1→2→4→6-month ladder, append-only attempts; ride-along `qualification_per_pass=5`) | `src/catalog/qualification.py`; gate in `src/scheduler/runner.py` (`select_sources`, ~:330); ride-along wiring runner.py ~:1317; `qualification_per_pass` `src/scheduler/settings.py:103`; `Source.status`/`qualified_at`/`qualification_criteria_version` `src/database/models.py` ~:399–461 |
| Bulk qualification job | **NOT built** (only the 5/pass ride-along) | — |
| Two-class sources display | **NOT built** (Library blends the counts) | `src/api/library.py` (~:140 `counts.get("sources")`) |
| Prose gate (nav-soup criterion) | **BUILT** (AND-gated function-word density + sentence-punctuation density) | `src/services/prose_gate.py` |
| Non-article scan w/ opt-in prose gate | **BUILT** (`include_prose_gate=True`, bounded decrypt batch) | `src/analytics/non_article_scan.py` |
| Retroactive quarantine job | **SCAFFOLD BUILT, deliberately UNWIRED** — dry-run detection only, no `Article` quarantine column, no singleton/endpoint; its own docstring says execution waits for maintainer sign-off | `src/analytics/quarantine_job.py` (chassis mirrors `ReindexJobManager`; `_work_fn` seam is the swap-in point) |
| Import-time screening / quarantine schema | **NOT built** | — |
| Import report (JSON+Md, persisted) | **NOT built** (summary is the in-dialog `_renderImportSummary`, `src/static/app.js` ~:5875, headline still a cross-table row-sum per the 2026-07-20 ruling) | — |
| Snapshot recorder / Library graphs | **NOT built** (render substrate exists: `dashChartSvg` tiny cards + `chartEnlarge`→`ooChart`) | `src/static/app.js` |
| Diagnose-the-diagnostics (journal, hardware header, runtime coverage) | **BUILT + field-proven** by both exports | `src/api/diagnostics.py` (`_write_all_diagnostics_zip`) |

**The maintainer's A2–A4 answers ARE the sign-off the quarantine scaffold was waiting
for** — with one condition preserved: the calibration diagnostic (S3.1) runs FIRST and
the maintainer reviews its output before any retroactive quarantine EXECUTES (0.3 gate
row 5: strategy discussed → agreed → implemented → executed).

---

## §1 Working mode (reset-proof; the house rules apply in full)

- **Read `CLAUDE.md` in full before any work.** Record every new ruling there in the
  same turn. Shipped work → a `docs/ledger/shipped.csv` row (+ `SHIPPED_LOG.md` +
  Lessons when a reusable lesson exists). Never compress away a pending ruling.
- **Staleness guard FIRST, per slice**: `git fetch origin main` immediately before
  cutting each branch from `origin/main`; re-verify the §0 table's rows you touch
  (grep, don't trust this doc's snapshot). The maintainer fast-merges; local
  `origin/main` goes stale within minutes.
- **Branch/PR discipline**: one DRAFT PR per slice onto `main`, branch prefix
  `claude/ff23-*`. Nothing self-merges. After `git push`, if the output says
  "[new branch]", the previous PR was merged — open a NEW PR.
- **Verification gates (all blocking)**: full `pytest -q` suite green where the env
  allows (py3.13 venv; sqlcipher/[analysis]-gated tests are CI-only — prove the
  algorithm with a standalone repro per the house lesson); `ruff check --select=F,B
  --extend-ignore=B008`; mypy ratchet ≤ baseline (run `python3 -m mypy <changed.py>`
  per file); `node --check` every touched JS; `scripts/i18n_report.py --min 100` when
  chrome strings change (12 locales, Arabic RTL); `bandit -r src -ll -q` for new
  dynamic SQL (`# nosec B608 - <reason>` convention).
- **Skeptics-before-push** on every data-safety or parser slice (S3 especially):
  parallel adversarial verifiers with distinct lenses INCLUDING the negative-space
  lens (should-be-empty inputs), completed BEFORE `git push`; findings hand-re-verified
  (the 06-audit false-positive lesson); reproducers pinned as tests.
- **Frontend = fork-3/Q6a conservative**: no browser here. Ship node-checked +
  invariant-guarded + defensive empty states, flagged "browser-unverified, needs
  click-through" in the PR body. Never a caveat hidden, never a score, counts with n.
- **Honesty non-negotiables** (§0.5 + ledger): no composite scores (walk payload KEYS
  for score/ranking/rating/grade substrings — remember `"degraded"` contains `"grade"`:
  statuses are VALUES, never keys); every number carries its method; degrade loudly;
  local-first (zero new egress paths; loopback writes are never consent-gated, network
  actions always are); anti-capping — a displayed figure must never secretly be a cap.
- **Schema changes**: additive nullable columns + a genuinely-random 12-hex alembic
  revision id (grep the versions dir; get the real head from `python3 -m alembic
  heads`, never a regex scan) + boot self-heal + `test_no_model_drift` green + one
  line in `src/backup/merge.py`'s explicit column map so backups carry the new fields
  (verify the cross-version restore floor migrates an OLDER incoming backup before the
  merge SELECTs the new column).
- **Store helpers + savepoints**: before wrapping any existing helper in
  `begin_nested`, grep it for internal commit/rollback (the #691 lesson).

---

## §2 Slice S1 — Qualification: VERIFY + SCALE + SURFACE (do first; ruled A8)

**S1.1 VERIFY the live lifecycle** against the 2026-07-20 rulings (a read/test pass, no
rebuild): admission gate only admits QUALIFIED sources to regular collection; the seed
catalog qualifies via its own first collect pass (all-sources-qualified-by-definition —
no grandfathering); disqualified domains are SKIPPED by the citation/discovery funnels
(never re-proposed); the re-qualification ladder derives from the append-only attempt
history; a catalog source failing qualification surfaces as a CATALOG-REVIEW signal.
Pin anything unpinned as tests. Field evidence to reconcile: the slow box logged one
`qualification trial fetch failed for 'latimes.com'` (transport failure ≠
disqualification — verify a fetch error never stamps disqualified).

**S1.2 BULK qualification job** — the backlog drainer. The ride-along at 5/pass needs
~90+ days for 42.6k–66.7k candidates. Build a task-manager-visible, cancellable,
resumable BackgroundJob (reuse the `src/catalog/discover_job.py` persisted-cursor
pattern + the qualification module's own `run_qualification_pass`/`evaluate_and_stamp`
primitives — orchestration only, never a second judging mechanism): bounded
concurrency (a few parallel trial fetches, per-host politeness untouched, own
sessions, writer gate never held across a fetch), NETWORK job kind (consent-gated
start via ensureOnline, refuses under airplane, pauses cleanly on airplane engage),
persisted cursor + append-only attempts (idempotent re-runs), honest progress
(evaluated/qualified/disqualified/errors + rate-derived ETA), memory-guard aware
(back off on mem-low like the collector — the 3.2 GB box must survive running it).
Endpoints + a Settings/source-management start button + `/api/jobs` surfacing.
The ride-along stays (steady-state trickle); the job is the catch-up tool.

**S1.3 TWO-CLASS sources display** (frontend, conservative): the Library "Sources"
stat splits into **enabled/qualified sources** vs **discovered candidates (disabled,
awaiting qualification)** — never one blended number (the maintainer read 46k as an
alarm precisely because of the blend). Backend: split counts in the library/db-stats
payload (cheap indexed counts by `enabled`/`status`). Same split anywhere "sources"
renders as a single total. Show the stamp ("qualified by Open Omniscience on DATE ·
criteria vN") in source management; the qualified-citations tally + discovery-trail
surfaces from the 2026-07-20 rulings are IN SCOPE here if time allows, else carried
over explicitly.

**Acceptance**: the bulk job drains a synthetic candidate set resumably (cancel/airplane
mid-run → resume from cursor, no double-stamps); counts never blended; every new
payload key walks clean of score-substrings; tests for the funnel-skip of disqualified
domains.

---

## §3 Slice S2 — Library graphs + the snapshot recorder (items 3+5; ruled A5)

**S2.1 Snapshot recorder**: a small additive table (e.g. `stat_snapshots`: taken_at ·
counter name · value) written HOURLY (and at pass end, cheap) from the MAINTAINED
counters — articles, sources by class (enabled/qualified vs candidates), keywords,
mentions, article_links, commodity price points, wiki pages + revisions, law documents
+ revisions, quarantined (once S3 lands). **INFINITE retention (ruled)** — at ~10–15
counters hourly this is trivial rows/decade; no downsampling. Writer: the scheduler
housekeeping + idle-maintenance path (never the fetch hot path; single-writer gate
respected; a failed snapshot degrades loudly, never blocks a pass). Honesty: series
begin when recording begins — NEVER fabricate a backfill; the articles-per-hour series
MAY backfill honestly from `Article.created_at` (real timestamps), and wiki/law series
from stored revision timestamps; every other counter starts at first snapshot with the
start date stated.

**S2.2 Library graphs** (frontend, conservative): replace the live FIGURES with
box-sized GRAPHS — corpus section: articles/hour over the past 7 days + the live rate;
database section: count-evolution series per counter. Reuse `dashChartSvg` (tiny cards,
shared time axis, Item-Y sparse bars, n shown) + click-to-enlarge via the existing
`chartEnlarge`→`ooChart` dialog (full interactivity: zoom/pan/readout — invariant #16).
Graphs must NOT exceed the current boxes' footprint. Honest empty state before enough
snapshots exist ("recording since …").

**S2.3 Downloaded-section tidy** (item 5): compress to compact chips; ADD two sections
— "Wikipedia tracked" (pages + revisions over time) and "Law tracked" (documents +
revisions over time), each with the same small-graph + enlarge grammar.

**S2.4** This doubles as the STALL DETECTOR (item 4): an articles/hour trough is
visible at a glance. Additionally surface the per-pass timeline the debug bundle
already carries (pass start/end + gap) in the task-manager Schedule subtab if cheap.

**Acceptance**: snapshot writes are idempotent-per-hour + gate-clean; graphs render
from real snapshots with the honest start note; no oversized layout shift (invariant
#3 footprints); i18n via keyed strings or the `t()` fallback convention.

---

## §4 Slice S3 — Screening + quarantine + the import report (items 1+2; ruled A1–A4)

**ORDER INSIDE THIS SLICE IS BINDING**: S3.1 ships and the maintainer REVIEWS its
output before S3.4's retroactive execution runs on any real corpus.

**S3.1 The TEMPORARY criteria-calibration diagnostic** (A4): a downloadable report —
top-100 disregarded/would-be-disregarded articles under the CURRENT criteria
(extraction-validity URL/shape rules + the prose gate + the borderline classes), with
per-article detail (id, title, url, source, word count, function-word density,
sentence-punctuation density, which criterion fired) + aggregate statistics (per
criterion, per source, per language) so the maintainer optimizes criteria on real
specimens. Reuse `scan_non_article_candidates(..., include_prose_gate=True)` +
`prose_gate` — this is a REPORT over the existing detectors, not new judging. Rides
the Diagnostics panel + the all-diagnostics bundle (respect the coverage ratchet:
member or documented exemption). Iterative loop: maintainer reviews → criteria
adjusted (propose→review→apply, the stoplist discipline) → re-export.

**S3.2 Quarantine schema + write step** (A2): additive `Article` columns (quarantined
flag/status · quarantine_reason · quarantine_criteria_version · quarantined_at) via the
standard migration + boot-self-heal + merge.py column-map pattern; REVERSIBLE by
construction (un-quarantine restores full visibility); quarantined articles are
EXCLUDED BY DEFAULT from search/FTS results, analytics, keyword indexing surfaces and
Home — but their rows, keywords and provenance stay intact (never a delete). They RIDE
backup export/import (ruled). Wire the write step into the existing
`quarantine_job.py` scaffold's `_work_fn` seam (idempotent on an already-quarantined
row, per its own docstring) + the `get_*_manager` singleton + `/api/jobs` surfacing the
scaffold deliberately left out. Re-index after a quarantine batch clears the junk
keywords/entities (reuse the reindex job; state the cost honestly).

**S3.3 Import-time screening** (A2): the same classifier runs on INCOMING articles
during restore-merge/import — a flagged article is imported QUARANTINED (never
skipped/dropped: quarantine-in-DB was chosen over skip-and-export precisely because
criteria keep evolving), counted per class in the report. The additive-restore
non-negotiable is untouched (nothing replaced or deleted; quarantine is a stamp).

**S3.4 Retroactive screening job** (A3): the scaffold job, now write-enabled, run over
existing corpora — resumable, pausable, criteria-version-stamped, dry-run mode kept.
**EXECUTION GATE**: ships dry-run-default; the actual write run on the maintainer's
corpora happens after the S3.1 review round says the criteria are agreed (record the
agreement in the ledger when it happens).

**S3.5 The import REPORT + post-import screen** (A1 + the ruled 2026-07-20 screen —
ONE build): a dedicated post-import results popup with (a) the ARTICLES-first headline
+ labeled per-type breakdown (the cross-table row-sum may remain only if labeled
"database records, all types"); (b) the corpus-delta view (before→after via cheap
counter snapshots — reuse S2.1's recorder); (c) induced work (N sources awaiting
qualification, N quarantined-on-import with a link to review); (d) **Download report**
— JSON + Markdown, PERSISTED under `data_dir()` (a browsable history of past imports),
and the persisted reports ride backup export/import (ruled A1). Numbers through the
shared formatter + `OOI18N.tf` templates ×12.

**Skeptic mandate**: S3.2/S3.3 are data-safety-critical — full adversarial pass
(negative-space: articles that must NOT quarantine — unsegmented zh/ja/th bodies skip
the prose gate per the S5.2 mislabel lesson; short-but-real terse prose; quoted lists
inside real articles) before push.

---

## §5 Slice S4 — Throughput levers (evidence order; measure before/after)

**S4.1 DUTY-CYCLE fix — the top lever (~2× on modern hardware, helps every box):**
the 3–8 min inter-pass gap is (i) the single-core briefing refresh and (ii) the
ride-alongs' serial Tor fetches (calendar auto-imports, wiki/law tracking, discovery,
world-discovery, qualification trials). Design directions (pick per evidence, each
independently shippable): run the briefing refresh CONCURRENTLY with the next pass
(read-mostly; verify writer-gate + session hygiene — no gate held across analytics;
the `run_in_threadpool`/background-thread pattern), and/or overlap the network
ride-alongs with the next pass's fetch phase (they already use own sessions;
politeness + kill-switch unchanged), and/or bound per-gap ride-along work. HARD
CONSTRAINTS: single-writer correctness; airplane semantics; a ride-along failure never
breaks a pass (the existing savepoint posture); no polling storms. MEASUREMENT: the
duty-cycle % from the scheduler run history (both exports establish the baseline:
65%/48%) — state before/after in the PR; the maintainer's 8-core/20 GB machine is the
clean before/after bench (operator step).

**S4.2 COLLECTOR write-batching — now evidence-justified** (the fast box's
`writer-bound` verdicts at permits ~27 are the live measurement the 2026-06-25
deferral demanded): restructure the collector store path per
`docs/design/COLLECTOR_WRITER_BATCHING.md` using the existing `index_article(commit=False)`
primitive + the PROVEN rollback-then-redo-per-article fallback (`_redo_committed`
shape) — a lock/collision never drops a batch-mate; the no-loss battery
(tests/test_write_gate_dataloss.py grammar) extends to the collector path; the ETA
P1.8 autoflush lesson applies (bookkeeping AFTER the network loop, session leaves
clean). This is the riskiest hot-path change in the program — full skeptic matrix,
and it lands AFTER S4.1 so its effect is measured in isolation.

**S4.3 Memory-headroom honesty for small boxes**: no magic — document/profile the
mem-low floor (the 3.2 GB box parks at 2 permits by design, protecting the machine);
fold a "this machine's RAM caps parallel collection at ~N workers" line into the
collect_perf verdict + optionally the power-profile surface. Never promise 10× on
3–4 GB hardware.

**S4.4 Crawl mode expansion: OUT OF SCOPE** unless the maintainer rules it — record
interest, don't build.

---

## §6 Slice S5 — Small defects from the two exports

1. **htmldate.meta log-noise filter**: `impossible to clear cache for function` ×85 =
   85 of 93 logged "problems" on the slow box — a third-party logger polluting the
   error log's signal. Add a targeted logging filter (that logger + that message
   class), never a blanket suppression; the error-log counters must stop counting it
   as a problem.
2. **KPI K2 resolver TypeError** (`kpi.json`: "resolver error (not-measurable):
   TypeError" for Interactive-endpoint-p95): a real resolver bug hiding behind an
   honest verdict — fix the resolver, pin with a test against the request-latency
   payload shape that broke it.
3. **`locked_errors` 6/session** on the slow box: investigate the log lines' origin
   (the is_locked_error family); if a real ungated write path surfaces, fix it; if
   benign retries, say so in the ledger.
4. **world-discovery `gb/news: Expecting value…`** (fast box): a Wikidata response
   that wasn't JSON was correctly best-effort-skipped — improve the recorded error to
   carry the HTTP status/first bytes class so rate-limiting is distinguishable from a
   broken query (observability only, no retry-policy change).

---

## §7 Out of scope / operator steps / gates

- **Operator (maintainer) steps, not session work**: click the new top-bar knob on
  existing installs (saved settings predate the "maximum" default); run the bulk
  qualification job (network consent); the 8-core/20 GB before/after bench for S4.1;
  review the S3.1 calibration report (gates S3.4's real run); browser click-throughs
  of every conservative frontend slice (the knob + version from PR #748 included).
- **Gated/parked (do NOT build)**: crawl-mode expansion (S4.4, needs a ruling);
  the Observatory; the 5 new verticals; anything the ledger marks
  operator/ruling/browser-gated. The qualified-citations tally + discovery-trail
  surfaces (2026-07-20) are OPTIONAL stretch inside S1.3 — carry over honestly if
  skipped.
- **Never**: fabricate a measurement or a pass; enable a candidate source outside the
  qualification path; add egress; hide a caveat; delete quarantined data.

## §8 Definition of done + closeout

Each slice: its own draft PR, gates green, skeptics complete (where mandated), a
`shipped.csv` row, lessons harvested. The session closes with: a ledger closeout
(what shipped · what's carried over · the operator list), the duty-cycle and
qualification-backlog numbers restated with their post-change measurements where
available, and NO pending ruling silently dropped. The 0.3 close-gate rows this
program advances (row 1 source-management program, row 5 cleanup strategy, row 8
browser bar) get their status updated in the CHANGES 0.3.0 board if touched.
