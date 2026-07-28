# Execution Plan — 2026-07-26 Field Remarks + Hardware Diagnostics Fixes

**Who this is for:** ONE autonomous Sonnet 5 CLI session with ultracode (multi-agent
orchestration) enabled. This doc is the OPERATING MANUAL — the router, sequencing, risk
classes, parallelization map, and verification gates. The full fix specifications (root
causes, exact code, exact tests) live in the two companion investigation docs and are NOT
repeated here:

- [`AUTONOMOUS_SESSION_BRIEF_2026-07-26_HARDWARE_DIAGNOSTICS_COMPARISON.md`](AUTONOMOUS_SESSION_BRIEF_2026-07-26_HARDWARE_DIAGNOSTICS_COMPARISON.md)
  — read §1.1, §2.1, §6.1, §7.1, §8.1, §9.1 (each is a complete, code-cited spec).
- [`AUTONOMOUS_SESSION_BRIEF_2026-07-26_FIELD_REMARKS.md`](AUTONOMOUS_SESSION_BRIEF_2026-07-26_FIELD_REMARKS.md)
  — read items 1–3, 6, 7 (each carries its fix shape + exact proposed tests).

Read the spec section for a slice IN FULL before building it. Do not re-derive root causes
— they are already verified against `main` with file:line citations. Do re-verify the
ANCHORS (staleness guard, §0.3 below) — this repo merges fast and citations go stale.

---

## §0 Working mode (binding)

**0.1 Branches + PRs.** Cut every branch from a FRESHLY-fetched `origin/main`
(`git fetch origin main && git checkout -B claude/oos-fd26-<slice> origin/main` — the
stale-base revert incident is a named lesson in CLAUDE.md; never skip the fetch). One
DRAFT PR per PR-group (§2). The maintainer merges everything; nothing self-merges.
Commit messages: no backticks inside `git commit -m` heredocs.

**0.2 Skeptics-before-push.** Every slice marked ⚠ in §2 must pass an adversarial
skeptic fan-out (parallel subagents, DISTINCT lenses, listed per-slice in §3) that
COMPLETES before `git push` — "draft PR" is not a review gate here (the #542→#544
lesson). Feed skeptics the DIFF + surrounding facts INLINE, never "go read the 1,400-line
file" (the context-overflow lesson). Hand-re-verify every skeptic finding before acting
on it (the 06-audit false-positive lesson). Pin every real finding as a regression test.

**0.3 Staleness guard.** Before building ANY slice, a recon subagent verifies its spec's
anchors against the live tree: the cited functions still exist at (approximately) the
cited lines, and — critically — the fix hasn't ALREADY landed (this repo's briefs have
repeatedly found "open" items already shipped; the power-profile table value in §W6 is
the in-doc example: half the finding self-resolved in commit `4c20b23` before the doc was
even written). A shifted line number is fine — adjust and proceed. A vanished/changed
function means STOP on that slice, record the discrepancy, and re-scope from the live
code, never from the doc's prose.

**0.4 Full-suite discipline.** The in-repo py3.13 `.venv` runs the FULL suite locally.
Run it before every push — per-file test runs miss cross-test pollution (the #577
lesson), and a passing subset is not evidence. Known environmental failures in a sandbox
(PackageNotFoundError version tests, sqlcipher3-absent skips) are recorded in CLAUDE.md —
do not chase them; anything ELSE red is yours.

**0.5 Ledger closeout.** Per CLAUDE.md's protocol: each shipped slice = a
`docs/ledger/shipped.csv` row; a reusable lesson also goes verbatim into
`docs/ledger/SHIPPED_LOG.md` + the CLAUDE.md Lessons list. Update the two investigation
docs' status lines (strike ✅ what shipped). Never revert sibling-session lines in shared
append-targets; after any merge, `grep -n '^<<<<<<<\|^=======$\|^>>>>>>>' CLAUDE.md
docs/ledger/shipped.csv` must return nothing.

**0.6 Honesty rails (project non-negotiables, enforced by existing tests).** No composite
scores; no score-substring dict KEYS (`grade` ⊂ `degraded` trap); every disclosed number
from a real method; degrade loudly never silently; `basis` blocks are disclosures, not
scores; a cache/rollup must fall back to the live path on any miss, never serve wrong
data.

