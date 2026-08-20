# Parked — out-of-scope ideas captured during the v0.0.7 audit

Items deliberately deferred so the audit phases stayed in scope. Each links to a finding ID or
phase where relevant. Nothing here is a Critical/High safety or invariant defect (those were fixed
in Phase 3). This is the backlog the Phase 6 roadmap draws from.

## Maintainability / typing
- **`Mapped[]` ORM migration** (MAINT-03): **DONE 2026-08-20 — the gate is blocking; nothing left
  to do here.** The entry's own plan was "do it as one focused PR, then flip mypy to a blocking CI
  gate", and both halves have now happened, in two separate passes:
  - The *migration itself had already landed* before the session that closed this out. Measured on
    `main`: `src/database/models.py` carries 490 `Mapped[...]` and 490 `mapped_column(...)`, a
    `class Base(DeclarativeBase)`, and 9 remaining `Column(...)` — all nine inside the two
    `Table()` association constructs (`source_group_association`,
    `article_keyword_association`), which are *correct* as `Table()` and were never in scope.
    models.py itself reports zero mypy errors. That work cut mypy **303 → 128**; fixing two real
    latent bugs it exposed (the 429 handler's `retry_after`, `escape(None)`) took it to **127**.
  - The remaining **127 → 0** was the 2026-08-20 paydown, across the 48 files that still carried
    errors — `models.py` was not among them and was not touched. With the residue at zero the
    ratchet had nothing left to count, so `ci.yml`'s `Type-check ratchet (mypy)` became a plain
    blocking `python -m mypy src/`.
  - Measured before/after, CI-verbatim with the pinned mypy 2.3.0 and a cleared `.mypy_cache`:
    **127 errors in 48 files → 0 errors in 475 source files**, rc 0.
  - Two riders worth keeping. The paydown was behaviour-neutral except for **two defensive checks
    added in paths that already failed, only worse** (a non-Ed25519 evidence key now raises where
    it used to fail later as a confusing signing error; an in-memory SQLite URL now raises
    `BackupError` instead of `Path(None)`), and it fixed **one live user-reachable 500** on the
    omnibar (`search_ids` returns `None` for a query with no positive content, e.g. `NOT foo`, and
    the caller took `len()` of it). And a question is left open rather than silently decided:
    `ConfidenceInterval.sample_size` is typed `float | None` because the Haldane–Anscombe
    correction makes the emitted total genuinely fractional — the type now matches the value, but
    whether a *corrected* total should be published under that name is a statistics call, not a
    typing one, so the value is unchanged and the wart is recorded in the module.
- **`print()` → logger** (MAINT-04): remaining live `print()` calls → structured `structlog`
  loggers. Re-measured 2026-08-20 while passing through: **72** statement-position `print(` in
  `src/`, not "~50", and the file list here is stale — `src/discovery/duckduckgo.py` no longer
  exists (the live ones are `src/utils/cache.py` 17, `src/crypto/provenance.py` 10, the rest
  spread). Counted, not fixed; the count is the scope, not the estimate.
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
