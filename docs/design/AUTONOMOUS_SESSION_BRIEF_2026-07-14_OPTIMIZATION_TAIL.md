# Autonomous session brief — the optimization tail (2026-07-14)

**Status:** OPERATING MANUAL for one autonomous Claude Code CLI session (maintainer-directed
2026-07-14: "a detailed prompt for an autonomous session addressing all of our previously
unaddressed optimizations"). Reset-proof: everything needed to execute is in this doc + the
repo; if your context is summarized mid-session, re-read this file and continue from the
per-slice status you have been recording.

**Mission in one line:** close every *codeable-now* optimization item left open across the
boards — the recursive-improvement instruments (V1_PATHWAY §2.4 R1/R2/R4/R5), the S2
snappiness carry-overs, and the optimization-program tails — so that after this session the
only open optimization work is operator-gated (live corpus / Ollama rig / AppVM) or
ruling-gated (V1-6/V1-7).

---

## §0 Read FIRST, in this order

1. **`CLAUDE.md` in full** (the protocol demands it; the Lessons subsection contains the traps
   this brief cites by name).
2. This brief.
3. [`V1_PATHWAY_2026-07-14.md`](V1_PATHWAY_2026-07-14.md) §2 (the loop + R-items) + §7.1.
4. [`../ROADMAP.md`](../ROADMAP.md) §2 (P1 board — the carry-over rows quoted below).
5. [`PLANNING_2026-07-12_OPTIMIZATION_PROGRAM.md`](PLANNING_2026-07-12_OPTIMIZATION_PROGRAM.md)
   §1/§2/§7 (the Conjunction-Lens/Leads-2.0/power-profile designs of record — slices L/M/K
   implement THEIR specs, not new ones).

**THE STALENESS GUARD IS RULE #1.** This brief was written against `origin/0.2` @ `55a203e`
(2026-07-14, #682 merged). The maintainer fast-merges parallel sessions — before EVERY slice,
verify its anchors against the tree; if you find an item already built, VERIFY-AND-MARK it
(ledger row "found already resolved"), never rebuild. Precedents: S4.7, S6.1, the elections
calendar (all found shipped mid-plan).

## §1 Working mode (binding)

- Branch `claude/opt-tail-<suffix>` cut from a **freshly fetched** `origin/0.2`
  (`git fetch origin 0.2 && git checkout -B <branch> origin/0.2` — the stale-base lesson).
  One working branch with **one commit per slice** under ONE draft PR onto `0.2` is fine
  (the S1–S6 harness); nothing self-merges — the maintainer merges.
- **Verification gates per slice** (all must pass before the slice's commit):
  full `pytest -q` in the repo's py3.13 `.venv` when available (else the CI-only fallback:
  targeted tests + standalone repros per the ledger's sandbox lessons) · `ruff check
  --select=F,B --extend-ignore=B008 src/ tests/` · mypy ratchet ≤ baseline (`python3 -m mypy`
  on changed files at minimum) · `node --check` after any JS edit · `python scripts/
  i18n_report.py --min 100` if locale files change · new user-visible strings via `t()`
  English-fallback (keyable later) unless the slice says otherwise.
- **Skeptics-before-push** for every slice marked ⚠ below: at least two adversarial reviewer
  agents with distinct lenses (correctness + the negative-space lens), findings hand-re-verified
  then fixed + regression-pinned, BEFORE `git push`. "Draft PR" is not a review gate here
  (the #542→#544 lesson).
- **After every push: run the full local suite again** (the S2.5 lesson — it catches
  source-anchor breakage before CI reddens) and re-fetch `origin/0.2` before the next slice.
- Frontend slices ship **CONSERVATIVE + FLAGGED** per ruling Q6a: `node --check` + an
  invariant-test guard + defensive empty states + "browser-unverified, needs click-through"
  in the ledger row. No headless browser exists in your session.
- Record every slice in `docs/ledger/shipped.csv` (append-only, **binary-safe writes** — the
  file mixes LF and CRLF rows; never round-trip it through Python text mode or `csv.writer`
  whole-file rewrites) and end the session with a closeout entry + carry-over list.

## §2 The slice queue (ordered — instruments first, then backend snappiness, then UI tails)

### Slice 1 ⚠ — R5: `LOOP_SELFTESTS` backfill + registration enforcement

*Why first:* it hardens the loop that measures everything else, and it is cheap.
**Verified state (2026-07-14):** `src/monitoring/recursive_loop.py` registers **4** gates
(keyword, ir-eval, perception-eval, keyword-triage) while the tree holds **12**
`run_*_selftest` harnesses — the module's own "add a gate the moment a new harness ships"
comment has lapsed 8 times: `run_leads_selftest`, `run_conjunction_selftest`,
`run_skeleton_selftest`, `run_tor_throughput_selftest`, `run_non_article_selftest`,
`run_search_timing_selftest`, `run_power_profile_selftest`, `run_source_audit_selftest`
(re-verify the list with `grep -rhoE "def run_[a-z_]+_selftest" src/`).
**Build:** (a) backfill the 8 gates into `LOOP_SELFTESTS` (module path + fn name each; run
each once locally first — a gate that cannot pass must be investigated, never registered
red); (b) an **enforcement test** that discovers `run_*_selftest` functions from the tree
(AST or grep over `src/`) and asserts each is registered — so the discipline can never
silently lapse again; (c) confirm `recursive_loop_report()` stays read-only/deterministic
with 12 gates (bounded runtime — if any gate is slow, note it, don't drop it).
**Traps:** the existing membership contract test guards the *bundle*, not the registry —
extend, don't duplicate. Fable-5 verified the source-of-truth discovery must be the TREE,
not a hand-list (a hand-list is the same lapse one level up).
**Acceptance:** 12/12 gates green via `GET /api/diagnostics/recursive-loop`; the enforcement
test fails if a 13th harness ships unregistered (prove it with a temporary dummy, then remove).

### Slice 2 ⚠ — R1: the KPI snapshot (`src/monitoring/kpi.py` + `GET /api/diagnostics/kpi`)

**Spec (V1_PATHWAY §2.3 — the K1–K14 board IS the schema):** a read-only module emitting
versioned JSON (`schema: "oo-kpi-1"`) with one entry per K-metric:
`{id, name, value, method, n, as_of, source_endpoint, direction, target, verdict}` where
`direction ∈ {up, down, exact}` is ALWAYS present, `target` may be `"pending-ruling-V1-6"`,
and `verdict ∈ {green, red, not-measurable-here}` — **never a fabricated pass** (the S1
lesson: a metric whose instrument lacks data on this machine reports `not-measurable-here`,
e.g. K9/K10 without graded gold sets, K3 without a P0-validation report, K12 without the R3
flag inventory). **No composite anywhere** — no overall score/percentage/count-of-greens
beyond a plain listing. Reuse the existing instruments (engine_report, request-latency,
datediag, source-audit, i18n via subprocess is FORBIDDEN — read what is cheaply readable
in-process; a metric whose instrument is expensive reports the LAST persisted value with its
`as_of`, or `not-measurable-here`, never triggers a heavy crunch on GET).
**Wire:** route in `src/api/diagnostics.py` (plain `def`, threadpool — never `async def`
with sync DB work) + membership in `_all_diagnostics_members` (the single-source-of-truth
list at ~`diagnostics.py:2376`) + a `LOOP_SELFTESTS` gate (`run_kpi_selftest` proving the
mechanism on fixtures: direction present on every metric, no composite key by the
substring-walker convention, not-measurable honesty) — the Slice-1 enforcement test will
force this automatically.
**Traps:** the no-score KEY-walkers ban `score/ranking/rating/grade` as key substrings —
walk your own payload before pushing (the "degraded-contains-grade" lesson: statuses are
VALUES, never keys). Endpoint tests override `get_db`, never seed `SessionLocal`.
**Acceptance:** `GET /api/diagnostics/kpi` returns all 14 metrics with honest verdicts on an
empty dev corpus (mostly `not-measurable-here` — that IS the honest answer); rides the
bundle; gate green.

### Slice 3 — R2: the KPI differ (`scripts/kpi_diff.py`)

**Spec:** stdlib-only (the `analyze_keyword_log.py` pattern — runs without the app
installed): `python3 scripts/kpi_diff.py OLD.json NEW.json` → a cycle report listing, per
metric: `improved | regressed | unchanged | not-measurable` (computed from `direction` +
values; a metric missing from either side = `not-comparable`, said plainly). **Never a
blended verdict**; exit code 0 always (it reports, it does not gate — a regression is a
finding for the PLAN stage, not a CI failure). Include `--json` for machine consumption.
**Tests:** pure fixtures (two hand-written snapshots covering: improvement in a `down`
metric, regression in an `up` metric, exact-match, not-measurable on either side, missing
metric, schema-version mismatch fails loud).
**Acceptance:** hand-computed fixture deltas match; README-style usage block in the module
docstring; referenced from R4.

### Slice 4 — R4: `docs/process/IMPROVEMENT_CYCLE.md`

The standing cycle protocol (V1_PATHWAY §2.2 is the seed — expand, don't contradict):
the six stages with their concrete commands (which diagnostics job, where snapshots live,
how `kpi_diff` is run, the priority rule *red V1 bars > regressions > coverage > polish*),
the three roles (operator · planning session · CLI session), the safety rails (§2.6 —
pointer to the runbook as canonical), and the 15-minute gold-set grading step in Measure.
Link it from `docs/ROADMAP.md`'s doc-map table (one additive row) and from the V1_PATHWAY
§2.4 R4 bullet (edit the one line to "SHIPPED — see docs/process/IMPROVEMENT_CYCLE.md").
**Acceptance:** a future session could run a cycle from this doc alone.

### Slice 5 — wire `instrument_search` into the live search path

**Verified state:** `src/monitoring/search_timing.py:211` ships the `instrument_search`
seam + aggregation, but nothing calls it — `GET /api/diagnostics/search-timing` is
empty-honest forever. **Build:** wire the seam into the real search endpoint(s) — the
`/api/articles` FTS path and/or `search_ids`' API-level caller (find the narrowest single
chokepoint; do NOT instrument library internals called by non-search paths). Overhead must
be near-zero (the timer is injectable-clock, in-memory + bounded JSONL); it must never
change results or error behaviour (wrap in the seam's own try/except discipline).
**Traps:** the search handlers are plain `def` on the threadpool since S2.5 — keep them so;
grep the TEST tree for source anchors before touching handler signatures (the
`async def view_article` anchor lesson).
**Acceptance:** after a few TestClient searches in a test, `/api/diagnostics/search-timing`
reports non-empty phase aggregates with a measured dominant phase; zero result-diff on the
search contract tests.

### Slice 6 ⚠ — the maintained per-`Source` article counter (unblocks two carry-overs)

**Why:** ROADMAP P1.2/P1.3 carry-overs both need it — `GET /api/source_io/sources` and the
reader's per-source article count each run live `COUNT(*)`s per source.
**Build (mirror the `Keyword.mention_count` reference implementation end-to-end):**
additive nullable `Source.article_count` column + Alembic migration (**pick a genuinely
RANDOM 12-hex revision id and grep `migrations/versions/` for collisions; get the real head
from `python3 -m alembic heads`, never a regex scan** — the 2026-07-14 cycle-detected
lesson) + boot self-heal registration (the `SELF_HEALED_COLUMNS` convention) + maintenance
in `index_article`/the delete paths + a `reconcile_source_counters` pass mirroring
`reconcile_keyword_counters` (`src/analytics/store.py:558` area) wired into the S2.2 idle
maintenance + the counter **honesty envelope** (`{value, basis, as_of, method, n}`) on read
surfaces. Then convert `source_io/sources` + the reader's per-source count to read the
counter (envelope-disclosed), live-count fallback when NULL.
**Traps:** `test_no_model_drift` runs `alembic upgrade head` — run it locally (alembic works
in the sandbox). Bulk deletes bypass per-article maintenance — reconcile covers drift, and
the newsletter/pdf remove paths must call the backfill like `delete_imported_newsletters`
does for keywords. Never a `keyword_mentions→articles` style join for the fallback (codec
column-order trap); count on the indexed `Article.source_id`.
**Acceptance:** counter == live `GROUP BY` on a seeded fixture after ingest + delete +
reconcile; `source_io/sources` p95 no longer scales with corpus size (assert query count,
not wall time); reader page unchanged visually (server-rendered value swaps source).

### Slice 7 ⚠ — `diagnostics/keywords` pass-collapse (100–184 s in the field)

**Constraint (binding, from S2.5):** the maintainer FORBADE capping/deadlining the keyword
crunch — the fix is EFFICIENCY, never truncation. It already streams on a read-only WAL
snapshot in the threadpool. **Build:** collapse its multiple `keyword_mentions` passes into
one scan (it makes ~3 today — verify in `src/api/diagnostics.py` `/keywords`), serve the
corpus-wide totals from the maintained counters (envelope-disclosed) instead of recounting,
and add an OPTIONAL background-job variant reusing the `/all-job` template (POST starts,
GET status/download) so the operator can run it without holding an HTTP connection for 3
minutes — the sync GET stays (Desk lesson: never lose a tool).
**Traps:** `insights._cached` is DICT-ONLY — a scalar handed to it is a silent no-op (wrap
in a dict + pin a cache HIT with a store assertion). Byte-parity of the export payload is
the contract — the digest feeds the bundle; keep the schema identical and prove it with a
before/after fixture comparison, field by field (order-insensitive where sets tie — the
rollup-parity lesson).
**Acceptance:** identical export content on a fixture corpus; pass count over
`keyword_mentions` measurably reduced (assert via query counting on the session); job
variant cancellable + surfaced in `/api/jobs`.

### Slice 8 ⚠ — `debug-bundle` hardening (69 s in the field)

Per the S2 assessment: open the DB **read-only** for the bundle, widen `_safe()` so every
member is individually guarded (one failure writes `<name>.error.txt`, never aborts — the
all-diagnostics convention, partially present), and add a per-member time BUDGET that
records `{skipped: budget}` honestly instead of hanging the whole bundle on one slow member.
**Acceptance:** a member monkeypatched to raise AND one to sleep past budget both yield a
complete bundle with honest error/skip records; total wall time bounded on the fixture.

### Slice 9 — grouped-SQL rewrites: `monitoring/anomalies` + `commodity/correlation`

Both run per-item Python loops over per-day queries (verify current shape first). Rewrite
as ONE grouped query each (`GROUP BY` day/symbol), keeping outputs byte-identical
(fixture-pinned before refactoring — write the golden first). `EXPLAIN QUERY PLAN` on the
new queries: no bare `SCAN <table>` without `USING` (the covering-index classification
lesson).
**Acceptance:** goldens identical; query count collapses from O(days/symbols) to O(1).

### Slice 10 — `framing` response cap

The S2.4 note: `api/framing` materializes unbounded article text for the tonal comparison.
Add the established admission-cap treatment (`_resolve_corpus`-style bound + the existing
8000-char per-article cap verified still present), disclosing `{analyzed_n, total_n}` when
capped — a disclosed bound, never a silent truncation.
**Acceptance:** contract test with > cap articles shows the disclosure; under-cap behaviour
byte-identical.

### Slice 11 — power-profile live application

**Verified state:** `src/config/power_profiles.py` ships the knob table +
`resolve_effective` + the one wired knob (`fts_analysis_limit`). **Build:** apply the
remaining *safely-appliable* knobs at their read sites through `resolve_effective` (each
knob's consumer reads the profile-resolved value instead of its raw env default — enumerate
`PUBLISHED_KNOBS` and wire each consumer), and make a profile SWITCH take effect without
restart where the knob is read per-operation (document per knob: live vs next-restart —
honest, per the published-table transparency ruling). Do NOT invent Low/Max numbers — the
measured values stay GAMMA-gated (operator); the wiring uses the existing PROVISIONAL
values with their flags intact.
**Acceptance:** a test flips the profile and observes at least two knobs' effective values
change at their consumers; Optimized == current defaults byte-identical (the pinned test
stays green).

### Slice 12 ⚠ — Leads 2.0 surfacing (conservative + flagged; the §2 cores are shipped)

**Spec = PLANNING_2026-07-12 §2.1–2.5** (evidence chips · transparent ordering + user sort ·
major-floor · lifecycle/story-clustering · the Settings → Leads subtab). The cores
(`src/briefing/leads.py`: `sort_leads`/`explain_order`/`is_major`/clustering/lifecycle) are
built and tested; nothing calls them. **Build order (risk-managed, because wiring
`sort_leads` visibly reorders the flagship Home feed browser-unverified):**
(a) the **Settings → Leads subtab** (ooSubtabs grammar #18: per-producer toggles surfaced
from `recipes.py`, major-floor inputs, default-sort select, clustering on/off) storing to
settings; **the shipped default preserves TODAY'S ordering exactly** — the new ordering
modes activate only by user choice until a human click-through graduates them;
(b) evidence CHIPS on each card (n · distinct sources · the producer's own effect · newest
age — REAL numbers with #17 hover methods, never a composite) — additive render, low risk;
(c) the sort control on Home wired to `sort_leads` + the "why is this first?" hover from
`explain_order`; (d) story-clustering + lifecycle deltas rendered only when enabled.
i18n: new chrome strings via `t()` fallback; extend `test_ui_invariants` with a #-numbered
guard (chips render real fields; no score key; default ordering unchanged).
**Acceptance:** invariant test green; `node --check`; with settings untouched the briefing
payload + DOM order are byte-identical to today (pin it); ledger row flags
"browser-unverified".

### Slice 13 — Conjunction-Lens picker UI (conservative + flagged)

**Spec = PLANNING_2026-07-12 §1**; backend `GET /api/insights/corpus-algebra` is live.
**Build:** an N-keyword picker surface (the analysis window is the natural host — a small
"Combine keywords…" affordance near the Keywords subtab, or the omnibar `a∩b` syntax if
cheaper — pick ONE, judged by reuse of existing components) → calls corpus-algebra →
renders the set sizes (∩/∖/∪ with n each, the set expression as the corpus label per the
spec's transparency rule) → each set's "Open as corpus" via `openAnalysisForIds` (the
exact-set precedent). The deeper lens views (conditional trend, vocabulary contrast,
silence, lead/lag) are rendered from the endpoint's existing payload where present —
do NOT build new analytics; surface what §1's core computes.
**Acceptance:** invariant guard (picker wiring + endpoint URL + openAnalysisForIds path);
`node --check`; honest empty/1-keyword states; flagged browser-unverified.

## §3 Honesty rails (inherited, restated for the hot spots)

No composite scores (walk your payloads for banned key substrings) · method + caveat + n on
every new number · counters disclose their envelope/basis · `not-measurable-here` over a
proxy pass · degrade loudly (a failing bundle member is a recorded error, never a silent
gap) · caveats visible by default on any new UI · the three provenance classes never blend ·
no network calls anywhere in this session's scope (everything here is local/loopback).

## §4 Explicitly NOT yours (do not touch; note-and-skip if encountered)

- **R3 / `ui_walk` / the AppVM runner** — VM-gated (the runbook owns it).
- **R6 gold-set grading, the §8 triage batch/bench, GAMMA Low/Max measurement, live-corpus
  re-measurements, the D1 httpfs binaries, networked re-verification of the §4 vertical
  sources** — operator-gated.
- **Storage-plan phases + the incremental-vacuum idle pass** — ruling-gated (V1-7).
- **§3 fingerprint persistence** — gated on the triage cleanup (dormant stretch by ruling).
- **The §5 Tor ladder / segmented-download live wiring** — needs real multi-circuit Tor.
- **Versioned sources / verticals / discovery-funnel promotion frontier** — other briefs.
- Anything requiring a new heavy dependency, a network egress, or a consent-surface change.

## §5 Definition of done + closeout

Done = every §2 slice either SHIPPED (verified per its acceptance) or honestly parked with a
named blocker in the closeout. Closeout = one `shipped.csv` row per slice + a session
closeout row + a CLAUDE.md Open-queue entry (compact, pointer-style, additive — never touch
sibling lines) listing carry-overs, + the PR body's "Notes for reviewers" naming every
browser-unverified surface for the click-through list. If the maintainer merges mid-session,
re-fetch and rebase before the next slice.

## §6 Operator list produced by this session (expected)

The maintainer, after merging: run one **Measure** cycle (all-diagnostics job + the new KPI
snapshot on the live corpus) → keep the snapshot file → run it again after the next merge
wave → `kpi_diff` the two = **the first measured improvement cycle**. Then the standing
items: rule V1-6/V1-7, grade the gold sets, run the triage bench on the Ollama rig, and the
browser click-through of slices 12/13.
