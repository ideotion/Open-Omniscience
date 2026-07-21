# RELEASE 0.3 GATE — checkable inventory

Status as of 2026-07-21, after an autonomous multi-lane session executing the buildable half of
"THE 0.3 CLOSE GATE" (`CLAUDE.md` ~line 6648, maintainer-ruled 2026-07-20), and after the
maintainer merged all ten resulting PRs into `main`. **This document does not itself close any
row** — it inventories what actually shipped, what remains, and what is structurally impossible
for an autonomous session to close at all (a live ≥5M-article corpus, real hardware time, human
browser verification, or explicit maintainer sign-off).

## The honesty boundary (read this before the table)

Every merged PR below went through: **built → self-tested (pytest/ruff/mypy/i18n) →
independently code-reviewed → merged by the maintainer.** None of that is "field-confirmed,"
"browser-verified," or "run at scale" — those bars are explicitly the maintainer's / a future
session's to clear, and this document never claims otherwise. Matches the repo's own standing
"merged ≠ green ≠ verified" convention.

**One real regression was caught and fixed post-merge**: PR #737 (nav-soup prose gate) added a
`run_prose_gate_selftest` harness without registering it in `recursive_loop.py`'s
`LOOP_SELFTESTS` tuple, which `tests/test_recursive_loop.py` enforces — this broke on `main`
after #737 merged (not a merge conflict; a genuine gap the PR's own targeted tests didn't cover).
Fixed in [PR #739](https://github.com/ideotion/Open-Omniscience/pull/739), still open at the
time of writing.

## Row-by-row status

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | 2026-07-20 source-management program, implemented **and field-confirmed** (not merely merged), incl. docs↔app reciprocity | **Merged, not field-confirmed** — all 7 sub-features merged into `main` (below); none are field-confirmed or browser-verified | See sub-feature breakdown |
| 2 | Full transversal repo audit, 0.3 edition | **Merged** | [PR #729](https://github.com/ideotion/Open-Omniscience/pull/729) (merged) — scoped honestly as a delta audit (07_TRANSVERSAL_AUDIT_V01's own findings' disposition + everything shipped since), not a blind full re-derivation |
| 3 | Full diagnostics at ≥5M-article corpus scale | **Blocked — hard** | Corpus is ~475K articles (a real operator export, see [PR #728](https://github.com/ideotion/Open-Omniscience/pull/728), merged), ~10x below the bar; only grows via ongoing maintainer merges. The run-journal *prerequisite* is merged: [PR #727](https://github.com/ideotion/Open-Omniscience/pull/727) |
| 4 | Full DB import re-checking ALL sources at scale (doubles as backup/restore-at-scale validation) | **Blocked — hard** | Needs the ≥5M corpus (see row 3) plus the admission gate row 1 ships — the gate itself is merged, running it at that scale is not |
| 5 | Article clean-up: discussed → **maintainer-agreed** → implemented → executed on ≥5M corpus | **Build-only, merged** | Detection merged: [PR #737](https://github.com/ideotion/Open-Omniscience/pull/737) (prose gate + inert quarantine scaffolding + a strategy-draft doc). Agreement and execution are explicitly human/maintainer steps, not attempted |
| 6 | DB-10 §1b page-size A/B bench (4K vs 16K), ruling made on large-corpus evidence | **Evidence delivered, ruling not yet formalized** | A separate PR (#726, merged same day, not part of this session's lane set) delivered the large-corpus A/B evidence — "16384 wins every dimension at scale, recommendation firm." `CLAUDE.md` records §1a as RULED (2026-07-17) but does not yet carry an explicit §1b RULED bullet — the formal page_size ruling itself appears still open |
| 7 | v0.2.0 P0 follow-ups: cold-boot unlock at full scale + multi-day live collector soak | **Blocked — hard** | Real hardware, real elapsed time, live network collection — out of scope for an autonomous session entirely, not attempted |
| 8 | Browser-verification bar: `ui_walk` runner standing, or a defined human click-through | **Build-only, merged** | Harness scaffolding merged: [PR #734](https://github.com/ideotion/Open-Omniscience/pull/734) — explicitly NOT a standing runner (no real browser/AppVM connection); the human click-through alternative remains fully available and untouched |

## Row 1 — sub-feature breakdown (all merged)

| Sub-feature | PR | Notes |
|---|---|---|
| Qualification lifecycle (admission gate, stamp, background job, re-qualification ladder) | [#732](https://github.com/ideotion/Open-Omniscience/pull/732) (merged) | New migration `8249f1450472`; independently re-verified (ruff, `alembic check`, single migration head, targeted tests) |
| Newsletter links → sources | [#733](https://github.com/ideotion/Open-Omniscience/pull/733) (merged) | Unrecoverable tracker-wrapped links correctly excluded from seeding a source |
| Airplane/Ollama gate split | [#730](https://github.com/ideotion/Open-Omniscience/pull/730) (merged) | Code review also caught and fixed a real pre-existing security bug: a hostname-prefix bypass (`host.startswith("127.")`) in the loopback-URL check, unrelated to airplane mode itself |
| Source-IP surfacing | [#733](https://github.com/ideotion/Open-Omniscience/pull/733) (merged) | Reader view + per-source aggregated view shipped backend-only (frontend wiring deferred, disclosed not silently dropped); per-country choropleth dimension partially wired. **Tor-exit-resolve intentionally NOT built** — the ruling itself marks this "design-of-record-pending-the-go," an assessment, not a build ask |
| Discovery trail + citations tally/drills + corpus filters | [#736](https://github.com/ideotion/Open-Omniscience/pull/736) (merged) | Originally stacked on #732; fixed a real crash bug (name-based lookup with no uniqueness constraint) found during shipping |
| Nav-soup prose gate | [#737](https://github.com/ideotion/Open-Omniscience/pull/737) (merged) | Detection/scaffolding only; quarantine job is inert by construction (no DB column, no API wiring, no singleton). Fixed a real sr/az language-detection false-positive bug found during code review. **See the LOOP_SELFTESTS regression note above** — the one real post-merge gap from this whole session |
| Post-import delta screen | [#731](https://github.com/ideotion/Open-Omniscience/pull/731) (merged) | Fixed a real bug found during review: a crashed re-index silently reported `failed: 0`, proved via revert-then-restore testing |
| LLM triage/tag + Claude-verification chain | [#735](https://github.com/ideotion/Open-Omniscience/pull/735) (merged) | Honesty rails (closed-vocabulary rejection, evidence floor, deduced-vs-asserted tag separation) are real code, verified directly against the diff |
| Docs↔app reciprocity (USER_MANUAL) | **Not done this session** | Each feature PR above shipped code + tests; none updated `docs/USER_MANUAL.md`. This is an explicit gap against row 1's own wording — flagged here rather than silently omitted |

## How the merge conflicts were actually resolved

Every PR from this session's lane execution appended its own row to the same append-only
`docs/ledger/shipped.csv` from the same base commit, so every merge after the first would have
hit a trivial content conflict there. Two real, structural conflicts also existed (not just
appends): `tests/test_repo_invariants.py` between #727 and #735 (a refactor vs. old inline-dict
additions), and all 12 locale JSON files between #736 and #731 (two independent sets of new
i18n keys). Resolution, applied and verified with real `git merge`/tests before each push (not
just planned):

- **`.gitattributes`** (`docs/ledger/shipped.csv merge=union`) added via #727 — makes every
  subsequent `shipped.csv` append auto-resolve for any merge where the side being merged *into*
  already carries the attribute (order matters: the attribute only helps once it's already on
  the target side of a merge, which is why the very first PR to introduce it can't benefit from
  its own fix).
- The `test_repo_invariants.py` conflict was fixed by merging #727 into #735 and relocating
  #735's new coverage-map entries into `src/api/diagnostics.py`'s `_DIAG_COVERAGE_MAP`/
  `_DIAG_COVERAGE_EXEMPT` dicts (which #727's refactor introduced), rather than the old
  inline-dict structure #735 was originally built against.
- The locale-file conflict was fixed by merging #736 into #731 and combining both PRs' new i18n
  keys as proper JSON (zero key collisions across all 12 locales).
- Every remaining PR in the chain (#733, #732→#736, #735, #731, #737, #729, #734, #738) was then
  individually pre-merged against the then-current chain state and verified conflict-free with a
  real `git merge` before being pushed — not just simulated.

All ten PRs from this pattern have since merged cleanly, in the order #727 → #730 → #732 → #736
→ #733 → #735 → #731 → #737 → #729 → #734, confirming the fix held in practice. Only
[#738](https://github.com/ideotion/Open-Omniscience/pull/738) (this document) and
[#739](https://github.com/ideotion/Open-Omniscience/pull/739) (the LOOP_SELFTESTS fix) remain
open as of this writing.

## What this session did NOT attempt (by design, not oversight)

- Any run at real ≥5M-article corpus scale (rows 3, 4).
- Executing the nav-soup cleanup or making the final page-size ruling (rows 5, 6 — both
  explicitly gated on maintainer sign-off/evidence review in the ledger text itself).
- The multi-day collector soak or full-scale cold-boot timing (row 7).
- Claiming the `ui_walk` runner "standing" or performing any actual browser click-through (row 8).
- USER_MANUAL updates for the row-1 features (see reciprocity gap above).

## Outstanding open items surfaced along the way

- [PR #728](https://github.com/ideotion/Open-Omniscience/pull/728) (merged) — a separate
  findings brief from a real 475K-article diagnostics export: two endpoints with a severe
  p95/p99 latency tail, a missing hard-link on "rising" Home Lead cards, an unexplained
  2026-07-11 stall cluster, and five sources at 100% outlier rate. Independent of the 0.3 gate;
  queued for whenever a session picks it up.
- [PR #739](https://github.com/ideotion/Open-Omniscience/pull/739) — the LOOP_SELFTESTS
  registration fix (open at time of writing).