---

## §1 Scope fence

**BUILD (this session):** the eight slices in §2.

**DO NOT BUILD — explicitly out of scope:**
- Field-remarks **item 9** (qualification judging disabled candidates): needs the
  maintainer's (a)/(b) ruling first. Do not default it silently.
- Field-remarks **items 4–5** (the Playwright `UiWalkDriver` untranslated-text detector):
  a separate, larger build; only the Phase-1 keying fixes ride along (F1, §2).
- The **Mistral-7B 94.7%-hallucination finding**: a maintainer model decision, not code.
- Hardware doc **§9's cold-boot-unlock growth + keyword-counter-drift** findings: flagged
  for their own dedicated investigation; no spec exists — do not improvise one.
- The **`/v1/models` 404 probe backoff**: flagged, no spec — skip.
- The **300s diagnostics-deadline scaling** question: flagged, needs scoping — skip.
- Anything browser-verify-gated beyond conservative+flagged (fork-3/Q6a): the F1 frontend
  ships `node --check`-clean + invariant-guarded + labeled "browser-unverified, needs
  click-through"; never claim it verified.

---

## §2 Slice table

| ID | Slice | Spec | Files touched | Risk | PR-group |
|----|-------|------|---------------|------|----------|
| W3 | `sources.last_crawled_at` index self-heal | HW §6.1 | `src/database/maintenance.py` (+1 test file) | LOW | **PR-A** |
| W4 | Logger-level noise filter (htmldate.meta + trafilatura.metadata) | HW §8.1 | `src/monitoring/errorlog.py`, `tests/test_errorlog_summary.py` | LOW | **PR-A** |
| W6 | Power-profile live-setting overrides | HW §7.1 | `src/config/power_profiles.py`, `src/api/diagnostics.py`, `tests/test_power_profiles.py` | LOW | **PR-A** |
| W2 | `/api/database/countries` in-memory rollup | HW §2.1 | `src/api/database.py`, new `src/analytics/source_country_rollup.py`, `src/scheduler/maintenance.py`, tests | ⚠ CORRECTNESS (byte-parity) | **PR-B** |
| W5 | Pre-restore snapshot age sweep | HW §9.1 | `src/backup/merge.py`, `src/scheduler/maintenance.py`, `src/api/main.py`, tests | ⚠⚠ DATA-SAFETY (deletes files) | **PR-C** |
| W1 | WAL long-reader restructure (+ optional WalGuard) | HW §1.1 | `src/briefing/registry.py`, `src/api/insights.py`, `src/analytics/columnar.py`, `src/analytics/rollup_serve.py`, (`src/scheduler/hygiene.py`), tests | ⚠⚠ HOT-PATH (transactional semantics) | **PR-D** |
| F2 | AI-job retry-with-backoff + paused≠done (triage, source-tags, perception-extract) | FR items 6–7 | `src/ai_layer/triage_job.py`, `src/ai_layer/source_tags_job.py`, `src/ai_layer/perception_extract_job.py`, `src/api/jobs.py`, tests | ⚠ CORRECTNESS (state semantics) | **PR-E** |
| F1 | AI-job toggle UI + `active_model()` fallback + collapsed descriptions | FR items 1–3 | `src/api/diagnostics.py` (3 Pydantic bodies), `src/static/app.js`, `src/static/index.html`, invariant test | MED (frontend browser-gated) | **PR-E** |

**File-collision map (drives sequencing; parallel worktrees for everything else):**
- `src/scheduler/maintenance.py`: W2 AND W5 both add a step to `run_idle_maintenance`,
  and both add wiring tests to `tests/test_offpeak_maintenance.py`. **Land PR-B before
  starting PR-C's wiring, or rebase PR-C on PR-B's branch** — never edit that function in
  two concurrent worktrees.
- `src/api/diagnostics.py`: W6 (the `/power-profile` endpoint, ~line 1399) AND F1 (the
  three `*RunBody` models, ~lines 3959/4089/4235) touch the same file in distinct
  regions. Parallel worktrees will merge-conflict trivially — either sequence PR-A before
  PR-E or accept a mechanical rebase.
