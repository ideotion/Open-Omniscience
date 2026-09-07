# Parked — out-of-scope ideas captured during the v0.0.7 audit

Items deliberately deferred so the audit phases stayed in scope. Each links to a finding ID or
phase where relevant. Nothing here is a Critical/High safety or invariant defect (those were fixed
in Phase 3). This is the backlog the Phase 6 roadmap draws from.

**Reconciled 2026-08-20 (quality-ratchet session, PR: `claude/oos-quality-ratchet-3otvey`):**
every item below was re-verified against the tree. Several had shipped in 0.0.8 without this
file being updated — those now carry a SHIPPED line with the anchor that proves it, per the
found-resolved-not-rebuilt rule. Statuses are the file's contract: keep them truthful.

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
  loggers. Re-measured 2026-08-20: **72** statement-position `print(` in `src/`, not the "~50"
  this entry used to claim, and its file list was stale — `src/discovery/duckduckgo.py` no
  longer exists (the live ones are `src/utils/cache.py` 17, `src/crypto/provenance.py` 10, the
  rest spread).
  **SHIPPED-WITH-CLASSIFICATION (guard 0.0.8; classification 2026-08-20):** the enforcing guard
  exists — `tests/test_repo_invariants.py::test_no_print_in_library_code` (AST-based, one-way
  ratchet) — and a fresh AST census found ALL 72 remaining prints inside its blessed classes:
  `__main__` demo guards (51), the named CLI helpers of src/api/main.py (13), the doctor's
  printed terminal report (5, capsys-tested), and collect_soak's machine-readable stdout/stderr
  protocol (3, subprocess-tested). Migrating any of them would break tests or degrade deliberate
  CLI output — the migration set is EMPTY under the guard's own definition. ⚠ FOUND while
  verifying: this item's "structlog" target contradicts the tree — **structlog is an ORPHANED
  core dependency (declared in pyproject, ZERO call sites)**; the established pattern is stdlib
  `logging` (~612 call sites). Adopt-or-drop is a maintainer call (dropping is a dependency
  change → both-venv-profiles verification); recorded, not acted on.
- **Remaining ruff E402** (MAINT-02 remainder): the test `sys.path` hacks and the GPL-header +
  module-docstring import pattern. Low value; consider per-file `# noqa` or a ruff per-file-ignore.
  **SHIPPED (2026-08-20, this PR):** a measured, CLOSED `[tool.ruff.lint.per-file-ignores]` list
  in pyproject covers exactly the 36 files carrying the legacy double-docstring/sys.path header
  pattern — E402 findings 164 → 0, the advisory ruff lane 510 → 344, the rule stays live for
  every other file, and the list is documented shrink-only.

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
  **SHIPPED (S2.5, 2026-07-12; found-resolved 2026-08-20):** the /api/articles FTS path resolves
  surviving ids id-only in final order and loads FULL rows for the page alone (ledger: GAMMA-measured
  50 ms → 11 ms warm at 1,776 matches; the win grows with match count).

## Reliability
- **SSRF TOCTOU** (TEST-03 residual): the SSRF guard resolves-and-checks, but `requests` re-resolves
  at connect time, leaving a DNS-rebinding TOCTOU window. Closing it needs connect-time IP pinning
  (a custom `requests` transport adapter). Exotic; hardening, not a known exploit path.
  **Still open (2026-08-20):** the quality-ratchet session's stretch slot deliberately did NOT
  attempt it — a security change in the fetch path wants its own full-skeptic session, and a
  half-shipped one is worse than none.
- **Narrow discovery excepts** (BUG-05 remainder): the URL-parsing helper fallbacks in
  `duckduckgo.py` could be narrowed from `except Exception`.
  **SHIPPED (narrowing found already landed; pins added 2026-08-20, this PR):** `_clean_url` /
  `_extract_domain` / `_resolve_url` catch `ValueError` only, and
  `tests/test_duckduckgo_url_helpers.py` now pins it — fallback branch + unexpected-exception
  PROPAGATION per helper, mutation-checked (re-widening reddens the three propagation tests).
