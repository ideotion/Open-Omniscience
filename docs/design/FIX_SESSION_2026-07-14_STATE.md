> **Status update (2026-07-22, docs-audit remediation pass):** verified against live `main` by a subagent fan-out audit of the whole `docs/design/` tree — this file's own "laws-as-Articles NOT built" note is now stale and superseded — `src/law/corpus.py` ships that wiring (see the FIX_SESSION_PROMPT_2026-07-14.md banner for detail). The other two carry-overs (data-location chooser, the quarantine action) remain open exactly as this file describes. See [`ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md`](./ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md) for the full remediation plan.

# Fix session 2026-07-14 — execution state + carry-over

Executing `docs/design/FIX_SESSION_2026-07-14.md` (`FIX_SESSION_PROMPT_...`). One draft PR per slice
onto `0.2`; nothing auto-merges. The **data-safety pair (Slices 0 + 1) is DONE at full quality** —
the prompt's Definition-of-Done ships those first. The feature/large slices are parked with precise
specs below (a future CLI session picks them up; verify each against the tip first — staleness guard).

## SHIPPED (draft PRs)
- **Slice 1 — encrypted-store lock retry (data-integrity)** — ✅ `is_locked_error` now recognises a
  RAW sqlite3/sqlcipher3 `OperationalError` (unwrapped by SQLAlchemy on the sqlcipher3-creator engine)
  across the cause/context chain, narrow by construction (an IntegrityError still takes the dedup
  path). **#669 (merged).** Follow-up **#671** broadens `run_write_with_retry`'s narrow
  `except OperationalError` to `except Exception` + `is_locked_error` gate, closing the same gap for
  the markets/import/store writers (`batch.py`'s 297-loss path was already re-armed via its broad
  `except Exception`). Negative-space lens pinned.
- **Slice 0 — large-data backup silently skipped the corpus (DATA-SAFETY, top)** — ✅ **#670.** The
  frontend `_uxRun` now gates the folder/blob phase (and "Backup complete") on the volumes job
  PROVABLY completing as a `backup` of the corpus into THIS dest (`state==="done" && mode==="backup" &&
  _uxSamePath`), and `_uxStartThenPoll` re-throws a masked 409 whose live job isn't ours (an unrelated
  Verify/restore/other-dest). Source-level guards + the backend "done⇒corpus present" contract pin it;
  the full jsdom/DOM harness + a click-through are owed (fork-3 — no jsdom harness exists here).

## PARKED — precise specs (attempted/verified; not rushed)
- **Slice 2 — first-launch external-drive data-location chooser.** A data-location step in
  `unlock.html` between legal-accept and create-passphrase (all pre-DB); a tiny pre-DB loopback
  endpoint validates a writable server-side dir + free space, creates `<picked>/OOS data/`, persists
  `OO_DATA_DIR` via the shipped A11 `install.sh persist_data_dir()`/`oo.env` seam, and re-points
  `data_dir()` before init. Default stays the app data folder (one click). Honest tmpfs/Qubes warning;
  key the step ×12; `test_repo_invariants` guard. BUILDABLE-NEXT — a bounded feature.
- **Slice 3 — law vertical: laws as first-class Articles (multi-PR, the big one).** The ruling of
  record ("versioned sources = an Article + a linked revision/audit trail"); NOT P0-scale-gated (tens–
  hundreds of docs). Slices: (1) `LawDocument.latest_text`(+`_revid`) + `LawRevision.full_text`
  (`CompressedText`, additive migration + boot self-heal like the wiki columns); `track.py` stores the
  FULL fetched text (diff becomes a derived convenience), through the ONE `EthicalFetcher`; pypdf for
  PDF law sources, a JS-only page stores nothing + a reason (never a fabricated body). (2) ingest each
  law into the corpus via `index_article` (mirror `src/wiki/corpus.py`) — one Article per doc, a
  dedicated per-jurisdiction source domain (filterable class forever), idempotent on content hash.
  (3) search (`/api/search/omni` content) + a reader tracked-changes view. (4) grow the catalog
  honestly. Skeptic (negative-space): a fail-to-extract law stores no body + a reason; a re-fetch of
  unchanged text doesn't dup the Article but records the revision check; PDF garble is flagged.
