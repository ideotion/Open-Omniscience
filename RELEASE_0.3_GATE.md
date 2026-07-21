# RELEASE 0.3 GATE — checkable inventory

Status as of 2026-07-20/21, after an autonomous multi-lane session executing the buildable
half of "THE 0.3 CLOSE GATE" (`CLAUDE.md` ~line 6648, maintainer-ruled 2026-07-20). This
document is the maintainer-facing scorecard for the whole gate. **It does not itself close any
row** — it inventories what shipped as draft PRs this session, what remains for the maintainer
to review/merge, and what is structurally impossible for an autonomous session to close at all
(a live ≥5M-article corpus, real hardware time, human browser verification, or explicit
maintainer sign-off).

Read this alongside each linked PR — this file states status, the PRs hold the diffs.

## The honesty boundary (read this before the table)

Every row below that touched code this session produced: **built → self-tested (pytest/ruff/
mypy/i18n) → independently code-reviewed → draft PR opened.** None of that is "field-confirmed,"
"browser-verified," or "run at scale" — those bars are explicitly the maintainer's / a future
session's to clear, and this document never claims otherwise. Matches the repo's own standing
"merged ≠ green ≠ verified" convention.

## Row-by-row status

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | 2026-07-20 source-management program, implemented **and field-confirmed** (not merely merged), incl. docs↔app reciprocity | **Built, not field-confirmed** — 7 of 7 sub-features shipped as draft PRs (below); none are field-confirmed or browser-verified | See sub-feature breakdown |
| 2 | Full transversal repo audit, 0.3 edition | **Written** | [PR #729](https://github.com/ideotion/Open-Omniscience/pull/729) — scoped honestly as a delta audit (07_TRANSVERSAL_AUDIT_V01's own findings' disposition + everything shipped since), not a blind full re-derivation |
| 3 | Full diagnostics at ≥5M-article corpus scale | **Blocked — hard** | Corpus is ~475K articles (a real operator export, see [PR #728](https://github.com/ideotion/Open-Omniscience/pull/728)), ~10x below the bar; only grows via ongoing maintainer merges. The run-journal *prerequisite* is built: [PR #727](https://github.com/ideotion/Open-Omniscience/pull/727) |
| 4 | Full DB import re-checking ALL sources at scale (doubles as backup/restore-at-scale validation) | **Blocked — hard** | Needs the ≥5M corpus (see row 3) plus the admission gate row 1 ships — building the gate is done, running it at that scale is not |
| 5 | Article clean-up: discussed → **maintainer-agreed** → implemented → executed on ≥5M corpus | **Build-only** | Detection built: [PR #737](https://github.com/ideotion/Open-Omniscience/pull/737) (prose gate + inert quarantine scaffolding + a strategy-draft doc). Agreement and execution are explicitly human/maintainer steps, not attempted |
| 6 | DB-10 §1b page-size A/B bench (4K vs 16K), ruling made on large-corpus evidence | **Blocked — hard** | Bench code already shipped pre-session (`src/monitoring/pagesize_bench.py`); the decisive run needs the large corpus + real hardware time, and the `page_size` call is the maintainer's, not attempted this session |
| 7 | v0.2.0 P0 follow-ups: cold-boot unlock at full scale + multi-day live collector soak | **Blocked — hard** | Real hardware, real elapsed time, live network collection — out of scope for an autonomous session entirely, not attempted |
| 8 | Browser-verification bar: `ui_walk` runner standing, or a defined human click-through | **Build-only** | Harness scaffolding shipped: [PR #734](https://github.com/ideotion/Open-Omniscience/pull/734) — explicitly NOT a standing runner (no real browser/AppVM connection); the human click-through alternative remains fully available and untouched |

## Row 1 — sub-feature breakdown

| Sub-feature | PR | Notes |
|---|---|---|
| Qualification lifecycle (admission gate, stamp, background job, re-qualification ladder) | [#732](https://github.com/ideotion/Open-Omniscience/pull/732) | New migration `8249f1450472`; independently re-verified (ruff, `alembic check`, single migration head, targeted tests) |
| Newsletter links → sources | [#733](https://github.com/ideotion/Open-Omniscience/pull/733) | Unrecoverable tracker-wrapped links correctly excluded from seeding a source |
| Airplane/Ollama gate split | [#730](https://github.com/ideotion/Open-Omniscience/pull/730) | Code review also caught and fixed a real pre-existing security bug: a hostname-prefix bypass (`host.startswith("127.")`) in the loopback-URL check, unrelated to airplane mode itself |
| Source-IP surfacing | [#733](https://github.com/ideotion/Open-Omniscience/pull/733) | Reader view + per-source aggregated view shipped backend-only (frontend wiring deferred, disclosed not silently dropped); per-country choropleth dimension partially wired. **Tor-exit-resolve intentionally NOT built** — the ruling itself marks this "design-of-record-pending-the-go," an assessment, not a build ask |
| Discovery trail + citations tally/drills + corpus filters | [#736](https://github.com/ideotion/Open-Omniscience/pull/736) | Stacked on #732 (base branch is `claude/l1-qualification-lifecycle`, not `main`) — merge #732 first. Fixed a real crash bug (name-based lookup with no uniqueness constraint) found during shipping |
| Nav-soup prose gate | [#737](https://github.com/ideotion/Open-Omniscience/pull/737) | Detection/scaffolding only; quarantine job is inert by construction (no DB column, no API wiring, no singleton). Fixed a real sr/az language-detection false-positive bug found during code review |
| Post-import delta screen | [#731](https://github.com/ideotion/Open-Omniscience/pull/731) | Fixed a real bug found during review: a crashed re-index silently reported `failed: 0`, proved via revert-then-restore testing |
| LLM triage/tag + Claude-verification chain | [#735](https://github.com/ideotion/Open-Omniscience/pull/735) | Honesty rails (closed-vocabulary rejection, evidence floor, deduced-vs-asserted tag separation) are real code, verified directly against the diff. **Depends on #730 merging first** — its own PR body notes #730 was still open/conflicting against `main` at ship time |
| Docs↔app reciprocity (USER_MANUAL) | **Not done this session** | Each feature PR above ships code + tests; none updates `docs/USER_MANUAL.md`. This is an explicit gap against row 1's own wording — flagged here rather than silently omitted |

## Merge-order notes for the maintainer

- **#736 (L5) must merge onto #732 (L1), not `main`** — its base branch is set accordingly; do not rebase it onto `main` before #732 lands.
- **#735 (L4) behaves correctly regardless of merge order**, but its airplane-mode behavior is only fully correct once **#730 (L3)** is also merged — #730 was open/conflicting against `main` at the time #735 shipped.
- All other PRs (#727, #729, #730, #731, #733, #734, #737) are independent and can merge in any order relative to each other.
- After merging more than one of these, grep for conflict markers (`<<<<<<<`/`=======`/`>>>>>>>`) before trusting the result — a real incident on this repo committed conflict markers to `main` this way before.

## What this session did NOT attempt (by design, not oversight)

- Any run at real ≥5M-article corpus scale (rows 3, 4).
- Executing the nav-soup cleanup or making the page-size ruling (rows 5, 6 — both explicitly gated on maintainer sign-off/evidence review in the ledger text itself).
- The multi-day collector soak or full-scale cold-boot timing (row 7).
- Claiming the `ui_walk` runner "standing" or performing any actual browser click-through (row 8).
- USER_MANUAL updates for the row-1 features (see reciprocity gap above).

## Outstanding open items surfaced along the way

- [PR #728](https://github.com/ideotion/Open-Omniscience/pull/728) — a separate findings brief from a real 475K-article diagnostics export: two endpoints with a severe p95/p99 latency tail, a missing hard-link on "rising" Home Lead cards, an unexplained 2026-07-11 stall cluster, and five sources at 100% outlier rate. Independent of the 0.3 gate; queued for whenever a session picks it up.
