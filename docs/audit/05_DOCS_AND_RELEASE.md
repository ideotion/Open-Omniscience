# Phase 5 — Documentation truth-up & release readiness

**Date:** 2026-06-09 · **Branch:** `claude/laughing-bohr-mzqflp` · **Register:** [findings.csv](findings.csv)

> Unlike the audit brief's expectation (six overlapping root docs, corrupted tables, fake model
> catalogs), the prior quarantine cycle had already consolidated the documentation. Phase 5's real
> work was the **residue**: one fossil section claiming the system is *non-functional* when it
> demonstrably works, a half-dead config file, doc-tree bloat, and the ETH-02 disclosure.

---

## 1. Doc consolidation map (executed)

| Before | Action | After |
|---|---|---|
| `docs/NEXT_VERSION.md` (167 lines, duplicate planning lane) | **MERGE** | Appended as "Next version — action plans (Themes 2–5)" section of `docs/ROADMAP.md`; cross-references updated (`src/safety/__init__.py`, `docs/CHANGES.md`) |
| `docs/PRESENTATION_PUBLIC.md` (marketing narrative) | **ARCHIVE** | `docs/archive/PRESENTATION_PUBLIC.md`; `docs/README.md` link updated |
| `docs/archive/QUBS_PHASE2_FULL_REPORT.json` (62.9 MB) + `PHASE2_REPORT.json` (3.1 MB) + `PHASE3_REPORT.json` (1.8 MB) | **PRUNE** (DOC-03) | Removed from the tree (retrievable from git history); findings indexes kept; `docs/archive/README.md` added explaining what/why/where |
| `docs/archive/` total | — | **69 MB → 1.2 MB** (VERIFIED `du -sh`) |
| All other docs (README, QUICKSTART, USER_MANUAL, DESIGN, ARCHITECTURE, ETHICS, SECURITY, GOVERNANCE, CONTRIBUTING, CHANGES, ROADMAP, HISTORY, FUTURE_DEVELOPMENTS) | **KEEP** | as planned in Phase 1-E |

## 2. Claims truth-up table

