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
  **SHIPPED (2026-09-07, prompt 21 S1, PR #1031) — but NOT by the remedy this entry prescribes,
  and that is the part worth reading.** The defect was live-reproduced first: a real
  `EthicalFetcher` against a resolver answering `93.184.216.34` at guard time and `127.0.0.1` at
  connect time returned a loopback HTTP server's body as a clean 200. Connect-time IP PINNING was
  then costed and refused — it means taking over urllib3's private connection construction and
  hand-carrying the hostname for SNI, certificate matching and the `Host` header, so its failure
  mode is a *silently weaker TLS verification* and it fails OPEN the day urllib3 moves. What
  shipped instead validates the address the connection ACTUALLY reaches: same security property
  (the threat is reaching an INTERNAL address; a second, different PUBLIC answer is normal under
  CDN anycast), no TLS state touched, and it rides the stdlib socket chokepoint every HTTP client
  must pass through, so it fails CLOSED. `src/ingest/ssrf_guard.py` + the scope entered in
  `_guarded_redirect_get`, hooked into `airplane.py`'s ONE socket patch layer;
  `tests/test_ssrf_connect_guard.py` (17 tests, a 13-mutation matrix).
  **Residual, stated rather than implied:** a fetch whose proxy endpoint is a HOSTNAME stands the
  connect-time check down for that request — allowlisting it would mean resolving from inside a
  socket hook on every fetch, and a security guard may not break a working configuration in order
  to protect it. `_guard_target`'s policy there is unchanged, so such a deployment is exactly as
  protected as before. A publicly-routable-but-internal address is out of reach of any
  address-shape rule, here and in `_guard_target` alike.
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
  **SHIPPED (2026-09-07, prompt 21 S2, PR #1031):** `safe_href` AND its sibling `sanitize_url` now
  catch `ValueError` only — the one exception `urlparse` genuinely raises — and log the drop.
  `urlparse` is hoisted to a module import so the PROPAGATION half is testable at all; without
  that, "an unexpected exception escapes" is an untestable claim. Pinned by the NET-02 block in
  `tests/test_security_hardening.py`; re-widening either except reddens exactly the two
  propagation tests.
- **DDG redirect results are dropped** (found 2026-08-20, recorded not fixed — behaviour change):
  `_clean_url` strips the query string BEFORE validation, so a real DuckDuckGo result href of the
  `//duckduckgo.com/l/?uddg=<encoded-target>` redirect form loses its target and is then rejected
  as scheme-less — every real DDG redirect result is silently discarded, and the existing search
  test only asserts `isinstance(results, list)` so it cannot see this. The fix is to unwrap `uddg`
  before stripping; it changes discovery behaviour and needs its own slice with a fixture of real
  DDG result HTML.
  **SHIPPED (2026-09-07, prompt 21 S2, PR #1031):** `_unwrap_search_redirect` resolves the
  redirector FIRST. It returns the target, or the input UNCHANGED for anything that is not a
  redirect (so a non-redirect result takes a byte-identical path), or `None` for a redirect with no
  usable target — never the redirector itself, which on the absolute form
  (`https://duckduckgo.com/l/?rut=…`) is a perfectly valid https URL and would register
  duckduckgo.com as a DISCOVERED SOURCE. `tests/test_duckduckgo_url_helpers.py`, seven mutations,
  all reddening by name. The query strip on the FINAL url is deliberately unchanged and now stated
  rather than implied: it is right for this consumer (which keeps the DOMAIN and treats the url as
  a homepage to look for feeds under) and wrong in general, for the recorded reason that a URL's
  query can BE the article address.
  **What this did NOT close, and could not:** the entry asked for "a fixture of real DDG result
  HTML" and there is still none, because `html.duckduckgo.com` answers `CONNECT … 403` through the
  session sandbox's proxy (probed 2026-09-07 against a `pypi.org` 200 control). See the new
  result-link-regex entry below — the `uddg` fix is justified by the URL shape alone, which is
  documented and stable, and is strictly additive, so it cannot lose a result that resolves today.

- **The DDG result-link regex requires `class=` to be the FIRST attribute** (found 2026-09-07,
  recorded NOT fixed): `_parse_results` matches `<a class="result__a" href="…">`, so an anchor
  carrying `rel="nofollow"` before `class`, or `href` before `class`, does not match at all. That
  is real fragility in the one sanctioned external discovery channel. It is deliberately left
  alone: widening it blind could start admitting sponsored anchors as discovered sources, and the
  live markup **could not be observed** — `html.duckduckgo.com` answers `CONNECT … 403` through the
  session sandbox's proxy against a `pypi.org` 200 control. Unblocked by either an egress-allowlist
  entry for that host or a captured sample of a real response; until then, changing it would be
  guessing at someone else's HTML.
- **Nonce-based CSP** (audit S-006 residual, NET-04): `src/api/main.py::_CSP` still carries
  `script-src 'self' 'unsafe-inline'`. It cannot lose that clause until the inline handlers go —
  re-counted 2026-09-06 at roughly **590** (~331 in `index.html`, ~259 across the seventeen
  `app-*.js` modules), not the 295 the ledger recorded, which counted `index.html` only and
  predates the module split. Sequenced strictly BEHIND that retirement; landing the nonce first
  breaks the app.
- **Four security items wait on a maintainer ruling, not on work** (re-verified 2026-09-07 —
  each has zero code, so a future session need not re-investigate): **I3** Tor-exit-resolve
  (SOCKS `RESOLVE` / `0xF0`; the design of record is already written, only the go/no-go is owed),
  **I4** `oo-netcut` and Stem-controlled Tor (Arti's Python bindings must be RE-VERIFIED, not
  assumed), and **G9 + NET-09** self-update and release signing (`release.yml` publishes
  `SHA256SUMS` and its own header already says signing is a tracked future item, so the release
  path does not over-claim today). Full detail, with what each is blocked on, in
  [`docs/ledger/OPEN_QUEUE.md`](docs/ledger/OPEN_QUEUE.md).

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
- **The Observatory's remaining tiers** (design of record:
  [`docs/design/OBSERVATORY_DESIGN.md`](docs/design/OBSERVATORY_DESIGN.md) §9; ruled 2026-07-18).
  **PARTLY SHIPPED 2026-09-07 (PR #1033):** S0 + S1 (the `domain:` scaffold field and the
  universe/galaxy payload endpoint, 2026-07-20) and S2 + S3 + most of S6 (the `ooSky` canvas
  renderer, the Observatory tab, interactions, a11y, the 17-theme sweep). UI invariant #31
  records what may not regress. **What is left, and why each is blocked on the same thing — the
  endpoint emits the universe and galaxy tiers only, so every item below needs payload before it
  needs pixels:**
  - **S5 · spiral ARMS** — the Item-AC topic tags within a galaxy, with the cardinality guard the
    ruling asked for *by construction* (top-K ≤ 6 arms by member count, each above a member floor,
    with a labelled "untagged / other (N)" disc carrying the remainder). Needs the keyword-tags
    facet per super-group in the payload. Design §11 threads 3 and 4 (**K = 6** and the **member
    floor ≥ 5**, both still only *proposed*) cannot be settled until this exists to measure.
  - **S5 · STAR SYSTEMS and PLANETS** — rings (cross-language concepts) as the tier below a
    galaxy, and their per-language members as literal planetary rings segmented by language share.
    Needs the ring list + `language_breakdown` per galaxy.
  - **S4 · NOVAE** — trending spikes gated with the `supergroup_rising` discipline (count floors +
    FDR across the sky), never a bare spike. The payload carries a per-galaxy `rate` but no
    per-star series and no gate output.
  - **S4 · the TIME SCRUB** — the ooTimeScope window, with novae flaring in their spike weeks.
    Default must stay full corpus time (cross-time recall is sacred); the scrub is the lens.
  - **The TELESCOPE** — the per-corpus mini-sky inside the analysis window. Explicitly *not v1*
    by the ruling itself; the name is reserved for it.
  **Two questions carried for the maintainer, recorded in `docs/ledger/OPEN_QUEUE.md`
  (2026-09-07) rather than decided:** (a) the twelve **domain wedge labels render in English in
  every locale**, because they are corpus data and this app never translates data — but they are
  bundled scaffold rather than user content, so they could reasonably be keyed; (b) the tab
  **autoloads** its payload, which is `_deadlined` and 120 s-cached and measured 0.26-0.28 s on a
  440-article corpus, but runs `supergroup_stats` for all 77 groups and is **unmeasured at 500k
  scale** — if a live run is slow the fix is the explicit-action button the article-length figure
  already uses, never a cap.
  **The human UX pass** the surface awaits is not a separate item: it is
  [`RELEASE_0.4_GATE.md`](docs/product/RELEASE_0.4_GATE.md) row F, which covers every
  Chromium-in-sandbox stamp.
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
