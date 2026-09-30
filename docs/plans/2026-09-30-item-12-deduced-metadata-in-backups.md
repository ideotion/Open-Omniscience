# Item 12 (R61): deduced metadata rides backups, with provenance, and nothing local gives way

Owner: thread "Translation sweep" (row H). Status: DESIGN, 2026-09-30. Build follows in three PRs.

## The user's rule (2026-09-29 19:55 UTC, answer 12 = b)

All deduced metadata, translations included, is brought over into backups and tagged with provenance.
On a contradiction the UI shows the difference; imported data never prevails over local data; both are
kept and reachable; the user may discard afterwards. Aggregate and accumulate. (R100, 03:35 on 09-30:
articles move between machines only through the user's own backups and restores; this design adds no
sharing between installs.)

## What I found (read from `src/backup/merge.py` on main dc058c2a)

1. A backup already contains every table, because it is a copy of `corpus.db`. "Carried" means the
   restore's merge has a handler for it. Of the deduced tables, only `article_title_translations`
   (my own, PR #1204) is not carried; `places` and `wikidata_items` are the other entries in
   `_MERGE_NOT_CARRIED` and belong to row C (Q823 = a now allows places; row C builds that using the
   tag below).
2. A row that is new to this machine arrives with a full provenance trail already: `merged_rows`
   (batch, table, row) joined to `merge_batches` (origin fingerprint, imported_at, app version), plus the
   producer columns on the row itself (`model`, `prompt_version`, `prompt_text`, `extractor`, engine
   stamps, `created_at`).
3. **The gap is the contradiction case.** When the incoming row has the same identity as a local one but
   a different value, the merge keeps the local row and DROPS the incoming value without a trace. Five
   handlers do it: `keyword_translations` (text), `article_analyses` (result), `article_mentioned_dates`
   (status, confidence, extractor, snippet), `ai_keyword` (confirmed, evidence, prompt_version, language),
   `law_revision_summaries` (summary, prompt_version). For dates this silently throws away another
   machine's confirm/reject of a date the local machine still has as a candidate.

## Inventory: deduced metadata and what a restore does with it TODAY

Read from the three registries in `src/backup/merge.py` against every table in `models.py` (56 tables).
"Carried" = a merge handler copies it into the local corpus. "Contradiction" = what happens when the same
identity arrives with a different value.

| Deduced metadata (table) | Carried today | Contradiction today | This work |
|---|---|---|---|
| Keyword ≈ translations (`keyword_translations`) | yes | incoming text dropped | keep as alternate |
| ≈ titles and summaries (`article_title_translations`) | **NO** | n/a | new handler + alternate |
| AI analyses: summaries, translations (`article_analyses`) | yes | incoming result dropped | keep as alternate |
| AI keywords and entities (`ai_keyword`) | yes | incoming confirmed/evidence dropped | keep as alternate |
| Mentioned dates with candidate/confirmed/rejected (`article_mentioned_dates`) | yes | incoming status dropped (loses a human confirm or reject) | keep as alternate |
| Law change summaries (`law_revision_summaries`) | yes | incoming summary dropped | keep as alternate |
| Keyword mentions, places-in-articles, entities-in-articles (`keyword_mentions`, `article_mentioned_places`, `article_entities`) | yes when the exporter's engine stamp and inputs match this machine (R24), otherwise rebuilt from the article text, which is lossless (no human decision is stored there) | not applicable, rebuilt | none |
| Engine stamps (`article_index_stamps`) | written only for carried rows | n/a | none |
| Deduced article language (`articles.detected_language`), source country and other adoptable article columns | yes (adopted where local has none) | local kept | none (a column, not a row; local already wins) |
| Source qualification verdicts and attempts (`source_qualification_attempts`, `source_candidates`, `source_metadata`) | yes | local kept, the qualification tally records disagreements | none for now: the tally already keeps counts of disagreement |
| Keyword families, tags, supergroups (`keyword_family_overrides`, `keyword_tags`, `keyword_supergroups`) | yes | local kept | none: these are user curation, not deduced |
| Feed fetch history (`feed_fetch_state`) | yes, adopted only where local has none and only when the operator trusted it | local kept | none |
| Places (`places`), Wikidata cache (`wikidata_items`) | no (Q823 held them back) | n/a | row C, using the tag below; Q823 = a now allows it |
| Admission events (`source_admission_events`) | no, by ruling Q1101 = a (an undo to a state this corpus never had) | n/a | unchanged |
| Did-you-mean deletes (`spell_deletes`), hourly counters (`stat_snapshots`), derived bookkeeping (`derived_meta`) | no | n/a | unchanged: rebuilt whole from the vocabulary, or measurements of THIS machine, not metadata about the corpus |

So exactly one deduced table is not carried and is folded into slice 1 (the ≈ titles). Five carried tables
lose the other machine's value on contradiction; slice 1 keeps it. Side files (settings, calendar feeds,
annotations) are not deduced metadata and are unchanged.

## (i) What a backup carries, and the provenance tag

