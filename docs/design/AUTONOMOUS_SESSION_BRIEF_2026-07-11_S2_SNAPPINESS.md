# SESSION 2 of 6 — TIER 1: P1 snappiness remainder

**Mission:** finish the P1 board. "This app is useless if it is not used" — responsiveness
at 100 GB is adoption-critical for the journalists it serves. The acceptance bar is written:
every interactive endpoint p95 < ~500 ms at 100 GB · no UI action blocks > 1 s without
becoming a visible job · background work never freezes the UI. Read
`SESSIONS_2026-07-11_CONVENTIONS.md` §0 first, then **absorb S1's carry-overs**.

## Queue (top-down)

### S2.1 — A9: the write-gate hold riders (F13 · F10/F11 · F14)
The single-writer gate is the app's scarcest resource; holding it across non-DB work is the
field's 438-s-wait signature. Fix each with a gate-hold regression test (the empirical
`write_gate.stats()["held"] is False` probe pattern from `tests/test_collect_batching.py`):
- **F13 (MED):** the batched collector flush holds the gate across per-article keyword+WWW
  **extraction**, not just the write — extract first, then take the gate for the write only.
- **F10/F11 (LOW):** backup's `_drain_wal` takes the gate then a pool connection (inverted
  order), and the gate is held across `_corpus_facts`' full COUNT+scan — reorder/move out.
- **F14 (LOW):** markets `run_rule` enters its CSV fetch with a dirty session, so autoflush
  hands the gate to the network wait — commit/rollback before the loop (the ETA P1.8 lesson).
Backup-path edits are data-safety-critical: the ZETA lessons (traversal guards, atomic
finalize, test the REAL path not a parameter-injected double) are binding.

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

### S2.4 — P1.2 residual: the last unguarded heavy reads
`corpus-www` (28 s) and `corpus-sentiment` (18 s) are plain `def` handlers — verify whether
they run under `guarded_read`; guard or job-ify what isn't (mirror #628's pattern: deadline +
cap + param-qualified single-flight; a deadline overrun raises, never returns truncated data
as complete). Then sweep for any OTHER heavy read that slipped the net (an Explore agent over
`src/api/` looking for corpus-scaled queries outside `heavy.py`).

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