- **`safe_href` broad except** (found 2026-08-20): `src/utils/security.py` `safe_href` still holds
  an `except Exception` in `_clean_url`'s validation chain — the one remaining broad except in the
  URL-parsing path. Narrowing it changes behaviour for non-str inputs of an app-wide sanitizer, so
  it wants its own reviewed slice, not a drive-by.
- **DDG redirect results are dropped** (found 2026-08-20, recorded not fixed — behaviour change):
  `_clean_url` strips the query string BEFORE validation, so a real DuckDuckGo result href of the
  `//duckduckgo.com/l/?uddg=<encoded-target>` redirect form loses its target and is then rejected
  as scheme-less — every real DDG redirect result is silently discarded, and the existing search
  test only asserts `isinstance(results, list)` so it cannot see this. The fix is to unwrap `uddg`
  before stripping; it changes discovery behaviour and needs its own slice with a fixture of real
  DDG result HTML.

## Capability / architecture (roadmap candidates)
- **Postgres parity or honest SQLite-only** (ARCH-06): either add an FTS path + CI matrix for
  Postgres, or document SQLite-only and stop implying dual support.
- **Core-only CI job**: add a `[dev]`-only CI job so TEST-06 (core install green) can't regress.
  **SHIPPED (found-resolved 2026-08-20):** the `core-only` job exists in `.github/workflows/ci.yml`
  ("Core-only install (no [analysis] extra)": installs `-e ".[dev]"`, boot-checks the app, runs the
  full suite with analysis tests skipping cleanly).
- **mypy / ruff blocking in CI**: once the debt is paid, flip both from advisory to blocking.
  Still open. Progress 2026-08-20: ruff's advisory lane is down to 344 findings (E402, a third of
  it, zeroed via the per-file-ignores carve-out); mypy sits at the 127-error ratchet baseline.
- **Endpoint test coverage** (TEST-05): keyword_management, reporting, framing, llm HTTP integration.
  **SHIPPED (core in 0.0.8 WP4; residue closed 2026-08-20, this PR):** WP4 delivered
  `tests/test_llm_api.py` + `tests/test_reporting_api.py` + `tests/test_framing_keywords_api.py`
  (reporting fully covered). This PR closes what WP4 left: the llm model-management/lifecycle
  surfaces get HTTP/wiring proof (`tests/test_llm_http_wiring.py` — they previously had only
  direct-function coverage), framing gains its limit-422s + the zero-match full-shape contract,
  keyword_management its 4 uncovered routes, and `tests/test_api_wiring.py` anchors llm in _SPINE
  plus framing/keyword_management in the optional-[analysis] block.
- **Rate-limit timing test** (TEST-04): fake-clock assertion on the politeness delay.
  **SHIPPED (0.0.8 WP3; found-resolved 2026-08-20):** `tests/test_rate_limit_timing.py` is exactly
  this (its docstring names the finding). This PR adds the two properties it did not pin: the
  shipped default stays polite (≥ 1s), and the per-host stamp survives a transport failure.

## Wikipedia as a living source — what the 2026-09-07 pass left (prompt 18)

