# Autonomous Session Brief — SESSION A: "Scale & Data-Safety" (backend)

**Date:** 2026-07-10 · **Authority:** maintainer ruled "1a 2a 3a 4a" (full autonomy, incl. P0
engineering vs the synthetic harness and vendored-binary attempts) + the standing "always
choose autonomously / I don't want to be asked anything" rulings (2026-06-15 / 2026-06-21).
**You run in PARALLEL with Session B** (brief: `AUTONOMOUS_SESSION_BRIEF_2026-07-10_B_PRODUCT_UX.md`).

## 0. Read first, non-negotiable

1. **Read `CLAUDE.md` in full** (the protocol demands it — it is the binding ledger: rulings,
   invariants, lessons; everything below defers to it on conflict).
2. Read `docs/ROADMAP.md` (the board) and `docs/product/SCALE_ROADMAP.md` (your deep detail).
3. This brief is your work queue + territory contract. Execute top-down; skip only with a
   recorded reason in your PR/ledger notes. NEVER ask the maintainer anything — pick the most
   honest, conservative default and record the decision.

## 1. Territory contract (collision-proofing with Session B — HARD RULES)

**YOU OWN (edit freely):** `src/scheduler/**` · `src/backup/**` · `src/database/**` ·
`src/monitoring/**` · `src/safety/**` · `src/testing/**` ·
`src/analytics/{rollup_serve,map_serve,columnar,readmodel,corpus_epoch}.py` and the *serving*
paths of `queries.py` · `migrations/**` · `install.sh`/`scripts/launch.sh` · your own tests.

**FORBIDDEN (Session B's territory — do not edit, at all):** `src/static/**` (ALL frontend
JS/CSS/HTML + locales) · `src/analytics/{extract,dateextract,datediag,families,selftest,
engine_report}.py` and stoplist code (`src/services/stopwords.py`) · `src/signals/**` ·
`src/stats/**` · `configs/` feed/stopword/baseline data files. If a fix seems to require a
frontend change, ship the backend + tests and record "UI wiring → Session B" in the PR body.

**SHARED EDGE FILES (both sessions may touch — keep edits surgical, function-scoped, and
`git fetch origin 0.2` + rebase immediately before every push):** `src/api/insights.py`,
`src/api/diagnostics.py`, `src/api/main.py` wiring lines.

