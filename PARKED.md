# Parked — out-of-scope ideas captured during the v0.0.7 audit

Items deliberately deferred so the audit phases stayed in scope. Each links to a finding ID or
phase where relevant. Nothing here is a Critical/High safety or invariant defect (those were fixed
in Phase 3). This is the backlog the Phase 6 roadmap draws from.

## Maintainability / typing
- **`Mapped[]` ORM migration** (MAINT-03): migrate `src/database/models.py` from legacy
  `Column(...)` to SQLAlchemy 2.0 `Mapped[...]` / `mapped_column()`. This is the real fix for ~103
  of the ~300 mypy errors (the `Column[int]`-vs-`int` false positives). XL effort; do it as one
  focused PR, then flip mypy to a blocking CI gate.
- **`print()` → logger** (MAINT-04): ~50 remaining live `print()` calls (cache.py, duckduckgo.py,
  crypto/provenance.py) → structured `structlog` loggers.
- **Remaining ruff E402** (MAINT-02 remainder): the test `sys.path` hacks and the GPL-header +
  module-docstring import pattern. Low value; consider per-file `# noqa` or a ruff per-file-ignore.

## Refactors (behaviour-preserving; gated on existing tests)
- `view_article` (`src/api/main.py`, 197 lines): extract row-rendering helpers.
- `build_families` (`src/analytics/families.py`, cc=31): split scoring from grouping.
- Other cc≥C functions from `docs/audit/raw/radon_cc.txt`.

## Performance (non-urgent; measured as fine today)
- **MinHash micro-optimization** (PERF-01): vectorise the 128-permutation hashing (numpy) to cut the
  ~5 ms/doc near-dup constant. Near-dup is on-demand analytics, not the hot path, so low priority.
- **FTS large-match-set path** (PERF-02): for queries that match a large fraction of the corpus, the
  `Article.id.in_(fts_ids)` materialization is the cost. Consider a JOIN against the FTS table or a
  bounded top-N. Only matters at very large corpora; measure on real data first.

## Reliability
- **SSRF TOCTOU** (TEST-03 residual): the SSRF guard resolves-and-checks, but `requests` re-resolves
  at connect time, leaving a DNS-rebinding TOCTOU window. Closing it needs connect-time IP pinning
  (a custom `requests` transport adapter). Exotic; hardening, not a known exploit path.
- **Narrow discovery excepts** (BUG-05 remainder): the URL-parsing helper fallbacks in
  `duckduckgo.py` could be narrowed from `except Exception`.

## Capability / architecture (roadmap candidates)
- **Postgres parity or honest SQLite-only** (ARCH-06): either add an FTS path + CI matrix for
  Postgres, or document SQLite-only and stop implying dual support.
- **Core-only CI job**: add a `[dev]`-only CI job so TEST-06 (core install green) can't regress.
- **mypy / ruff blocking in CI**: once the debt is paid, flip both from advisory to blocking.
- **Endpoint test coverage** (TEST-05): keyword_management, reporting, framing, llm HTTP integration.
- **Rate-limit timing test** (TEST-04): fake-clock assertion on the politeness delay.