| Claim / text | Old state | Verified status | New text |
|---|---|---|---|
| `docs/ARCHITECTURE.md` database section | "⚠️ EARLY CONCEPT RELEASE — NOT FUNCTIONAL … completely unusable … DO NOT ATTEMPT" over ~170 lines of "conceptual only" instructions (plus wrong ones: edit `models.py` for DB URL, `alembic init` inside `src/database`) | **FALSE — the DB layer works and is tested** (Phase 0: boots, migrations apply, 813 tests green) | Rewritten: SQLite is the supported, tested store (auto-tuned WAL/pragmas, FTS5, `DATABASE_URL`/`OO_DATA_DIR` override, correct `make migrate` workflow) |
| PostgreSQL support (same section + `settings.yaml` hint) | Implied a usable production alternative with "full-text search" | **MISLEADING** (ARCH-06): engine branch exists but FTS no-ops on non-SQLite, zero tests, zero CI | Honestly labelled "**experimental scaffolding, NOT supported**" with the exact gaps listed |
| `docs/QUICKSTART.md:3` "trustworthy core (v0.4)" | stale version | current is 0.0.7 | "(v0.0.7)" |
| `docs/CHANGES.md:3` "`0.05` is the repository's default branch" | stale | default is `0.07`; branches rotate per cycle | "default branch is the active cycle branch (currently `0.07`)" |
| `docs/CONTRIBUTING.md` "pytest -q # 400+ tests" | stale count | 813 collected | "800+ tests, ~2.5 min" |
| `docs/SECURITY.md` "v0.0.6" + outbound-traffic claim | discovery exception undocumented | ETH-01 fixed in Phase 3; ETH-02 (DuckDuckGo topic search) remains by design | v0.0.7; states discovery now uses the ethical fetcher; **documents the one external-service exception** (user-triggered, never scheduled/default) + the `/docs` Swagger CDN note |
| `configs/settings.yaml` (~13 decoy keys) | documented keys the code never reads (DOC-02) | verified against `_apply_yaml_config` | Pruned to the keys actually read, with an explicit honest-contract header and pointers to where the removed concerns really live |
| LLM model catalog (`src/llm/ollama.py` MODEL_CATALOG: llama3.2:3b, gemma2:2b, qwen2.5:3b, phi3:mini) | sizes marked "~" | **SKIPPED — Ollama registry unreachable from this environment (HTTP 403)**; tags match well-known models but were not live-verified | Unchanged; catalog already hedges sizes with "~" and downloads are never automatic |
| Install URL branch drift (brief's `0.03` concern) | — | **NO DRIFT** (verified Phase 1): `bootstrap.sh` tracks the remote HEAD | unchanged |

## 3. The status banner, right-sized

The brief expected to *soften* a "NOT FUNCTIONAL" README banner. Reality was inverted: the README
was already honest (and verified accurate in Phase 0); the stale doom-banner lived in
`docs/ARCHITECTURE.md` and **under**-claimed. New banner text (now in that file):

> **Status (verified in the v0.0.7 audit):** the database layer **works and is tested** — the
> server boots, creates/uses the SQLite store, applies Alembic migrations, and the full test
> suite (800+) passes against it.

The README's existing ✅/🚧 split needed no change — every ✅ checked in Phases 0–2 held up.

## 4. Developer onboarding — VERIFIED

The documented path (`docs/CONTRIBUTING.md` / `docs/QUICKSTART.md`), executed in this audit in
**three separate fresh venvs** (`.venv-audit`, `.venv-core`, `.venv-fresh`):

```bash
git clone <repo> && cd Open-Omniscience   # 1
python3.13 -m venv .venv                  # 2
. .venv/bin/activate                      # 3
pip install -e ".[analysis,dev]"          # 4
pytest -q                                 # 5  → 813 passed, 6 skipped, ~2.5 min
```

Clone-to-green in 5 commands: **VERIFIED**.

## 5. Changelog & version recommendation

- Added a dedicated **"0.07 — full audit cycle"** section to `docs/CHANGES.md` (ethics-invariant
  restoration, safe-by-default config, −63% DB size, retry/backoff, core-only green, dead-code
  quarantine, CI gates, docs truth-up).
- **Recommendation:** ship this audit as part of **0.0.7** (it lands on the `0.07` cycle branch,
  consistent with the project's branch⇒version convention). The next cycle (`0.08` ⇒ `0.0.8`)
  starts from the Phase 6 roadmap. No version-number change is needed in code — `pyproject.toml`
  already says 0.0.7 and the app now single-sources it.
- Operators upgrading an existing database should run `make migrate` once (drops the 224 MB
  redundant index).

## 6. CI (updated `.github/workflows/ci.yml`)

| Gate | Status |
|---|---|
| push trigger on every branch (ARCH-01) | ✅ fixed in Phase 3 |
| lint (ruff) | advisory (312 legacy errors remain; flip to blocking after the parked debt is paid) |
| migrations drift (`alembic check`) | blocking (pre-existing) |
| tests (full, `[analysis,dev]`) | blocking (pre-existing) |
| **core-only job** (`[dev]` install boots + suite green) | **NEW — blocking** (guards TEST-06 forever) |
| **bandit -r src/ -ll** | **NEW — blocking** (currently 0 issues, so any hit is a regression) |
| **pip-audit** | **NEW — blocking** (currently clean; fails on freshly published CVEs — by design) |
| PQC signing job | unchanged |
| External calls | none beyond PyPI/GitHub actions (no telemetry) |

YAML validated (`yaml.safe_load` → jobs: test, core-only, crypto). The new jobs run for the first
time on this PR's CI — their first live run is the verification.

## 7. Release-readiness checklist

| Item | Status |
|---|---|
| Clean install, fresh venv | **VERIFIED** (×3 venvs) |
| Server boots, all routes mount | **VERIFIED** (223 routes) |
| Full suite green (analysis) | **VERIFIED** 813/0/6 |
| Full suite green (core-only) | **VERIFIED** 710/0/6 (+ new CI job) |
| `bandit -r src/` | **VERIFIED** 0 issues |
| `pip-audit` | **VERIFIED** clean (only `pip`-tool advisory, upgraded in CI) |
| §0.5 invariants | **VERIFIED** (Phase 3 scorecard; ETH-02 documented exception) |
| Migrations apply to existing DBs | **VERIFIED** (alembic head `f1a2b3c4d5e6`) |
| Docs match reality | **VERIFIED** (this phase; LLM catalog live-check SKIPPED — registry 403) |
| Benchmarks recorded as regression gates | **VERIFIED** (`scripts/benchmark_audit.py`) |
| Deferred debt tracked | **VERIFIED** (`PARKED.md` + 5 DEFERRED findings, all Low/Medium) |

**Findings register after Phase 5: 24 FIXED / 5 DEFERRED** (newly fixed: ETH-02 as a documented
exception, DOC-02, DOC-03, ARCH-06 as honest docs; remaining deferred: BUG-05 remainder, MAINT-03,
MAINT-04, TEST-04, TEST-05 — all parked with rationale).