**SHARED APPEND-TARGETS (additive merges ONLY — never revert the other session's lines; the
PR #548 stale-base revert incident is the cautionary tale):** `CLAUDE.md`,
`docs/ledger/shipped.csv`, `docs/ledger/SHIPPED_LOG.md`, `docs/ROADMAP.md`,
`configs/external_artifacts.yml`, `tests/test_repo_invariants.py` (append new tests, never
reorder).

**Branch prefix:** name every branch `claude/a-<slug>` so A/B branches never collide.

## 2. Working mode

- Small **draft PRs onto `0.2`**, each cut from a **freshly fetched** `origin/0.2`
  (`git fetch origin 0.2 && git checkout -B claude/a-<slug> origin/0.2`; verify
  `git show origin/0.2:pyproject.toml` reads `0.2.0` before trusting the base). The
  maintainer fast-merges; after your PR merges, re-fetch before cutting the next.
- **Verify-before-push is a hard gate** (lesson #542→#544): parallel adversarial skeptic
  agents (distinct lenses; for anything touching parsing/routing include the NEGATIVE-SPACE
  lens — generate should-be-empty inputs) must COMPLETE, and their reproducers be pinned as
  tests, BEFORE `git push`. "Draft PR" is not a review gate here.
- **Test environment:** try a py3.13 venv first (`python3.13 -m venv .venv && .venv/bin/pip
  install -e ".[analysis,dev]"` — this empirically worked in-repo 2026-06-25 and runs the
  FULL suite + the mypy ratchet locally). If only py3.11 exists, use the ledger's CI-only
  lessons: `pip install mypy==2.1.0` + per-file mypy, standalone pure-module repros, `pip
  install bleach sqlalchemy pytest` for ORM tests; `cryptography` won't install there — those
  tests run in CI. Never claim green you didn't see.
- **After every fast-merged wave, run a FULL-suite health check** (lesson 2026-07-06:
  per-PR CI misses cross-test pollution; two parallel sessions make this MORE likely).
  NEVER switch git branches while a suite is running (lesson 2026-07-09).
- Gates on every PR: `pytest -q` green (or honest CI-only note) · mypy ratchet ≤ baseline ·
  `ruff check --select F,B` · bandit `# nosec` conventions for any dynamic SQL · endpoint
  tests override `get_db`, never seed `SessionLocal` · no positive route asserts against the
  shared `app.routes` singleton.
- Ledger discipline per shipped item: a `docs/ledger/shipped.csv` ROW; a `SHIPPED_LOG.md`
  entry + a Session-rituals lesson only if there's a reusable lesson; update
  `docs/ROADMAP.md` statuses you change; record any new decision in `CLAUDE.md` same turn.
- Honesty non-negotiables apply in full (no scores, visible caveats, degrade loudly, zero
  fabricated data/security, airplane socket guarantee, never silently downgrade transport).

## 3. Work queue (priority order — get through as much as possible)

### A1 — P0.4 UNLOCK AT SCALE (the standing v0.2 blocker; ruled 1a: engineer the fix vs the synthetic harness)
The facts: unlock was 60 s @ 2.28 GB, then **981 s → 1,645 s (27.4 min)** on consecutive
boots at ~11.7 GB db / ~130 GB data-dir; the one-time-migration hypothesis is REFUTED (cost
recurs and grows; schema stamp did not advance). Prime suspects: (i) **WAL recovery after
unclean shutdown** (free experiment: clean in-app Shutdown → time the next unlock), (ii)
**corpus-scaled synchronous init_db work**. Per-phase instrumentation is already merged
(#596 timing + wal-bytes-before-open; #599 elapsed-clock UI).
**Do:** reproduce with the GAMMA G2 unlock-wall benchmark on a synthetic ~12 GB encrypted
corpus (`src/testing/` + `scripts/`; P0.5 shipped #601) → name the phase with measurements →
fix it (candidates: WAL checkpoint-on-shutdown hygiene, moving corpus-scaled work off the
unlock path into the deferred/backgrounded startup — the PR #550 pattern, incremental/
budgeted recovery) → prove before/after on the benchmark → pin as tests.
**Acceptance:** steady-state unlock < 2 s on the synthetic tier; any long phase visible +
honest in the UI status (backend fields only — UI text is B's); the maintainer's live run
stays the FINAL validation (never claim P0.4 closed — claim "fixed on synthetic, awaiting
live validation").

### A2 — P1.1 death-spiral structural fix (marked IN FLIGHT — read the tree first, don't duplicate)
Server-side DEADLINES on heavy endpoints + a global request CONCURRENCY CAP + single-flight
for identical in-flight computations. Field signature: one `trending-windows` call in-flight
217 s while requests stacked; loop lagging 24.8 s. Check what the ALPHA work already landed
(`git log --oneline | head -50`, grep for deadline/single-flight/backpressure tests) and
finish the remainder. Degrade loudly (503/timeout with honest reason), never hang.

### A3 — P1.2 job-ify the heavy synchronous handlers
`enrich-source-types` 8.5 min · `governments/load-standard` 2.9 min · `keyword-tags/backfill`
1 min · `server-locations` 45 s · `corpus-www` 28 s · `corpus-sentiment` 18 s · `top` 20 s.
Any handler that can exceed ~1 s at scale becomes a visible, cancellable task-manager job
(the established manager pattern: NewsletterImportManager/ReindexJobManager) or at minimum
runs via `run_in_threadpool` with a deadline (the async-def-blocks-the-loop lesson). Backend
+ `/api/jobs` surfacing only; UI buttons are B's.

### A4 — P1.3 `count(*)` from maintained counters
`SELECT count(*) FROM keyword_mentions` measured 724 ms × 172 calls = 124 s. Route every
hot-path count through the maintained/reconciled counters (honesty envelope: value + basis +
as_of), keeping the reconcile pass as the drift-net.

### A5 — Heavy-endpoint sweep (deadline + cache/job)
`insights/lunar-correlation` (57–142 s) · `diagnostics/keywords` (100–184 s) ·
`debug-bundle` (69 s) · `integrity` (62 s) · `briefing` (30–37 s) · `/api/articles` p95 25 s.
Apply the established patterns (#589 memo-cache bind-aware; #600 job-ify; statement
deadlines; the EXPLAIN-QUERY-PLAN `USING` classification lesson). **EXCLUDE
`signals/flood`/`signals/bury`** — Session B owns those (correctness rework + they'll apply
your patterns).

### A6 — Backup verify completeness (backend)
The volumes verify job exists (`POST /api/backup/v2/volumes/verify`). The field-test gap: no
standalone verify covering **the folder-backup manifest** too. Ship the folder-manifest
verify (checksums, honest per-file report, job-ified if slow). UI wiring is B's — publish
the endpoint contract clearly in the PR body.

### A7 — Corpus-epoch → restore-merge wiring (DB-7)
`bump_corpus_epoch` is wired into reindex/prune but NOT the restore-merge (`src/backup`) —
the one residual mutator. Wire it (over-bumping is harmless); test that a restore-merge
invalidates the rollup serves.

### A8 — Alembic stamp self-heal (DB-8)
The live DB stamp lags the code head while self-heal keeps the schema in sync. Make the
boot self-heal ADVANCE the stamp once schema parity is verified (or ship a guarded
`stamp-to-head` maintenance step), so the next real migration and cross-version restore
aren't operating on a lying stamp. Test both directions (behind-stamp heals; a genuinely
missing column still migrates).

### A9 — Write-gate hold riders (post-merge audit F13 / F10 / F11 / F14)
F13: the batched collector flush holds the gate across per-article keyword+WWW EXTRACTION —
extract first, then take the gate for the write. F10/F11: `_drain_wal` gate/pool ordering +
gate held across `_corpus_facts` full scans. F14: markets `run_rule` dirty session holds the
gate across a CSV fetch — commit/rollback before the loop. Each with a gate-hold regression
test (the `write_gate.stats()["held"]` probe pattern from tests/test_collect_batching.py).

### A10 — P1.12 off-peak maintenance scheduling
The deadline/watermark half shipped; add scheduling so counter-reconcile + prune slices run
when the collector is idle (scheduler-owned; ordering never exclusion).

### A11 — DispVM durability: opt-in persistent data_dir
The disposable-VM crash vaporized a ~60K-article corpus. Ship: an easy opt-in persistent
`data_dir` (env/config + install.sh support for a bind-mounted/external path, validated +
preflighted), an honest one-time note when the app detects it is running on a likely-
ephemeral root (detection must be honest — if you can't detect reliably, document instead of
guessing). Never "stop using DispVMs" messaging.

### A12 — Data-folder composition diagnostic (DB-5, the ~120 GB mystery)
`db_bytes` 11.7 GB vs ~130 GB folder. Ship a read-only `du`-style breakdown of `data_dir()`
(top-level dirs + the known members: db/-wal/-shm, wiki_dumps, osm_regions, staging,
exports) as a diagnostics endpoint + debug-bundle member, so the next field export names
the 120 GB. Flag any plaintext staging leftovers LOUDLY (a would-be at-rest violation).

### A13 — httpfs crypto-extension bundling attempt → D1 persisted encrypted columnar store (ruled 3a: cleared, incl. binaries)
The blocker: DuckDB refuses an *authenticated* encrypted write without the OpenSSL `httpfs`
extension. Attempt: fetch the official per-OS/arch `httpfs` extension binaries for the
EXACT pinned DuckDB version (extensions.duckdb.org; linux_amd64 + osx_amd64/arm64 +
windows_amd64), sha256-pin them, registry entries (`configs/external_artifacts.yml` — the
duckdb-crypto floor must equal the pyproject `[columnar]` floor, test-enforced),
verify-before-LOAD, keep the empirical encryption gate (sentinel-absent / won't-open-
without-key / opens-with-key). Repo bundling is acceptable (a few MB each, far under the
100 MB limit) — but if the network/proxy blocks the fetch or attestation can't be verified,
STOP and record the blocker honestly (never fabricate a checksum; the in-memory fallback
stays). If the binaries land: build **D1 persisted encrypted store** per
`docs/design/PERSISTED_DUCKDB_HTTPFS.md`, then **D2 `keyword_daily` persisted** + **D3
incremental epoch-gated refresh** per `docs/design/SCALING_DERIVED_LAYER_1000X.md` (the
delete-then-reinsert epoch trap lesson is binding).

### A14 — (if time) P1.7 5 TB verify-before-trust review
A measured design doc: single-file SQLCipher behaviour at the 5 TB tier (page cache, VACUUM,
backup windows, parity ceiling F6 → adaptive volume sizing), driven by GAMMA-tier synthetic
measurements, feeding the P0.1 design. Design + measurements only; no risky code.

## 4. Definition of done (per item and for the session)

Tests green (full suite where runnable, CI-noted where not) · skeptics completed pre-push ·
draft PR opened with an honest status (shipped / fixed-on-synthetic-awaiting-live /
blocked-with-reason) · ledger row + roadmap status updated · no forbidden-territory edits ·
shared files merged additively. End the session with a summary PR comment listing what
shipped, what's blocked and why, and what the maintainer's live-validation checklist is.
