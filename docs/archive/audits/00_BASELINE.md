# Phase 0 — Environment Baseline: "What actually runs today?"

**Date:** 2026-06-09 · **Auditor session branch:** `claude/laughing-bohr-mzqflp` · **HEAD:** `c453159`

> Evidence Protocol labels used throughout: `VERIFIED` (command run in this session, output captured),
> `FAILED` (command run, error captured), `NOT TESTED` (with reason), `SKIPPED` (with reason).

---

## 0. Mission-brief vs. repository reality (read this first)

The audit brief described a repo with `pillar2`–`pillar6` directories, three root requirements
files, six overlapping root docs, ~868 commits, default branch `0.04`, and a "NOT FUNCTIONAL"
README banner. **None of that matches the current repository.** The brief itself instructs
"verify everything against the actual repo" — verified deltas:

| Brief claim | Reality (VERIFIED this session) |
|---|---|
| Default branch `0.04` | Default branch is **`0.07`** (`git remote show origin` → `HEAD branch: 0.07`). Branches `0.01`–`0.07` exist. |
| ~868 commits | 249 commits on the current branch lineage (`git rev-list --count HEAD`). |
| `pillar2`…`pillar6` at top level | Moved to **`quarantine/pillars`** (plus `quarantine/dead_src`, `monitoring_infra`, `package`, `pillar3_analysis`, …). Excluded from packaging, lint, mypy, coverage. |
| 3 root requirements files + per-pillar ones | **Zero** `requirements*.txt` anywhere (`find . -name "requirements*.txt"` → empty). Single `pyproject.toml` is the declared single source of truth. |
| Six overlapping root docs (`DOCUMENTATION.md`, `UNIFIED_DOCUMENTATION.md`, `FIXES_SUMMARY.md`, …) | Gone. One root `README.md`; consolidated `docs/` tree (15 files) + `docs/archive/` holding prior-cycle audit reports and `findings.csv`. |
| `.env.example` **and** `.env.production.example` | Only `.env.example` exists. |
| README declares "EARLY CONCEPT RELEASE — NOT FUNCTIONAL" | README v0.0.7 claims a "genuinely working and tested" core spine. This claim is **substantially VERIFIED** below (clean install, server boots, endpoints 200, 807 tests pass). |
| 2 open PRs | **1** open PR: #55 "In-app uninstall (one-click) + desktop Uninstall launcher" (draft, base `0.07`, adds `src/safety/uninstall.py`, `POST /api/safety/uninstall`, installer launcher; claims 7 new tests). |

Earlier audit cycles (visible at `docs/archive/PHASE*_REPORT.json`, `findings.csv`,
`security_findings.csv`, and merge `73f4872` "full re-audit + debug pass (P0–P3 cleared)" on `0.04`)
already executed much of what this mission's Phases 1–5 prescribe. **This cycle must audit the
current state on its own evidence, not re-litigate the old one** — but it should not assume the
old findings are still fixed either.

**Branch note:** §0.4 of the brief calls for `audit/full-review-<date>`; the execution harness
mandates all work on `claude/laughing-bohr-mzqflp` (pushed to origin). The harness rule wins; this
branch is the audit branch. It was cut from the tip of `0.07`.

---

## 1. Repo state snapshot (0-A)

- `git status`: clean at session start (now: this report + a `.gitignore` fix, see §6). `VERIFIED`
- Branch: `claude/laughing-bohr-mzqflp`; remote `origin` HEAD branch: `0.07`. `VERIFIED`
- Last 5 commits: `c453159` Merge PR #49 (docs-training) · `b393df6` Merge PR #52 (hazards-channel) ·
  `8ffa63a` merge `origin/0.07` · `a1ab90a` merge + temporal-map hazards layer · `dfb1139` Merge PR #54. `VERIFIED`
- Tracked files: **643**. Pack size: **6.92 MiB**. `VERIFIED`
- Last-commit date per top-level directory (`git log -1 --format=%ci -- <dir>`): `VERIFIED`

| Dir | Last commit | Dir | Last commit |
|---|---|---|---|
| `src/` | 2026-06-09 17:47 | `migrations/` | 2026-06-09 17:11 |
| `tests/` | 2026-06-09 17:47 | `quarantine/` | 2026-06-08 13:20 |
| `docs/` | 2026-06-09 17:48 | `assets/` | 2026-06-09 06:40 |
| `configs/` | 2026-06-09 17:44 | `.github/` | 2026-06-08 18:41 |
| `scripts/` | 2026-06-09 13:27 | | |

Development is **active today** — every core directory was touched within the last 48 hours.

- Open PRs: 1 (#55, summarized in §0 table). Listed via GitHub MCP (`gh` CLI unavailable in this
  environment; MCP equivalent used). `VERIFIED`

