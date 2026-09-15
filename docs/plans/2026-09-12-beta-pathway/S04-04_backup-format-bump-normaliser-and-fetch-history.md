# S04-04 — ONE backup-format bump: the alpha-3 restore normaliser, all rings, the tentative-translation table, the fetch-history member · 0.4, `RELEASE_0.4_GATE.md` row K

> **Scope:** `src/backup/artifact.py` (`BACKUP_SCHEMA`), `src/backup/volumes.py` / `stream_backup.py` (kinds),
> `src/backup/merge.py` (the normaliser before the value-keyed joins; the registry of un-merged tables), a new
> `keyword_translations` model + migration under `migrations/versions`, the rings member, the fetch-history
> member and its trust toggle (first launch + the import dialog), `src/catalog/countries.py` converters, the
> CSV/JSON exporters (Q313), a duplicate-key scan diagnostic, a CI fixture backup, the tests. Must NOT: flip
> storage to alpha-3 (0.5, `S05-02`), build the display half (`S04-05`), rework the import UI beyond the
> toggle (`S04-02`), or remove the legacy restore (Q215 ⛔ = a forbids it).
> **Implements:** Q215 ⛔, Q310, Q313, Q404 🔒, Q409, and — through the gate row — the Q701 NOTE.
> **Gated on:** nothing pending. Q301 ⛔ = c makes this row the precondition of the 0.5 storage half.
> **Sequencing:** after `S04-02` / `S04-03` (the fixture exports and imports through their paths); before
> `S04-06` lands the `keyword_translations` writers and `S05-02` moves storage.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (their verified context and option lists). Grep the tree before building
anything — the sheet's anchors were verified at `main`@`bebcef4` on 2026-09-12 and may have moved. The sheet
sections are §3 (Q215), §4 (Q310, Q313), §5 (Q404, Q409) and §8 (Q701); the `OPEN_QUEUE.md` C1 entry
(`grep -n "S2 (C1)" docs/ledger/OPEN_QUEUE.md`) and the 2026-09-15 head entry. Data safety: the full skeptic
matrix applies to every slice here.

## 1. The rulings this slice implements — verbatim, by ID

- **Q215** ⛔ — **(a)** «Keep the restore half forever, as the docstring commits; close C1.»
- **Q310** — **(a)** «The restore path normalises alpha-2 → alpha-3 while importing (old backups restorable
  forever), and the 0.4 gate proves it with a duplicate-key scan after restoring a pre-migration backup.»
- **Q313** — **(a)** «CSV/JSON exports carry both `country` (old form) and `country_iso3` for one release,
  then the old column is dropped; diagnostics payloads switch in the same release as storage.» [placement:
  both columns in 0.4; the old column dropped in 0.5 (S05-02)]
- **Q404** 🔒 — **(a)** «A `keyword_translations` table (term, source lang, target lang, text, model, prompt
  version, created) — never the trusted index, always ≈, rides the backup.»
- **Q409** — **(b)** «All rings, including shipped.»
- **Q701** ⛔ — not in this slice's JSON; carried here by gate row K as "the Q701 note" (the walk itself is
  `S05-06`). NOTE (verbatim, from `RULINGS_INDEX.md`): «!!!IMPORTANT NOTE!!!: we need to incorporate EVERY
  page request and download and history in backups so that a fresh install with an old backup doesn't
  re-downloads the same pages over and prioritizes other downloads / fetches, THIS IS TRUE NOT ONLY FOR
  WIKIPEDIA BUT FOR EVERYTHING DOWNLOADED WITH THE APP, web fetch/web scrapping history should be backed-up,
  and at install and import, users should be given the choice to trust or not the history with a "trust the
  backup scrapping history" toggle» [NEW RULING IN NOTE]

**Register round 2026-09-15 (C1):** «a, but wait for version 0.7» — read as the removal of the legacy single-file
restore authorised for 0.7; it CONFLICTS with Q215 = a (keep the restore half forever). ⛔ `RC02`. Until
confirmed: build on Q215 = a and remove nothing.

## 2. Where this stands in the tree — the staleness guard, with anchors

- Sheet §4 context (VERIFIED): "The restore merge keys on the **value** (`merge.py:3280`; `country` adoptable
  at :2274): an old backup's `fr` and a migrated `FRA` are unequal, so an unnormalised restore duplicates
  instead of deduplicating." `ISO2_TO_ISO3` / `to_iso2` (:644) / `to_iso3` (:672) exist, fail-closed. Sheet §5
  (VERIFIED): rings "live in `configs/` and ride no backup"; the LLM fallback is "a 5,000-entry process cache
  lost on restart".
