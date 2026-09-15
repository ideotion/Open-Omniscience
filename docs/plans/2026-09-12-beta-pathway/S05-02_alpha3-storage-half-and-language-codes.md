# S05-02 — Alpha-3 step 2: the store, the configs, the payload flip · 0.5, `RELEASE_0.5_GATE.md` row B

> **Scope:** `src/database/models.py` (the six `String(2)` country columns; `LawDocument.jurisdiction`), one
> Alembic migration + backfill, `src/catalog/countries.py` (`normalize_country`, `to_iso2`, `to_iso3`), the
> config loader and the 14 YAML files carrying `country:` / `jurisdiction:`, the value-keyed joins in
> `src/backup/merge.py`, diagnostics payloads and the CSV/JSON export columns, the language-code branch at
> `csv_io.py:130` (Q306 storage step). Must NOT touch: the three external contracts (FRED/OECD ids, the OSM
> `ISO3166-1:alpha2` tag, the DB-IP table — alpha-2 behind converters), the frontend display (0.4 row L),
> the backup format version (bumped once, 0.4 row K), the restore path's forever-acceptance of old backups.
> **Implements:** Q304, Q305 — via the gate row also Q301 ⛔ = c (step 2), Q313 (the old column dropped),
> Q306 = b (*proposed placement*: the storage step).
> **Gated on:** 0.4 row K SHIPPED AND EXERCISED on a real restore (Q301 = c's own words — the entry
> precondition of the 0.5 gate); 0.4 row L shipped (display + boundary, the loader normalising).
> **Sequencing:** data-safety-critical — never concurrent with S05-10 (both touch the merge and a stored
> identity; the gate row J's own reason). The order between rows B and J inside 0.5 is not ruled (§6).

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (their verified context and option lists). Grep the tree before building
anything — the sheet's anchors were verified at `main`@`bebcef4` on 2026-09-12 and may have moved.

The base working mode's full skeptic matrix applies to every slice here: a data-loss lens, a negative-space
lens, mutation-checked guards, skeptics complete before push. The 0.4 row K normaliser is the promise that no
older backup is ever stranded; this row re-proves it AFTER the store changes.

## 1. The rulings this slice implements — verbatim, by ID

- **Q304** — **(a)** «(a) If Q301 = FULL: `country` becomes alpha-3 everywhere; every parameter accepts both
  forms through `normalize_country`; external-contract endpoints emit `country_iso2` beside it.»
  [placement: the FULL shape lands with the storage half; 0.4 carries country_iso3 beside (Q301 step 1)]
- **Q305** — answered in words: «follows Q301» [placement: 'follows Q301': loader normalises in 0.4
  (S04-05), scripted rewrite + test in 0.5 — i.e. the sheet's option (a) «Rewrite them all in one scripted
  pass, with a test that no lowercase alpha-2 `country:` value remains» becomes the 0.5 step]
- Carried by the gate row, not in this slice's JSON: **Q301 ⛔ = (c)** «FULL, staged: (b) in 0.4, the
  storage half in 0.5 once the backup-format bump and the normaliser have shipped and been exercised on a
  real restore.» · **Q313 = (a)** (exports carry both columns for one release, then the old column is
  dropped; diagnostics switch with storage) · **Q306 = (b)** «Move to ISO 639-2/3 (`fra`).» — *proposed
  placement* of its storage step here, mirroring Q301 = c.

## 2. Where this stands in the tree — the staleness guard, with anchors

- The six `String(2)` country columns sit at `src/database/models.py:335, 425, 667, 1246, 1835, 1947`
  (sheet VERIFIED; grep-verified in this brief: `grep -n 'String(2)' src/database/models.py` — the same six
  lines). `LawDocument.jurisdiction` is a free `String(8)` at `models.py:2244` (grep-verified).
  `StatFigure.ref_area` is already alpha-3 uppercase (sheet VERIFIED).
- `to_iso2` at `src/catalog/countries.py:644`, `to_iso3` at `:672`, `normalize_country` at `:731`
  (sheet VERIFIED for the first two; grep-verified for all three), fail-closed.
- The restore merge keys on the VALUE: `("country", ("country",))` in the adoption table near
  `src/backup/merge.py:2274` and `COALESCE(t.country,'') = COALESCE(i.country,'')` near `:3280` (sheet
  VERIFIED; grep-verified: `sed -n '2270,2278p;3276,3284p' src/backup/merge.py`) — an old backup's `fr` and a
  migrated `FRA` are unequal unless the 0.4 row K normaliser runs first.
- 5,803 `country:` / `jurisdiction:` lines across 14 YAML files (sheet VERIFIED, not re-counted here — the
  session re-counts before the rewrite and records the number). Language codes are ISO 639-1 and share a
  normalisation branch with country at `csv_io.py:130` (sheet VERIFIED; not re-grepped — confirm).
- Twelve locale files `src/static/locales/{ar,bn,de,en,es,fr,hi,id,ja,pt,ru,zh}.json` (grep-verified `ls`).
- 0.4 rows K and L are not in the tree at this brief's writing — the session proves both landed and that
  the maintainer's real-restore artifact for row K exists BEFORE the first migration line is written.
- Tests present to extend: `tests/test_country_normalization.py`, `tests/test_countries_geo.py`,
  `tests/test_merge_ruled_identities.py`, the `tests/test_backup_*.py` / `tests/test_restore_*.py` families.
- Lesson (`LESSONS.md`, 2026-09-07, "MEASURING A PROPOSED ITEM CAN TURN IT INTO A NON-ITEM"): run the
  migration's own predicate over the real data and count the rows it would touch before writing it.

## 3. Slices — what to build, in order

### S1 — Preconditions proven, then the store migration (Q301 = c step 2, Q304)
- **What:** first the proof: 0.4 row K's real-restore artifact and duplicate-key scan exist; if not, STOP
  and say so. Then one Alembic migration: widen the six columns, backfill uppercase alpha-3 through
  `to_iso3` fail-closed (an unmapped value is left as-is and COUNTED in the migration report, never
  guessed); `LawDocument.jurisdiction` normalised with 0.4 row L's disclosed non-ISO codes (`GBR` for the
  law `uk`, `EUU`, `INT`); the migration prints before/after row counts per table.