Top level now: `src/` (38 subpackages: api, ingest, scraper, llm, custody, events, markets, wiki,
timemap, signals, …), `tests/` (104 files), `configs/` (16 YAML files), `migrations/` + `alembic.ini`,
`scripts/`, `docs/`, `quarantine/`, `assets/`, `pyproject.toml`, `install.sh`, `Makefile`,
`.env.example`, `.python-version`.

---

## 2. Toolchain & Python reconciliation (0-B)

**Host:** Ubuntu 24.04.4 LTS · 15 GiB RAM (14 GiB free) · 30 GB disk free · Linux 6.18.5. `VERIFIED`

**Python availability:** system `python3` → **3.11.15**; `/usr/bin/python3.13` (3.13.12), 3.12,
3.11, 3.10 also present. `pip` 24.0 (system) / 25.3 (venv). `VERIFIED`

**Python-version contradiction matrix — the old contradiction is RESOLVED:**

| Source | Claim | Agrees? |
|---|---|---|
| `.python-version` | `3.13` | ✔ |
| `pyproject.toml` `requires-python` | `>=3.13` | ✔ |
| `pyproject.toml` classifiers | `3.13` only | ✔ |
| README (lines 44, 172, 187) | "Python 3.13" | ✔ |
| `tool.ruff` / `tool.mypy` targets | `py313` / `3.13` | ✔ |

**Recommendation:** keep **Python 3.13** as the single supported version (it is consistently
declared, the install and full test suite pass on 3.13.12 — see below). The only operational trap
is that on hosts where `python3` ≠ 3.13 (like this one), `python3 -m venv` builds a 3.11 venv on
which `pip install -e .` would refuse to install; `install.sh`/docs must (and per QUICKSTART do)
insist on `python3.13` explicitly.

**Requirements inventory:** the three root requirements files and all per-pillar ones are **gone**.
`pyproject.toml` is the single dependency source: `VERIFIED`

| Dependency set | Packages | Notable contents |
|---|---|---|
| core `dependencies` | 26 floors (no hard pins) | fastapi, uvicorn[standard], sqlalchemy≥2.0.30, alembic, requests, httpx, beautifulsoup4, lxml, feedparser, trafilatura, pydantic v2, bleach, bcrypt, cryptography, pillow, structlog, slowapi, prometheus-client, tenacity, cachetools, orjson, psutil |
| `[llm]` | 1 | httpx only — Ollama is an external binary over HTTP; **no torch/transformers** in any path |
| `[analysis]` | 8 | numpy, pandas, scipy, scikit-learn, statsmodels, networkx, nltk, vaderSentiment |
| `[nlp]` | 1 | spacy |
| `[crypto]` / `[pqc]` / `[timestamping]` | 1 each | python-gnupg / pqcrypto / opentimestamps |
| `[compression]` | 2 | zstandard, lz4 |
| `[dev]` | 7 | pytest, pytest-cov, pytest-mock, hypothesis, ruff, mypy, httpx |

No overlaps/conflicts possible (single file). All floors resolved cleanly together (see §3).
Version pinning is floor-only (`>=`) — reproducibility of installs is therefore time-dependent;
worth a lockfile discussion in a later phase (parked, not a Phase 0 action).

---

## 3. Installability test (0-C)

Fresh venv: `python3.13 -m venv .venv-audit` → Python 3.13.12, pip 25.3. `VERIFIED`

| Install | Result |
|---|---|
| `pip install -e ".[dev]"` | **VERIFIED — clean.** 84 packages resolved & installed, editable wheel built, zero errors. Key resolved versions: fastapi 0.136.3, uvicorn 0.49.0, sqlalchemy 2.0.50, pydantic 2.13.4, trafilatura 2.1.0, cryptography 48.0.0, pytest 9.0.3. |
| `pip install -e ".[analysis]"` | **VERIFIED — clean.** numpy/scipy/pandas/scikit-learn/statsmodels/networkx/nltk/vaderSentiment import OK on 3.13. |
| `requirements.txt` / `requirements-minimal.txt` | **N/A** — files do not exist in this revision. |
| GPU/CUDA extras | **N/A** — none are declared anywhere (deliberate, per pyproject header). |

No system-library failures, no version conflicts, no dead packages, no typos. Sandbox note: pip
needed network access to PyPI (granted in this environment); on a fully offline host a wheelhouse
would be required — consistent with the project's own offline-install discussion in `install.sh`.

---

## 4. Launch attempt & smoke test (0-D)

Entry points: console script `open-omniscience = src.api.main:main` (pyproject) and
`uvicorn src.api.main:app`. Used the latter. `VERIFIED`

**Startup log (verbatim, full):**

```
2026-06-09 18:17:34 - api - WARNING - Commodity, statistical-analysis & keyword endpoints disabled:
  install the [analysis] extra (pip install -e '.[analysis]') to enable them.
INFO:     Started server process [5144]
INFO:     Waiting for application startup.
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running stamp_revision  -> b1c2d3e4f5a6
```

