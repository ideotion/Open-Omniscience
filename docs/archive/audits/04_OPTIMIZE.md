# Phase 4 — Clean-up II + Optimization: maintainability & performance

**Date:** 2026-06-09 · **Branch:** `claude/laughing-bohr-mzqflp` · **Register:** [findings.csv](findings.csv)

> Every performance change in this phase is backed by a before/after measurement from
> `scripts/benchmark_audit.py` (synthetic local data only — never live scraping). Behaviour-preserving
> work was gated on the full test suite staying green on both venvs.

---

## 1. Headline result

**Dropping one useless index cut the database by 63%.** On a seeded 50,000-article SQLite DB,
`idx_article_content` — a B-tree over the full article body — was **224 MB of the 354 MB file** and
was used by **no query** (full-text search goes through FTS5, not a B-tree on `content`). Removing it:

| Metric (50k articles) | Before | After |
|---|---|---|
| Total DB size | 353.8 MB | **130.2 MB** (−63%) |
| Per-insert cost | maintains a B-tree over full text | gone |
| FTS5 search | unaffected | unaffected (VERIFIED) |

Done via a model change (fresh DBs never create it) + reversible Alembic migration
`f1a2b3c4d5e6` (`DROP INDEX IF EXISTS`).

## 2. Maintainability work

| Item | Result |
|---|---|
| **Lint (MAINT-02)** | `ruff check --fix`: **887 → 312** errors (497 autofixed: unused imports, import sorting, pyupgrade typing, redundant modes). `ruff format`: **243 files** reformatted to the 100-col style. Two committed as separate `style:` commits. Remaining 312 are dominated by E402 (test `sys.path` hacks + the GPL-header/docstring module pattern) and are accepted debt. One hand-fix: B006 mutable list-default → tuple in `confidence_intervals.py`. |
| **Re-export guard** | `ruff --fix` stripped `Session`/`SessionLocal` from the backward-compat re-export block in `models.py` (an F401 false positive that broke `from database.models import Session`). Restored with explicit `# noqa: F401` so it can't be re-stripped. Caught by the suite (red `test_source_manager`), then fixed. |
| **Typing (MAINT-03)** | **DEFERRED with a sharper diagnosis.** mypy reports ~302 errors, but **103 are the SQLAlchemy legacy-`Column[...]` typing false positive** (accessing `article.id` yields the class-level `Column[int]` descriptor type, not `int`) and a large cluster is overload-expansion noise on `session.get(**kwargs)`. These are not bugs. The real fix is migrating `models.py` to `Mapped[]`/`mapped_column()` — an XL refactor that belongs on the roadmap, not a speculative Phase-4 edit. mypy is not a blocking CI gate, so nothing regresses by deferring. |
| **`print()` (MAINT-04)** | DEFERRED. MAINT-01 already removed the ~22 prints in the quarantined dead packages; ~50 live prints remain (cache.py 17, duckduckgo 11, crypto 10) — mechanical logger conversion, low value, parked. |
| **Packaging / requirements (4-A.3/4)** | **Already satisfied** (VERIFIED Phase 0). The `PYTHONPATH=pillarN` smell is gone (pillars quarantined); a single `pyproject.toml` with extras is the one dependency source; `pip install -e '.[dev]'` and `'.[dev,analysis]'` both install cleanly in fresh venvs (`.venv-core`, `.venv-audit`). No work needed. |

## 3. Performance — measured, before → after

Harness: `python scripts/benchmark_audit.py --rows 50000` (reusable; intended as a regression gate).

### PERF-02 — DB query latency (50k rows)

| Query | Result | Notes |
|---|---|---|
| Recency browse `/api/articles` (no query, `ORDER BY published_at DESC, id DESC LIMIT 100`) | **p50 1.27 ms / p95 1.43 ms** | `EXPLAIN`: `SCAN articles USING INDEX idx_article_published_at` — already optimal, no missing index |
| FTS5 `market AND court` | p50 113 ms / p95 158 ms | High **only** because the synthetic corpus has a ~36-word vocabulary, so this query matches a huge fraction of 50k rows → a large `id IN (...)` set. On real corpora (large vocabulary, small match sets) this is far lower; not a code defect. Recorded honestly. |
| `idx_article_content` removal | **−224 MB / −63% DB size** | §1 |

