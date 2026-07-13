# SESSION 2 of 6 — TIER 1: P1 snappiness remainder

**Mission:** finish the P1 board. "This app is useless if it is not used" — responsiveness
at 100 GB is adoption-critical for the journalists it serves. The acceptance bar is written:
every interactive endpoint p95 < ~500 ms at 100 GB · no UI action blocks > 1 s without
becoming a visible job · background work never freezes the UI. Read
`SESSIONS_2026-07-11_CONVENTIONS.md` §0 first, then **absorb S1's carry-overs**.

## Queue (top-down)

### S2.1 — A9: the write-gate hold riders — REPRODUCER-FIRST (Session A already investigated and DECLINED all three; start from that record)
The ledger's SESSION A PROGRESS entry is binding context: **"A9 riders INVESTIGATED, none
shipped (F14 non-reproducible: SessionLocal is autoflush=False; F10/F11 data-safety-
backup-path risk > LOW gain; F13 index_article-split risk vs GIL-marginal)."** So this is
NOT "fix three bugs" — it is: build the empirical gate-hold REPRODUCER for each claim (the
`write_gate.stats()["held"]` probe pattern from `tests/test_collect_batching.py`, which
already pins the fetch/extract-outside-gate property), and ship a change ONLY where a
reproducer demonstrates a real hold worth its risk:
- **F14:** presumed REFUTED (`SessionLocal` is `autoflush=False` — the claimed mechanism
  cannot fire). Close it with the reproducer-as-evidence unless one proves otherwise.
- **F13:** the reproducer decides whether the extraction-inside-gate window is real and
  material (Session A judged the split risk vs GIL-marginal — respect that judgment unless
  your measurement overturns it).
- **F10/F11:** backup-path edits carry recorded risk > gain; touch `stream_backup.py` ONLY
  with a demonstrated hold AND the full ZETA lessons (traversal guards, atomic finalize,
  test the REAL path — never a parameter-injected double).
Whatever the outcome, fix the stale `docs/ROADMAP.md` A9 line ("not reached" is wrong — it
was investigated & declined) in the same PR, and record the evidence in the ledger.

### S2.2 — A10: off-peak background maintenance
Counter-reconcile (86–104 s/pass) + orphan-prune slices already run deadline-budgeted with
resumable watermarks; schedule them for when the collector is IDLE (scheduler-owned; check
collector state, yield during passes). Ordering, never exclusion — the freshness gates stay;
disclosure (`complete:false` until a sweep finishes) stays.

### S2.3 — P1.3 completion: the `count(*)` sweep
Audit EVERY hot-path `count(*)`/full-count call site (grep + EXPLAIN; remember: `SCAN ...
USING COVERING INDEX` is healthy, a bare `SCAN` is the smell). Route corpus-scaled counts
through the maintained/reconciled counters with the honesty envelope
(`{value, basis, as_of}`); keep the reconcile pass as the drift net. The `/status`
data-aware cache shipped — verify and extend to the remaining sites.

### S2.4 — P1.2 residual: the guard-coverage SWEEP
`corpus-www` and `corpus-sentiment` are believed ALREADY guarded (both return through
`_deadlined` in `src/api/insights.py` — TTL cache + `run_heavy` cap/single-flight +
statement deadline) — confirm that in one look, then the real work: an Explore-agent sweep
of `src/api/` for ANY corpus-scaled read still outside `heavy.py`/`_deadlined`, guarding or
job-ifying what the sweep finds (mirror #628's pattern; a deadline overrun raises, never
returns truncated data as complete). Update the stale ROADMAP P1.2 wording with the sweep's
verdict.

### S2.5 — The measured residue
`diagnostics/keywords` (100–184 s) and `debug-bundle` (69 s): bound/cache/job-ify as fits
(diagnostics exports may prefer the job pattern à la `/all`; per-member deadlines + the
`_safe()` degrade convention — a diagnostic must degrade, never 500). `/api/articles`
p95 25 s: profile on a GAMMA synthetic corpus; it is FTS/index-backed and async — fix the
actual bottleneck found, don't guess.

### S2.6 — A14/P1.7: the 5 TB verify-before-trust review
A MEASURED design doc (`docs/design/5TB_ARCHITECTURE_REVIEW.md`): single-file SQLCipher
behaviour at scale — page-cache behaviour, VACUUM infeasibility + the incremental-vacuum
options, backup windows, the parity ceiling (DB-9) with the adaptive-volume-sizing options
S3 will implement. Drive it with GAMMA-tier synthetic measurements where the sandbox disk
allows; extrapolations labelled as extrapolations. This doc is S3's input — hand it over in
the carry-over section.

### S2.7 — Snappy-bar instrumentation check
Verify the latency reservoir actually reports the p95s the acceptance bar is written
against (per-endpoint, exportable in the perf report). Close any gap so the maintainer's
next field export can SHOW pass/fail against the bar rather than anecdotes.

## Explicitly NOT yours
D1/D2/D3 columnar (S3) · product/UX (S4) · rulings builds (S5) · backlog features (S6) ·
anything networked (conventions §4).

## Closeout
Ledger rows + ROADMAP status flips + the CARRY-OVER section for S3 (include the S2.6 doc
pointer explicitly).