- grep-verified in this brief: `src/backup/merge.py:2274` `("country", ("country",))` in the adoptable
  columns; `:3280` `COALESCE(t.country,'') = COALESCE(i.country,'')` — a value-keyed join;
  `src/catalog/countries.py`: `ISO2_TO_ISO3` `:641`, `to_iso2` `:644`, `to_iso3` `:672` (`:677`: aggregates
  such as `HIC`/`WLD`/`EUU` refused), `normalize_country` `:731`, `country_display_name` `:747`.
- grep-verified: `src/backup/artifact.py:48` `BACKUP_SCHEMA = "oo-backup-2"`; `:650` `read_artifact`'s
  docstring "Accepts, forever (D7): oo-backup-2 zips (plain or OOENC1-wrapped), legacy bare SQLite backups,
  and legacy v1 .ooenc files"; `:576` "oo-volumes-1 zip reassembly (read forever, D7)";
  `src/backup/volumes.py:42` `_KNOWN_KINDS = ("oo-volumes-1", "oo-volumes-2")`. Migrations: `./alembic.ini`,
  `./migrations/versions`.
- grep-verified: `docs/ledger/OPEN_QUEUE.md:933` "⛔ S2 (C1) — THE LEGACY SINGLE-FILE RESTORE CANNOT BE
  REMOVED…": `import_scan` finds `legacy_backup`, the dialog offers `ux-i-legacy`, `KINDS` carries `"legacy"`,
  `ImportQueue._run_legacy` shares the `/legacy/restore` helper; `tests/test_unified_backup_ui.py` pins it.
- grep-verified: `src/backup/merge.py:1785` lists `"feed_fetch_state": "per-feed ETag/Last-Modified +
  backoff, re-learned on the next pass"` in the registry of tables deliberately NOT merged ("(b) PER-MACHINE
  or self-healing"); `FeedFetchState` (`src/database/models.py:516`) is per-FEED only (`etag`,
  `last_modified`, `last_status`, `last_checked_at`, `consecutive_unchanged`, `skip_until`); no per-URL fetch
  history table exists (`grep -n "^class " src/database/models.py`); `wiki_pages` / `wiki_revisions` /
  `law_documents` / `law_revisions` DO merge (`merge.py:1714–1715`, `:2952–2966`).
- grep-verified: rings — `src/analytics/equivalence.py:43` `_PATH = configs/keyword_equivalents.yml`
  (curated), `:46` `_GENERATED_PATH = configs/keyword_rings_generated.yml`, three `lru_cache(maxsize=1)`
  loaders (`:97`, `:112`, `:377`) with no runtime invalidation; no `keyword_rings_local.yml` in the tree;
  `keyword_translations` absent (`grep -n "class KeywordTranslation" src/database/models.py` → none).
- grep-verified: no duplicate-key scan exists (`grep -rn "duplicate-key\|duplicate_key"
  src/api/diagnostics.py src/backup/*.py scripts/*.py` → none). The P0 runbook the gate names:
  `docs/product/P0_VALIDATION_RUNBOOK.md` (`RELEASE_0.3_GATE.md:418`), `src/monitoring/p0_validation.py`.
  Exporters for Q313: `/api/articles/export` (`src/api/main.py:1623`), `src/catalog/csv_io.py`,
  `src/catalog/qualification_export.py`; diagnostics payloads in `src/api/diagnostics.py`.
- The lesson governing every member here — `tests/test_merge_owed_tables.py:1–13`: a table riding uncopied
  survives every self-restore; only a merge into a DIFFERENT corpus exercises a handler.

## 3. Slices — what to build, in order

### S1 — The bump and the CI fixture
- **What:** one new format literal (the session picks it and writes why); every older kind stays accepted
  forever (Q215 = a, D7); a fixture backup per older format restores in CI; a round-trip test per member into
  a DIFFERENT corpus, never a self-restore.
- **Why (ruling):** the gate row ("one format-version bump carrying five payloads"); Q301 = c's staging.
- **Acceptance:** the CI restore of the fixture proving each of the five members round-trips.