- Everything else is pairwise disjoint and safe for concurrent worktrees.

---

## §3 Phases + orchestration map (ultracode)

**Phase 0 — recon fan-out (parallel, read-only, ~30 min).** One subagent per slice
verifies the spec's anchors against live `main` (§0.3) and reports
`ok | shifted(details) | already-shipped | diverged(details)`. A second, single subagent
re-runs the collision map (§2) against the live tree. Nothing builds until Phase 0's
report is in. Any `already-shipped` slice: verify-and-record, never rebuild.

**Phase 1 — PR-A, the low-risk trio (one worktree, serial within, ~fast).** W3 → W4 → W6
in one branch. All three are single-function-scale edits with tests specified verbatim in
their specs. Inline skeptic pass (one agent, correctness lens) suffices — no full matrix.
Gate: full suite + §5 gates. Push, draft PR.

**Phase 2 — PR-B (W2) and PR-C (W5), sequenced (maintenance.py collision).**
- **W2** first. Build exactly to spec §2.1 (extract `_live_sources_by_country` verbatim →
  the rollup module → wire → serve-with-fallback). MANDATORY skeptic fan-out before push,
  3 lenses in parallel: (1) *byte-parity* — served payload must equal the live compute
  including `countries[]` ordering and `top_tags` truncation ties; (2) *fallback-safety* —
  every miss/cold/bind-mismatch/exception path returns `None` and the caller degrades to
  the unchanged live path; (3) *negative-space* — a `"(none)"`-bucket-only corpus, an
  empty `sources` table, a 249-country corpus. The spec's test E ("no SQL against sources
  when warm") is the structural proof — write it first.