Recorded here so the backlog carries them; the reasoning and the full measurements are in the
Open queue entry (`docs/ledger/OPEN_QUEUE.md`, "WIKIPEDIA AS A LIVING SOURCE — THE 2026-09-07
PASS") and in `docs/plans/2026-09-06-repo-analysis/PROMPT_18_wikipedia-living-source.md`.

- **Six quadratic patterns in `plain_from_wikitext`** (found this pass; three sibling patterns
  were fixed in it). They wear the recorded K·N class as `OPEN[^X]*CLOSE`, where an opener with
  no closer makes the character class consume to end-of-document and then backtrack. MEASURED on
  the real function, 100,000 → 400,000 chars of opener-only spam: `<[^>]+>` 0.154 → **2.381 s** ·
  `<ref[^>/]*/>` 1.052 → **16.756 s** · `[[File|Image|Category]]` 1.749 → **28.035 s** ·
  `[[target|label]]` 1.614 → **26.388 s** · `[[target]]` 1.721 → **27.398 s** · `[url label]`
  1.420 → **22.525 s**. Only `{{templates}}` is linear. This is on the wiki INGEST path, so
  whole-edition ingest meets it on every malformed page. Not fixed in the same pass because each
  CAPTURES and rewrites rather than removing, so `strip_blocks` needs a replacement callback and
  every rewrite needs its own byte-identical differential before it goes near ingest. The
  differential harness and the numbers are in `tests/test_markup_blocks.py`; the constants and
  their measurements are beside `_WIKI_BLOCKS` in `src/wiki/corpus.py`. Recorded refutations:
  possessive quantifiers do not fix these (the cost is a scan per start position, not
  backtracking depth), and a "does the closer exist at all" pre-check is byte-identical and free
  but only covers the no-closer-anywhere case.
- **S3 — wikitext rendering.** DESIGNED, not built:
  `docs/plans/2026-09-06-repo-analysis/WIKI_S3_RENDERER_DESIGN.md`. Its deciding constraint is
  verified: the raw wikitext is not in `Article.content` and must not be put there, so the
  renderer must render ON READ from `WikiPage.latest_text` and degrade honestly for a
  dump-ingested page that has none. It is a new HTML-emitting surface over untrusted markup, so
  its safety argument (escape everything, a fixed tag allowlist, no raw HTML pass-through) is the
  slice rather than a detail of it.
- **S1 — whole-edition ingest.** STORAGE-GATED and stopped at the seam, with the gate measured
  against the tree rather than read off a status line: of `docs/design/STORAGE_5TB_PLAN.md` §9's
  five sequencing steps preceding it, steps 1–2 are done and steps 3–5 are not (the FTS split-out
  to a contentless-delete `fts.db`; the hash-sharding prototype at 50–100M synthetic documents,
  which the plan requires BEFORE any sharding code; the Phase C packed keyed text store). Four of
  the six §8 rulings are unruled (blob dedup · OOENC2-vs-`age` · keyed HMAC addressing · the
  `sqlite3mc` trial). What exists today: the bounded ingest already ships
  (`ingest_dump_pages` over an operator-chosen title list); the delta half has a client
  (`WikiClient.fetch_recentchanges`) and **no consumer**; nothing enumerates a whole edition and
  nothing auto-tracks after a dump download.
- **One consented request instead of N HEADs for dump sizes.** The shipped refresh is one
  consented, bounded, politeness-spaced read over the operator's SELECTION. Folding it into a
  single request would be a real win, and the premise it was proposed on — "the dump date's
  `dumpstatus.json` lists every edition at once" — is UNVERIFIED: it has one origin (an
  assistant-written docstring) and two echoes, every `dumps.wikimedia.org` path this repo builds
  is per-edition, and the host is egress-blocked in the build sandbox. **Needs someone who can
  reach the live endpoint**; shipping a parser against a guessed shape would be a fabricated
  endpoint.
- **G10, and it is TWO questions rather than five.** Q2 (analytics mixing), Q3 (version storage
  depth) and Q4 (change feed) were answered by the maintainer's own 2026-06-12 ruling recorded in
  the same FUTURE_DEVELOPMENTS section that filed them, and Q3 shipped the same day. **Q1 —
  scope of dump ingestion:** the superseding ruling says a downloaded edition is TRACKED
  entirely; it does not say INGESTED entirely, and the tiering already proposed under it
  (metadata + flags for all edits, full text and analytics only for pages in the analytical
  corpus) is what decides how much store Phase C must carry. **Q5 — backups:** whether an
  edition's ingested Articles ride the corpus artifact at edition scale, or are reconstituted
  from the dump on restore — which makes a restore depend on a file the backup deliberately
  excludes as re-downloadable. Recommended defaults exist in
  `docs/plans/2026-09-06-repo-analysis/QUESTIONS_FOR_THE_MAINTAINER.md` and are NOT taken.
- **Browser pass.** The dump picker's `=`/`~` size marking, the reader's version row and the
  `?wikitc=` deep link are guarded behaviourally (a node suite drives the tracked-changes view)
  but are Chromium-unverified in that pass.
- **`Article.source_revision` fills forward only.** Existing wiki articles keep `NULL` until a
  re-sync or a re-ingest; there is deliberately no backfill, because a revision that was never
  recorded cannot be recovered from the text. If a backfill is wanted for watched pages, the
  honest source is `WikiPage.latest_text_revid`, and it would claim less than the column does.