Server booted, created `data/open_omniscience.db` (path is gitignored), stamped Alembic head,
served requests, and shut down cleanly on SIGTERM. **VERIFIED**

**Endpoint smoke test** (`curl`, server on 127.0.0.1:8000, core install only — before the
analysis extra was added):

| Endpoint | Status | Body (truncated) | Verdict |
|---|---|---|---|
| `GET /api/health` | 200 | `{"status":"healthy","version":"0.0.7","timestamp":"…"}` | VERIFIED |
| `GET /docs` | 200 | Swagger UI HTML | VERIFIED — **but** loads swagger assets from `cdn.jsdelivr.net` (external call when a browser opens it; offline-/local-first wrinkle → carry to Phase 2 findings) |
| `GET /api/sources` | 200 | `[]` | VERIFIED |
| `GET /api/articles` | 200 | `{"total":0,"limit":100,"offset":0,"results":[]}` — paginated by default | VERIFIED |
| `GET /api/llm/health` | 200 | `{"available":false,…"detail":"Ollama not reachable at http://127.0.0.1:11434: [Errno 111] Connection refused…"}` | VERIFIED — graceful degradation without Ollama, honest error, no crash |
| `GET /` | 200 | Single-page UI, header comment: "Deliberately dependency-free: no CDN, no React, no web fonts" | VERIFIED — frontend is served by FastAPI itself, no separate server |

Ollama: not installed, not attempted (per brief). LLM generation paths: **NOT TESTED (no Ollama)** —
but the health endpoint's no-Ollama behavior is VERIFIED above.

---

## 5. Test-suite reality check (0-E)

Pillar suites: **N/A** — pillars are quarantined; `tool.pytest.ini_options.testpaths = ["tests"]`
is the only suite. The brief's "101 tests in pillar2" claim refers to a tree that is no longer wired in.

| Run | Collected | Passed | Failed | Errors | Skipped | Runtime |
|---|---|---|---|---|---|---|
| `--collect-only` (core install) | 740 | — | — | **4 collection errors** (`test_awareness`, `test_commodity`, `test_confidence_intervals`, `test_statistical_tests` — all `ModuleNotFoundError: No module named 'scipy'`) | — | 4.3 s |
| Core install, 4 analysis modules excluded | 740 | 723 | **11** | 0 | 6 | 2 m 39 s |
| **With `[analysis]` extra (full suite)** | **813** | **807** | **0** | **0** | **6** | **2 m 41 s** |

The 11 core-only failures are all in analysis-dependent endpoints (`test_analysis_api`,
`test_commodity_csv`, `test_csv_feeds`, `test_workflow_integration`) — tests expect routes that the
app correctly disables (404) without the extra. So: **the dev+analysis combination is the
configuration under which the suite is green**; running `pytest` on a core-only install is red.
That is a test-marking gap (tests should skip, not fail, when the extra is absent) → carry to
Phase 2 as a finding candidate, severity Low/Medium.

All 6 skips are honest optional-dependency skips: `VERIFIED`
2× `pqcrypto/ML-DSA not installed`, 3× `opentimestamps not installed`, 1× `live OTS network test (opt-in)`.

No hangs; no timeout needed; total runtime ≈ 2m40s.

---

## 6. Writes performed in Phase 0 (all within the allowed scope)

1. Created `.venv-audit/` (disposable; not committed).
2. `.gitignore`: added `.venv-audit/`; **root-anchored** the `audit/` and `data/` ignore patterns
   (`audit/` → `/audit/`, `data/` → `/data/`). The unanchored `audit/` pattern would have silently
   ignored this mission's entire `docs/audit/` deliverable tree (and already shadowed `src/audit/`,
   which is only visible because its files were committed before the pattern). Minimal, reversible.
3. This report.

---

## 7. Executive answer: what fraction of the documented product demonstrably runs today?

**Most of it — the documented core is real.** On a fresh Python 3.13 venv, a single
`pip install -e ".[dev,analysis]"` completes cleanly; the server boots in seconds with a SQLite
store and Alembic migrations; the documented health, sources, articles, and LLM-health endpoints
all answer correctly; the web UI is served locally with no CDN dependencies (the only external
reference found so far is FastAPI's default Swagger CDN on `/docs`); and the full test suite —
813 tests — finishes **807 passed / 0 failed / 6 honestly-skipped** in under 3 minutes. The
README's v0.0.7 claim of a "genuinely working and tested spine" is, at smoke-test depth,
accurate rather than aspirational. What Phase 0 cannot vouch for: the *quality* of those 807
tests, the LLM generation path (no Ollama here), live-network ingestion behavior (deliberately
not exercised), and the claims of the larger feature surface (markets, custody, timemap, wiki,
events) beyond "their tests pass" — that is precisely Phases 1–2's job. The headline risks
carried forward: tests fail rather than skip on a core-only install; Swagger-UI CDN reference;
floor-only (unpinned) dependency versions; and a large `quarantine/` tree whose status must be
kept explicitly out of the product story.