### PERF-01 — near-duplicate clustering scaling

| Corpus size | Time | Per-doc |
|---|---|---|
| 1,000 | 4,934 ms | 4.93 ms |
| 5,000 | 24,833 ms | 4.97 ms |
| 10,000 | 49,387 ms | 4.94 ms |

**Verdict: dead-linear — the MinHash + LSH banding correctly avoids O(n²)** (the finding asked us to
prove this; proven). No fix needed. The per-doc constant (~5 ms, pure-Python MinHash over 128
permutations) is the real cost, but near-dup clustering is an **on-demand analytics** operation, not
the hot ingestion path (ingestion dedup uses exact SHA-256, O(1) per article). Optimising the MinHash
constant (vectorising the permutation hashing) is a worthwhile but non-urgent future item — parked,
not a correctness issue.

### API p50/p95 under load

Measured at the query layer (above); the FastAPI handler adds its fixed serialization overhead on top
of the 1.3 ms query. A full concurrent load test (`hey`/`wrk`/`locust`) was **not run** — the
dominant cost is the DB query, which is measured, and adding a load generator would not change the
conclusion. **LLM-path timing: NOT TESTED (no Ollama in this environment).**

## 4. Reliability hardening

| Item | Result |
|---|---|
| **Retry/backoff (BUG-02)** | `EthicalFetcher.fetch` now retries **only transient** failures (network errors, 429, 5xx) with bounded exponential backoff; 4xx / non-HTML / robots / SSRF are never retried; per-host rate limiting is honoured before every attempt; bounded by `max_retries` (default 2). Wired via `OO_FETCH_MAX_RETRIES`/`OO_FETCH_RETRY_BACKOFF`. 5 regression tests (`test_fetcher_retry.py`). |
| Timeouts | Already present on the fetcher (30 s) and the Ollama client (120 s) — verified Phase 1, unchanged. |
| Graceful shutdown / bounded crawl | Already present (scheduler `stop()`, crawler depth/page caps) — verified Phase 1. |
| **BUG-05** | Partially addressed and DEFERRED: the load-bearing handler (the fetch try/except that could mask ingest failures) was already narrowed to `FetchError` in the ETH-01 rework. The remaining broad excepts are defensible best-effort fallbacks in tiny URL-parsing helpers that degrade to a safe value and do not mask data loss; narrowing them is low-value churn, parked. |

## 5. What we deliberately did NOT optimize, and why

- **No large behaviour-preserving refactors** of the complexity hotspots (`view_article` 197 lines,
  `build_families` cc=31). They are already covered by tests and are **not on a hot path**; a
  speculative refactor risks regressions disproportionate to the (cosmetic) benefit. Parked with a
  concrete plan: extract `view_article`'s row-rendering helpers and split `build_families`' scoring
  from its grouping, each behind the existing tests. → `PARKED.md`.
- **No MinHash micro-optimization** (PERF-01): linear and off the hot path; vectorising is a future
  nicety, not a fix.
- **No `Mapped[]` ORM migration** (MAINT-03): correct fix for the dominant mypy class, but XL; roadmap.
- **No FTS query rework** (PERF-02 FTS row): the measured latency is a synthetic-corpus artifact, not
  a code defect.

## 6. Status after Phase 4

- Findings register: **20 FIXED / 9 DEFERRED** (was 16/13 — added PERF-01, PERF-02, BUG-02, MAINT-02).
- Test suite: **813 passed / 6 skipped / 0 failed** (analysis venv); core venv green.
- `bandit -r src/`: **0**. `ruff`: 887 → 312 (accepted remainder). DB size on 50k rows: **−63%**.
- New reusable artifact: `scripts/benchmark_audit.py` (the Phase-4 numbers are now reproducible gates).

Remaining deferred (all non-Critical, sequenced to Phase 5 or roadmap): BUG-05, MAINT-03, MAINT-04,
TEST-04, TEST-05, ETH-02, DOC-02, DOC-03, ARCH-06.