Carried after this work: every deduced table that holds text or a judgement no re-run reproduces exactly:
`article_title_translations` (new handler, identity `(article, target_lang, model, prompt_version)`),
plus the six existing ones, plus the new table `metadata_alternates` below (slice 3).

**The provenance tag, format `oo.prov/1`** (one JSON object; built on read for any deduced row, stored
verbatim on each alternate at restore time). Row C should attach exactly this to places:

```
{
  "v": 1,
  "kind": "model" | "extractor" | "engine" | "human",   # who produced the value
  "producer": "<model name | extractor name | engine id>",
  "version": "<prompt_version | extractor version | null>",
  "prompt_text": "<verbatim prompt, or null>",
  "produced_at": "<the row's created_at, ISO 8601 UTC, or null>",
  "origin": "local" | "<origin_fingerprint of the backup it arrived in>",
  "arrived": null | {"batch": <merge_batches.id>, "at": "<imported_at>", "app_version": "<x.y.z>"}
}
```

Rules: `origin` is the immediate backup's fingerprint (a row that hopped A to B to C says B; the producer
fields still say what A's model and prompt were, because they travel on the row). "human" is used when the
value is a user judgement (a date's confirm or reject). A field that is unknown is `null`, never guessed and
never omitted. No new column is added to any domain table: the tag is assembled from `merged_rows`,
`merge_batches` and the row's own producer columns by one function (`src/backup/provenance.py`,
`provenance_tag(session, table, row_id)`), so it cannot drift from what is stored.

## (ii) Restore: local never gives way, the other value is kept

Unchanged: a new identity is inserted; the same identity with the same value is a duplicate.
New: the same identity with a DIFFERENT value leaves the local row exactly as it is and writes one row to
`metadata_alternates` (new table, one migration):

| column | meaning |
|---|---|
| id | primary key |
| batch_id | the merge batch that brought it (FK `merge_batches`) |
| table_name, identity (JSON) | which deduced table and the row's natural key; article-scoped rows name the article by its content hash so the pointer survives a later restore |
| local_row_id | the local row it contradicts (rebound by identity when the alternate itself travels) |
| fields (JSON) | the imported row's compared and shown fields (the UI marks which differ from the local row) |
| provenance (JSON) | the `oo.prov/1` tag of the imported value |
| status | `pending` (shown in the differences view) or `kept` (the user looked and chose to keep both) |
| created_at | when the restore recorded it |

Identical re-imports do not multiply alternates (unique on table, identity, fields and origin). Nothing is
written into the deduced table itself, so every reader that shows local data is unchanged and no imported
value can appear where a local one is shown. The restore report gains a line per table: "N differences kept
as alternates" (the counts stay counts, no verdict). Fully local machines with no restores have an empty table.

## (iii) The UI: differences visible, discard is the user's

Settings, Data and backup (not a tenth subtab; the nine are pinned by a test): a panel "Differences from
restores" listing alternates grouped by restore batch (date, where from, how many), each item showing
the local value and the imported value side by side, each with its provenance tag in words, and two
actions: **Keep both** (marks it seen) and **Discard the imported value**. There is no action that makes
the imported value the shown one (built as a swap, a review found six defects in it, and the ruling says
imported never prevails; it can return as its own slice on identity-based resolution). A per-batch "Discard all from this restore" is offered with a
count confirmation. Every string ships in 12 languages. The reader's ≈ title and the date list carry a small
"n alternates" hover pointing to the panel (slice 2, if it fits).

## Slices

1. `metadata_alternates` migration, `provenance.py`, the `article_title_translations` handler, alternate
   capture in the six collision handlers, restore-report lines, tests (including a two-corpus restore proving
   local is byte-identical afterwards). Completeness tests updated (`_MERGE_NOT_CARRIED` loses the title table).
2. Endpoints (`GET /api/backup/alternates`, `POST .../{id}/discard|adopt|keep`, batch discard) and the
   Settings panel, checked by me in Chromium.
3. Alternates travel in backups: each incoming alternate is re-attached to THIS corpus's row by its natural
   identity (never the exporter's ids), only if it still contradicts what this corpus holds, arriving pending
   with the origin and tag the exporter recorded. One with no home here (its article is absent) is counted, not
   invented a home. A discarded alternate returns if an older backup still carrying it is restored, like any
   other row a restore adds; discarding it again is one click.

**Status 2026-09-30:** slice 1 = #1237 (merged). Slice 2 = #1242 (panel, keep/discard, the local side found by
identity: article hash or law jurisdiction + url + revision hash, plus the key columns; newest row). Slice 3 is built
locally and follows #1242. Known limitation: `merged_rows` is never pruned, so a row that reuses the id of a deleted
restore-inserted row can be tagged "arrived" (SQLite reuses integer keys); the tag is honest about the row it
reads, not about a row that no longer exists.

## Choices left to the user (recommendation applied unless you say otherwise)

- "Use the imported value instead" was dropped from slice 2 (see above). Say so if you want it back as a slice.
- Places: not in this design. Row C attaches `oo.prov/1` and a handler when it takes its backup slice.