### S2 — The restore normaliser (Q310)
- **What:** ONE direction-agnostic normaliser on the restore path — accepts either form, emits the store's
  canonical form (alpha-2 in 0.4; the flip is `S05-02`'s), fail-closed through `to_iso2` / `to_iso3` — applied
  to every country-bearing column of the staged copy and to `jurisdiction` BEFORE the value-keyed joins
  (`:2274`, `:3280`). Exercised on a real restore in 0.4 so that 0.5 changes only the target.
- **Why (ruling):** Q310 = a; Q301 = c ("once the backup-format bump and the normaliser have shipped and been
  exercised on a real restore").
- **Acceptance:** the duplicate-key scan (S7) reports 0 after restoring a PRE-migration backup — CI on the
  fixture, the maintainer on a real one (`not-measurable-here`).

### S3 — All rings ride the backup (Q409 = b)
- **What:** the curated and generated ring files, and any locally loaded rings (`S04-06`), as a member; a
  restore that brings rings invalidates the three cached loaders. The gate's design note — the member carries
  the ring file's version and the newer shipped set wins — binds nobody; adopt it or write why not.
- **Why (ruling):** Q409 = b; R9. **Acceptance:** the round-trip test; negative space: a member name is a
  filesystem path and passes the ONE traversal guard on both verify and restore (the 2026-07-10 lesson
  `PROMPT_07` names).

### S4 — The `keyword_translations` table (Q404 🔒 = a)
- **What:** the columns verbatim (term, source lang, target lang, text, model, prompt version, created); an
  alembic migration; a merge handler whose cross-corpus identity is STATED in its docstring (the owed-tables
  lesson); never read as the trusted index — a row here is always ≈. `S04-06` owns the writers.
- **Why (ruling):** Q404 = a. **Acceptance:** `alembic upgrade head && alembic check`; the round-trip test.

### S5 — The fetch / scrape history member and the trust toggle (the Q701 note)
- **What:** the history of everything the app downloads rides the backup (press feeds and the Wikipedia lane
  now; OSM and law as they land) so a fresh install restored from an old backup does not re-download the same
  pages and prioritises other fetches; a "trust the backup scrapping history" toggle offered at INSTALL (the
  first-launch flow) and at IMPORT (the `#ux-import` dialog — coordinate with `S04-02`), its copy ×12 with the
  caveat visible (trusting skips re-fetching what the history says was fetched; untrusting re-fetches).
  Today's per-feed `feed_fetch_state` is explicitly un-merged and per-URL history has no table — the member's
  data model is the session's design, written up as a design note.
- **Why (ruling):** the Q701 note (verbatim above), carried by gate row K.
- **Acceptance:** a fixture where a restored history, trusted, prevents a re-fetch of a recorded page and,
  untrusted, does not; the toggle in the click-through record at both surfaces.
- **May not decide:** the toggle's DEFAULT and the history's identity across corpora (§6).

### S6 — Both columns in exports (Q313)
- **What:** the CSV/JSON exporters emit `country` and `country_iso3`; diagnostics payloads do not switch (they
  move with storage in 0.5); a test pins both columns on each exporter. **Why (ruling):** Q313 = a.

### S7 — The duplicate-key scan (the gate's artifact) and C1 closed (Q215)
- **What:** a read-only diagnostic scanning the value-keyed tables for rows that differ only by code form
  (`fr` vs `FRA`), its output the artifact; C1 closed in `OPEN_QUEUE.md` as KEPT, and any doc still recording
  the legacy restore's removal (`FUTURE_DEVELOPMENTS`, per `PROMPT_07` S2) corrected in the same PR.
- **Why (ruling):** Q310 = a (the scan); Q215 = a (C1). **Acceptance:** the scan's output on the CI fixture
  (0) and on the maintainer's real restore (0).

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured. Plus: the full
skeptic matrix — adversarial passes with a data-loss lens and the mandatory negative-space lens (a hostile
member name refused on verify AND restore; an untrusted history writes nothing; an older ring member never
silently wins; a `None` country is never normalised into a value); every guard mutation-checked by name;
`alembic upgrade head && alembic check`; the P0 data-safety trio re-run green on the new format per
`docs/product/P0_VALIDATION_RUNBOOK.md` (operator); the CI fixture restore; the three i18n gates for the
toggle's strings; the Chromium click-through (Q1128 = a) of the first-launch toggle and the import-dialog
toggle — en, fr, ar; the numstat rule for the ledger files. The real-restore half: `not-measurable-here`.

## 5. Operator steps

1. Restore a real pre-migration backup on the maintainer's machine, then run the duplicate-key scan: the
   output (0 duplicates) is the artifact the row closes on.
2. Re-run the P0 trio on the new format per the 0.3 runbook. Artifact: the `oo-p0-validation-*.json` report.
3. The click-through of the two toggle surfaces (Q1128 = a). Artifact: the record under `docs/audit/`.
4. The maintainer's word on the toggle default and the history model (§6).

## 6. What this slice may not decide

- The trust toggle's DEFAULT (the note gives the choice, not the default) and what "history" is at the row
  level (a per-URL request log, per-page latest revision, the per-feed state — or all three); whether the
  per-machine run journals count.
- The new format literal's name and the ring-version precedence (a design note, not a ruling).
- The cross-corpus identity of a `keyword_translations` row (state it; never guess silently).
- Q301's 0.5 half (`S05-02`); Q823 ⛔ touches nothing here; Q215 ⛔ was answered (a) and is built as KEEP.
- No ASSUMPTION and no CONFLICT is built on here.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.4_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or
  PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
