# ISO 639 language storage step (S05-02, Q306 = b): what it would touch, measured from the tree

Measured 2026-10-16 on local/row-j12 (d2c13a386 + test fold), grep and file reads only; no code written, nothing run against a real corpus.
Nothing starts until row J merges (Coordinator, 10-16 23:42).

## What is already done (0.4 display half)

`src/catalog/languages.py` holds the converter: `ISO1_TO_ISO3` (639-2/T, == 639-3 for every pair in it), `language_display_code` (639-1 -> `fra`), `language_storage_code` (inverse; fails closed on `pcm`, `yue`, `tet`, which have no 639-1). Display callers: `src/bulletin/render.py` (4 sites). Import caller: `src/catalog/csv_io.py:165` normalises a sheet's language back to 639-1. The T-versus-B choice (20 languages differ) is recorded there as the session's assumption, not ruled.

## What the storage step would change: 11 columns in 11 tables

| table (model line) | column | width | note |
|---|---|---|---|
| Article (713, 719) | `language`, `detected_language` | 10 | the largest table; `language` is stored raw from `<html lang>`, so values like `en-US` exist; 5 indexes carry `language` (927-1012) |
| KeywordMention (2401) | `language` | 10 | the table the outlet and ubiquity gates read by the million (the 2M-mentions window in the J2 timing was synthetic; the real row count is not in the tree) |
| Keyword (1164) | `language` | 10 | part of the keyword's identity `(normalized_term, language)`; index `idx_keyword_language` (1226) |
| AiKeyword (2495) | `language` | 16 | |
| Source (435), SourceMetadata (342) | `language` | 10 / 20 | `idx_source_language`, `idx_metadata_language`; 6,537 `language:` lines in 6 YAML catalogues |
| ExternalSource (1374) | `language` | 10 | |
| LawDocument (2722) | `language` | 8 | |
| KeywordTranslation (1993-1994), ArticleTitleTranslation (2067-2068) | `source_lang`, `target_lang` | 16 | NOT NULL; the pair is a key of the translation cache |

Widths already hold three letters (8 is the smallest), so no column widens; the work is a value rewrite plus every reader of the old value.

## The value space (configs/*.yml)

6,537 `language:` lines, 99 distinct values. 96 are two-letter 639-1; three are already three-letter 639-3 (`pcm`, `tet`, `yue`: one line each). `en` 3,195, `es` 664, `fr` 350, `pt` 264, `ru` 181. So the YAML rewrite is mechanical for 6,534 lines and a no-op for 3, but the converter has no 639-1 form for those 3, which means a store holding `fra` cannot always be shown to `Intl` or `<html lang>` without the fail-closed branch.

## The readers (the risk, not the rewrite)

- 128 `src/` files read a language field (`.language`, `detected_language`, `source_lang`, `target_lang`, `normalize_lang`): `src/analytics` 35, `src/api` 18, `src/ai_layer` 15, `src/law` 9, `src/bulletin` 8, `src/database` 6, `src/ingest` 4, `src/scheduler` 3, others 6. Plus the frontend (`app-*.js` read `.language` in at least 10 files) and 12 locale files.
- `src/analytics/managed.py::normalize_lang` is the house normaliser and returns 639-1; `is_unmanaged`, the language-equilibrium and the ubiquity gates compare against 639-1 sets.
- The DuckDB columnar files carry `language VARCHAR` (`columnar.py` 758, 884): a stored-form change makes every existing rollup and projection stale (a rebuild of the rollup on every install) and #1422 owns those files.
- The restore merge matches keywords on `(normalized_term, language)` by value (`merge.py:1080`) and adopts `language`/`detected_language` columns by value (3225-3226): an old backup's `fr` and a migrated `fra` are unequal unless the normaliser runs first (the same trap country had, solved in 0.4 row K for countries only).
- Wikipedia edition codes (`enwiki`, `simple`, `zh-yue`) are not languages and stay as they are.

## Not measurable from the tree (needs an operator's real store)

Row counts per column (KeywordMention and Article decide the migration time and the backup size); how many `Article.language` values carry a region subtag; how many values are neither 639-1 nor 639-3. The B1 pattern (scan, estimate, backup first, backfill, resume) answers all three before any rewrite; it is the same engine, one more column family.

## The placement question (to the coordinator as Q43)

The two sides of the ruling disagree on timing: the brief proposes the storage half "in 0.5, mirroring Q301 = c", but Q301 = c's own precondition was a real restore exercised on the first half, and the language half has no such step yet (the display half shipped without a storage normaliser on the merge side).

Q43. When does the language storage step land?
 A. (recommended) Not in 0.5. Ship 0.5 with display-only 639-2/T; in 0.6 do the B1-shaped migration (scan, backup, backfill) after the merge normaliser for language has shipped and been exercised. Reason: 11 tables, 128 readers, the DuckDB rollups and the restore's value joins all move at once, #1422 owns the rollup files, and no real-store row counts exist yet.
 B. In 0.5, after J, as a staged row: (1) merge-side normaliser + reader helper (no store change), (2) migration with the B1 engine, (3) payload flip. Larger than row B was; every step needs an operator run.
 C. Never: keep 639-1 in storage permanently and only display 639-2/T (the 0.4 state). Cheapest and safe; the cost is that two forms exist forever and exports show one while the store holds another.
