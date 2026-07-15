# The improvement cycle — the standing protocol (R4)

**Status:** the reset-proof operating protocol for one recursive-improvement cycle. Any future
session (operator, planning, or CLI) can run a full cycle from this doc alone. Seeded by
[`../design/V1_PATHWAY_2026-07-14.md`](../design/V1_PATHWAY_2026-07-14.md) §2.2 (this doc expands
it; the V1_PATHWAY stays the strategy of record).

**The loop in one line:** measure the app with its OWN diagnostics → compare to the last cycle →
plan the next brief → build it → verify → merge + record. The instruments improve, which improves
the loop. Every improvement claim is a **measured delta**, never "it feels better."

---

## The six stages (with concrete commands)

### 1 · MEASURE — the operator, on the live corpus
The live corpus NEVER enters an agent session; the exported counts/structure are the safe channel
(runbook safety line 2). The operator, in the running app:

- Run the **all-diagnostics job** (Settings → Diagnostics → "Run all diagnostics") — the bundle of
  every measurement export + the self-tests, kept off the request thread. Download the zip.
- Save the **KPI snapshot**: `GET /api/diagnostics/kpi` (rides the bundle; or the endpoint
  directly, `?download=1`) → keep the file as `kpi-<date>.json` in the operator's cycle folder.
  It is the machine-readable K1–K14 board (`src/monitoring/kpi.py`).
- Run the **P0-validation job** (Settings → Diagnostics) *when the backup/scale engines changed
  since the last run* — it re-stamps K3 (bounded-RAM · verify · staged-restore).
- **The 15-minute gold-set grading step (R6 — do it EVERY cycle):** Settings → Diagnostics →
  "Build an IR gold set" (and the who/where/when perception set), then grade ~10–15 queries
  0/1/2. Small, regular, compounding — it is what unblocks K9/K10, lemmatization, the BM25F
  default, and LLM extraction. One heroic grading session never happens; a 15-minute-per-cycle
  habit does.

### 2 · COMPARE — the KPI differ
```
python3 scripts/kpi_diff.py kpi-<prev>.json kpi-<this>.json        # human table
python3 scripts/kpi_diff.py kpi-<prev>.json kpi-<this>.json --json # machine
```
Per metric: `improved | regressed | unchanged | not-measurable | not-comparable`, computed from
the declared direction-of-goodness (no blended verdict, no score). A **regression is a
first-class finding** (the `merged ≠ green` lesson made mechanical), not a CI failure — the
differ always exits 0 for a well-formed diff; only a malformed/incompatible snapshot exits 2.

### 3 · PLAN — a planning session
Turn the cycle report + the ledger Open queue into the next prioritized brief (the 2026-07-12/13/14
pattern; briefs are reset-proof operating manuals). **The priority rule:**
> **red V1 bars > regressions > coverage expansion > polish.**

A red V1 KPI bar (§2.3) outranks everything; a regression outranks new coverage; coverage
outranks polish. The output is a session brief in `docs/design/AUTONOMOUS_SESSION_BRIEF_*.md`.

### 4 · BUILD — a CLI session
Execute the brief: branch off a **freshly fetched** `origin/0.2`, one commit per slice under one
draft PR, the **staleness guard** before every slice (verify anchors; a found-already-shipped item
is verify-and-marked, never rebuilt), **skeptics-before-push** with the negative-space lens on
every honesty-critical / data-safety slice, gates green per slice (suite · ruff F,B · mypy ≤
baseline · `node --check` · i18n `--min 100`). Nothing self-merges.

### 5 · VERIFY — suite + CI + the browser/scale lanes
The ~3,400-test suite + 3-OS CI + the mypy ratchet + i18n gate + the invariant suite. Frontend
slices go through the AppVM `ui_walk` (R3) and graduate "browser-unverified" →
"Gecko-verified (VM) · awaiting human UX pass". Scale claims go through the GAMMA synthetic
harness. Honesty-critical parsers get the negative-space skeptic.

### 6 · MERGE + RECORD — the maintainer + the ledger
The maintainer merges; a `shipped.csv` row per slice + harvested lessons into the Session-rituals
subsection; **a new measurement instrument registers in `LOOP_SELFTESTS`** (enforced by
`tests/test_recursive_loop.py`, which discovers every `run_*_selftest` from the tree). The next
cycle's Measure re-runs the KPI snapshot; the differ closes the loop.

---

## The three roles

| Role | Owns | Does |
|---|---|---|
| **Operator** (maintainer) | the live corpus, the merges, the rulings, the Ollama/AppVM rigs | stage 1 (Measure), stage 6 (Merge), the 15-min grading, the networked/operator-gated steps |
| **Planning session** (web/planning instance) | the strategy + the next brief | stage 3 (Plan) — turns the cycle report into a prioritized brief; DESIGN/DOCS only |
| **CLI session** (Claude Code) | the code | stage 4 (Build) + stage 5's automatable gates — draft PRs, skeptics-before-push, staleness guard |

The recursion is explicit in three places: the loop improves **the app**, **the instruments**
(a better diagnostic makes the next cycle sharper — e.g. the CJK date *probe* shipped before the
extractor, so the fix will be measurable), and **the process itself** (lessons change the
conventions; the ledger is the compounding memory that makes session N+1 smarter than session N).

## Safety rails (binding — §2.6; the runbook is canonical)

The four AppVM lines (synthetic encrypted corpus only · the real corpus never enters an agent
session · app stopped across branch switches · airplane by default) are summarised here but the
**normative text is
[`../design/RECURSIVE_IMPROVEMENT_RUNBOOK_2026-07-13.md`](../design/RECURSIVE_IMPROVEMENT_RUNBOOK_2026-07-13.md)
§6.3, which stays canonical.** Draft-PR-only; propose-never-auto-apply for anything touching data
/ curation / user-visible defaults (auto-actions ship default-OFF behind explicit settings,
activated only on a ruling calibrated by measured false-positive rates). **The constitution is out
of scope for the loop** — the honesty non-negotiables, consent model, no-score rule, local-first,
and the ledger protocol are not optimization targets; any change to a non-negotiable is a
maintainer ruling in the ledger, never proposed as a "fix."

## The instruments this cycle uses (all shipped)

`GET /api/diagnostics/all-diagnostics` (job) · `GET /api/diagnostics/kpi` (`src/monitoring/kpi.py`) ·
`scripts/kpi_diff.py` · `GET /api/diagnostics/recursive-loop` (the meta-gate that proves the
instruments themselves are trustworthy — `src/monitoring/recursive_loop.py`) · `engine_report` ·
`datediag` · `request-latency` · `source-audit` · the P0-validation job · the IR/perception
gold-set builders.
