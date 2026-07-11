# SESSION 1 of 6 — TIER 0: the v0.2.0 Release Kit

**Mission:** the v0.2.0 tag is held on the maintainer's LIVE-corpus validation of the P0
data-safety set. You cannot run that corpus — so make the validation **push-button**: one
in-app job, one runbook, one pass/fail report, plus everything tag-day needs prepared.
Data safety before features: this session exists so a journalist's corpus can never be lost
to an unproven backup path. Read `SESSIONS_2026-07-11_CONVENTIONS.md` §0 first.

## Queue (top-down; spawn sub-agents freely)

### S1.1 — Post-wave full-suite health check (do this FIRST)
The A+B wave (#614–#630) merged as many parallel PRs; per-PR CI misses cross-test pollution
(the #577 lesson: order-dependent failures only collide in the combined run). Build the
py3.13 venv, run the FULL suite on the `0.2` tip, fix-forward anything red (each fix its own
small PR with the failing case pinned). Also run `ruff`, the mypy ratchet, and
`scripts/i18n_report.py --min 100` once each.

### S1.2 — The P0 live-validation JOB (the centerpiece)
One cancellable, task-manager-visible job (`POST /api/diagnostics/p0-validation` + status/
cancel + a Settings → Diagnostics panel button) that runs the P0 acceptance checks against
the OPERATOR'S OWN live corpus and emits ONE exportable JSON+readable report:
- **P0.1 backup:** drive the `oo-volumes-2` streaming backup to a caller-supplied dest dir,
  sampling process RSS through the run (psutil, like collect_perf) → report peak RSS,
  duration, volume count, incremental-reuse stats. Then **verify** (signed manifest + every
  volume checksum — the existing verify job) → report.
- **P0.2 restore:** a STAGED round-trip probe — restore into a throwaway staging dir +
  dry-run merge preview ONLY (never touch the live corpus; reuse the existing preflight/
  preview machinery) → report bytes, duration, peak RSS.
- **P0.4 unlock:** read the merged per-phase unlock instrumentation (#596) from the last
  boot → report phase timings vs the <2 s bar; include a "how to time your next cold boot"
  instruction in the report when instrumentation shows a stale boot.
- **P0.3 collector:** read the collect_perf RSS curves + memory-guard state over the recent
  window → report flat-vs-climbing RSS, guard trips, pass recycling counts.
- **The verdict block:** per-check `pass | fail | not-measurable-here (reason)` against the
  written acceptance bars — measurements only, NO composite score, NEVER a fabricated pass;
  a check that cannot run reports WHY. The report is **backup-engine-version/format-stamped**
  (so a later engine change — e.g. S3's adaptive volume sizing — makes a stale validation
  detectable). Wire it as a debug-bundle member too.
Design constraints: heavy work off the event loop (job thread), writer-gate discipline for
the backup window (it already owns this), bounded staging with disk preflight, honest
cleanup of the staging dir on cancel/finish.

### S1.3 — The operator RUNBOOK
`docs/product/P0_VALIDATION_RUNBOOK.md`: the exact click-by-click operator procedure —
pre-flight (disk space, update install, clean shutdown first), run the S1.2 job, the cold-boot
unlock timing step, the multi-day collector soak, what PASS looks like per check, what to
export back if anything fails. Link it from the Settings panel hint and the ROADMAP Tier-0
rows. Keep it in the app's honest voice (state what each step can and cannot prove).

### S1.4 — Tag-day preparation (prepare, never execute)
(a) Refresh `docs/CHANGES.md`'s 0.2.0 section from the ledger so it is release-notes-ready
(the A+B wave items belong in it; keep the "tag awaits live validation" line — the tag stays
HELD). (b) Verify `release.yml` still gates correctly (full-suite job, tag==pyproject check)
against the current tree. (c) Add a short TAG-DAY CHECKLIST to the runbook: validation report
green → dispatch CI + watch to completion at the SHA → tag `v0.2.0` → verify release assets +
SHA256SUMS. (d) Confirm `README`/`CONTRIBUTING` version prose needs no change at tag time.

### S1.5 — Validation-kit hardening sweep
Adversarial pass over your own S1.2 job with the data-safety lenses (this touches the backup
path — the most consequence-laden code in the repo): the job must be UNABLE to corrupt or
delete live data under any input (staging-only writes, traversal-guarded paths per the ZETA
lessons, atomicity where it writes reports), and a crashed/cancelled validation leaves no
half-state that a later backup could mistake for real. Tests must drive the **REAL
live-corpus source path** (monkeypatch `live_db_path`, never a `corpus_source` parameter
double — the ZETA (c) lesson: an injected double bypasses exactly the code being validated).
Pin these as tests.

## Explicitly NOT yours
The live run itself, the tag push, click-throughs (operator). Tiers 1–5 (sessions 2–6).

## Closeout
Ledger row + closeout PR with the CARRY-OVER section for S2 (conventions §5). In the
closeout, list the exact operator sequence: "merge → run the runbook → send the report →
tag" — that report is the artifact the whole program is gated on.