- **W5** second (rebase on PR-B if unmerged). This slice DELETES files —
  the project's backup bar is "entirely reliable or it doesn't ship." MANDATORY full
  skeptic matrix, 4 lenses in parallel: (1) *data-loss* — can any input/config/timing
  make it delete a snapshot whose restore is still running? (attack the
  `active_staging` registration window: is the guard registered BEFORE the first moment
  the sweep could see the file?); (2) *race/concurrency* — idle-maintenance firing
  mid-commit on the ordinary REST path (the spec's own stated hazard); (3)
  *negative-space* — hand-renamed files, malformed timestamps, a future-dated timestamp,
  `pre-restore-` prefix collisions; (4) *config-abuse* — `max_age_hours=0`, negative,
  NaN, huge. The spec's test 3 (old-but-active never swept) is the mechanism proof —
  stash-verify it (reproduce the unguarded behavior, watch the test fail, restore the
  fix).

**Phase 3 — PR-D (W1), the big one. Build LAST among the W-slices** — highest blast
radius, benefits from everything else being merged and green first.
- **Probe-first, before writing the fix:** the spec's step 3 (commit mid-`fetchmany`)
  depends on an empirical question — does a held SELECT cursor survive `session.commit()`
  on this connection? Write the probe as a standalone test FIRST. If yes → periodic-commit
  path; if no → the keyset-cursor path (`id > last-seen` per chunk). Never assert the
  answer from docs (the P2.4 discipline).
- Then the regression test proving the root cause (spec's test 1) — watch it fail on
  unpatched `main` — then the fix, then tests 2–4.
- MANDATORY skeptic fan-out, 4 lenses in parallel: (1) *transactional semantics* —
  `run_all` producers and `warm_cache` steps are not all pure reads (`evaluate_watches`
  writes bookkeeping); a mid-loop `session.commit()` changes atomicity — enumerate every
  write inside the loop and confirm each is safe to commit early (and that no
  half-written producer state becomes visible); (2) *write-gate/autoflush* — the repo's
  autoflush-hands-the-gate-to-a-read lesson: does any new commit point acquire/hold the
  writer gate differently? (3) *parity/double-count* — the delete-then-reinsert lesson:
  run `keyword_daily_parity` with a tiny batch_size forcing many mid-stream commits
  (spec's test 3); (4) *S4.1-preservation* — the fix must not reintroduce blocking
  between the briefing refresh and the next pass (assert the duty-cycle tests still
  pass unchanged).
- The `WalGuard` watchdog is OPTIONAL — build it only if the core restructure lands
  clean with time to spare; it is defense-in-depth, never the fix.

**Phase 4 — PR-E (F2 backend + F1).** One branch (the field-remarks doc's own
sequencing: same panels, same job files).
- **F2 first** (backend): port the langdetect retry template (constants + shape from
  `src/api/ai.py` / `src/ai_layer/langdetect_llm.py`) into all three progressive jobs;
  catch `LLMError` alongside `LLMUnavailable`; un-conflate paused/done across
  `/status`+`/last`+`/api/jobs`. NOTE: `tests/test_triage_and_source_tags_endpoints.py:
  207-270` currently PINS the paused==done conflation as intentional — that test must be
  UPDATED to the new honest contract, not deleted (state the change in the PR body).
  Skeptic fan-out, 2 lenses: (1) *retry-semantics* — a genuine cancel is never retried; a
  permanent outage still terminates loudly within the failure budget; (2) *state-machine*
  — every (paused, done, error, running) × (/status, /last, /api/jobs) cell agrees.
- **F1 second**: backend `model: str | None = None` + `active_model()` fallback on the
  three bodies (+ the fallback tests per the FR doc); then the frontend — ONE shared
  toggle helper on the `pollLangDetect`/`_paintLangDetectButton` pattern, wired to all
  three panels, descriptions collapsed via `<details class="adv-collect">`; extend
  `test_ui_invariants` with the source-scoped "no `btn.disabled` in these handlers"
  guard (scoped per function body — never a whole-file substring, the false-pass
  lesson). Frontend ships conservative+flagged (§1).

**Ultracode summary:** Phase 0 = one parallel recon fan-out. Phases 1–4 are sequential
PR-groups, but WITHIN the session, PR-A (Phase 1) and Phase 0's W1-deep-recon can run
concurrently, and every mandated skeptic pass is itself a parallel fan-out. Do NOT run
PR-B/PR-C/PR-D worktrees concurrently with each other (shared files + shared
`test_offpeak_maintenance.py`).

---

## §4 Per-slice definition of done

A slice is DONE when: (a) its spec's proposed tests exist and pass (adjusted names/
fixtures fine; semantics not weakened); (b) any ⚠ skeptic findings are fixed +
regression-pinned; (c) the full suite is green locally (§0.4); (d) all §5 gates pass;
(e) the PR body states what was built, what the skeptics found, and any deviation from
the spec WITH the reason (a deviation is fine; a silent one is not).

---

## §5 Verification gates (verbatim, from ci.yml — run all before every push)

```bash
# blocking lint (config ignores dropped by CLI --select, hence the explicit form):
ruff check --select=F,B --extend-ignore=B008 src/ tests/
# mypy ratchet — count must NOT rise above baseline:
count=$(python -m mypy src/ 2>/dev/null | grep -c " error: " || true); echo "$count vs 127"
# SAST (pinned version — unpinned drift reddens PRs):
python -m pip install bandit==1.9.4 && bandit -r src/ -ll -q
# i18n (only if any locale-keyed string changes; F1's new strings may use the
# established un-keyed-diagnostics-panel English-fallback convention instead):
python scripts/i18n_report.py --min 100
# JS syntax after any app.js/index.html <script> edit:
node --check src/static/app.js
# full suite (py3.13 .venv):
python -m pytest -q
```

Alembic: NO slice in this plan adds a migration (W3 deliberately fixes the SELF-HEAL, not
the migration). If you find yourself writing one, re-read the spec — you've diverged.

---

## §6 Session closeout

1. Ledger rows per §0.5; strike shipped items in both investigation docs' status lines.
2. Report per PR: built/skipped/deviated + skeptic findings + the environmental-failure
   list from the full-suite run.
3. Carry-overs stay carry-overs: item 9's ruling question, items 4–5's detector build,
   the §1-fence flags. Restate them; never silently drop or silently build them.
4. If the maintainer's 8-machine experiment numbers arrive mid-session: record them in
   the hardware doc §11 verbatim; they validate/re-rank W1/W2 but change no spec.