- **Slice 4a — retroactive non-article QUARANTINE** (reversible, never a silent delete): reuse the
  #659 classifier over the existing corpus, move flagged items to a quarantined state (excluded from
  analytics/search, restorable), report counts, operator reviews before purge.
- **Slice 4b — keyword extraction junk** (honesty-critical; needs the self-test the SAME commit + a
  diagnostics before/after + a skeptic): three sub-fixes — (i) URL residue: never tokenize tracker-URL
  fragments into keywords; (ii) drop repeated-token n-grams; (iii) accented/CTA all-caps mis-tagged as
  ENTITIES. **DESIGN FINDING (recorded so the next session doesn't repeat it):** `surface.isascii()`
  alone is TOO BROAD — it would drop legit non-Latin acronyms (Greek ΕΕ, Cyrillic СССР); the
  accented-Latin guard (`[À-ÖØ-öø-ÿĀ-ſ]`) handles "DÉCOUVREZ" but NOT the prompt's ASCII examples
  ("PARTAGEZ", "S'ABONNER"), which need an evidence-driven CTA denylist (a `_CTA_STOP` frozenset,
  casefolded, applied in `_entities` after `_ACRONYM_STOP` at `extract.py:708` — worst case demotes a
  CTA to a term, never removes a real keyword; honor the stoplist-architecture collision rule). Land
  each in `src/analytics/selftest.py` with a real-acronym-stays-an-entity negative case.
- **Slice 4c — async diagnostics freezes** (verify-first; S2 already converted `/api/articles` +
  guarded insights): re-check which diagnostics GETs are still `async def` doing heavy sync DB+codec
  work; convert offenders to plain `def`/`run_in_threadpool` + bound whole-table materializations. Grep
  the TEST tree for the old `async def <name>(` before converting (the #283 stale-anchor family).
- **Slice 4d — segmenter** — OPERATOR, not code: `pip install -e ".[segmentation]"` on the field box
  (the `None`-fallback seam is already safe).

## UPDATE (2026-07-14, continuation) — 3 more slices addressed
- **Slice 4b — keyword extraction junk** — ✅ SHIPPED (**#673**). Three sub-fixes in `extract.py`,
  each landed in the keyword self-test: (i) `_strip_urls` removes tracker-URL residue before
  tokenising (both extractors); (ii) repeated-token n-grams dropped; (iii) accented-Latin shouts +
  a `_CTA_STOP` demoted from ENTITY to term — **deliberately narrow** (Latin-accent-only, so Greek
  ΕΕ / Cyrillic СССР acronyms survive; NASA/WHO stay entities). 3 self-test cases + 7 negative-space
  tests.
- **Slice 4a — retroactive non-article scan (review half)** — ✅ SHIPPED (**#674**).
  `scan_non_article_candidates` + `GET /api/diagnostics/non-article-scan` — COUNT-ONLY (url +
  word_count, no content decrypt), per-reason counts + bounded id sample; a conservative undercount
  that never flags a real article. **Remaining: the quarantine ACTION** (a `quarantined` column +
  migration + self-heal + the `SELF_HEALED_COLUMNS`/scale-bench guard registrations + a reversible
  de-index/restore job + an operator-review UI).
- **Slice 4c — async diagnostics freeze** — ✅ VERIFIED-PRESENT (no fix needed). The only 2
  `async def` in `diagnostics.py` are nested stream-drain helpers, not route handlers; every
  diagnostic route is a plain `def` (threadpool). S2's work held — nothing to convert.
- **Slice 4d — segmenter** — operator step (`pip install -e ".[segmentation]"`); the `None`-fallback
  seam is already safe.

**STILL REMAINING (the two large features):** Slice 2 (first-launch external-drive data-location
chooser — a pre-DB endpoint that writes `oo.env` + re-points `data_dir()` mid-boot, plus an
`unlock.html` step; delicate, bounded) and Slice 3 (the law vertical — laws as first-class Articles
+ `LawRevision` audit layer; explicitly multi-PR). Both warrant a dedicated session; specs above.