- **Why (ruling):** Q301 ⛔ = c, Q304 (a).
- **Acceptance:** the before/after row counts per table recorded in the PR body (the gate's clause);
  `alembic upgrade head && alembic check` green; the unmapped-value count is 0 on the reference corpus or
  each residue is named.
- **May not decide:** anything about the three external contracts — they stay alpha-2 behind converters.

### S2 — The payload flip (Q304, Q313)
- **What:** `country` is alpha-3 in every payload; every parameter accepts both forms through
  `normalize_country`; external-contract endpoints emit `country_iso2` beside it; diagnostics payloads switch
  in this release; the export's transitional pair collapses to one alpha-3 value (Q313 — the old alpha-2
  column gone); a walk over every payload's keys for `score`/`rating`/`ranking`/`grade` before push.
- **Acceptance:** a parameter fixture (`fr`, `FR`, `FRA`, `fra`, garbage) per endpoint; an export fixture
  proving one country column, alpha-3, and `country_iso2` only where an external contract needs it.

### S3 — The scripted config rewrite and its test (Q305 → the (a) step)
- **What:** one scripted pass over the 14 files; a repo test that no lowercase alpha-2 `country:` value
  remains; the 0.4 loader normaliser is KEPT as the net for user-edited configs (never removed).
- **Acceptance:** the test is green and mutation-checked (re-insert one `country: fr` → it reddens by name);
  the config diff is reviewed line-for-line, not by count.

### S4 — ISO 639-2/3 in storage (Q306 = b, *proposed placement*)
- **What:** the language columns (`Source.language` is `String(10)` "ISO 639-1 code" — grep-verified in the
  `Source` class) move to 639-2/3 with the same both-forms acceptance, the shared branch at `csv_io.py:130`
  handling both codes; a test over the twelve locale codes.
- **Acceptance:** the twelve-code test; the restore of a fixture backup carrying `fr` yields `fra` once.
- **May not decide:** whether the locale FILE names and `OOI18N` keys move (§6).

### S5 — The real-restore re-run and the trio (operator-gated)
- **What:** the maintainer restores a real pre-migration backup AFTER the storage migration and re-reads the
  duplicate-key scan; the P0 data-safety trio runs on the migrated store.
- **Acceptance:** the scan reports 0 duplicates (the scan output is the artifact); the trio is green.

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured. Plus: the full
skeptic matrix on S1–S4 — the negative-space lens generates an unmapped code, a mixed-case value, a NULL, an
already-alpha-3 value (must not double-convert) and an old backup's `fr` beside a migrated `FRA` (must
dedupe, never duplicate); every new guard mutation-checked by name; the CI restore of 0.4 row K's fixture
backup re-run on the migrated store; the whole-tree guard set; the numstat rule on any ledger file; a
Chromium click-through of the surfaces that show a country (0.4 row L's list: map, agenda, sources, markets,
laws, wiki) in `en` and `ar`, proving no surface regressed to a bare code. The real-restore step is
`not-measurable-here`.

## 5. Operator steps

1. On the maintainer's machine, after the storage migration: restore a real PRE-migration backup, run the
   duplicate-key scan → artifact: the scan's output showing 0 duplicates (`not-measurable-here`).
2. Run the P0 data-safety trio (the 0.3 runbook) on the migrated store → artifact: its report.
3. The click-through of the §4 surfaces (Q1128 = a) → the record on the PR.

## 6. What this slice may not decide

- The order between rows B and J inside 0.5 — not ruled; the brief only forbids running them concurrently.
- The surviving export header (`country` carrying alpha-3, or `country_iso3`) — Q313 names the value that
  is dropped, not the header that stays; proposed in the PR body.
- Whether the loader's both-forms acceptance is permanent for user-edited configs (the brief keeps it).
- Under Q306, whether locale file names / `OOI18N` keys follow the storage codes — asked, not moved.
- The DB-IP bundled table (`src/geo/data/dbip_country_lite.csv.gz`, an alpha-2 external contract): converted
  at read or rebuilt — Q301 (a)'s text says "DB-IP rebuilt", the gate row B does not; asked.
- Nothing about the filename rule (0.4 row L, Q309) or the display hover (Q302) — already ruled and shipped.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.5_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every §1 ruling in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
