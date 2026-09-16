# Open Omniscience — backup summary

- **Folder:** `202609161718_OpenOmniscience_Backup`
- **Written:** 2026-09-16T17:18:30+00:00

## What is in this folder

- **Encrypted volumes:** 4 · 11.6 MB on the drive · 5.8 MB of content
- **Parity (corruption recovery):** written
- **Files copied:** none.
- **Elapsed (corpus):** 0.6 s
- **Elapsed (files):** not recorded — no large-data files were copied
- **Destination:** `/tmp/claude-0/-home-user-Open-Omniscience/3c715d31-5d5e-518b-85f8-01fee7c9c964/scratchpad/drive/202609161718_OpenOmniscience_Backup`

## Integrity

- Verified — all 4 volumes were re-read and matched their checksums.
- Verify-after-write re-reads every volume from the destination and checks its checksum, so an export reads every byte back off the drive as well as writing it. That is what catches a stick that accepted the write and stored something else.
- Every export writes every volume: nothing is reused from an earlier backup, so this folder's bytes were all written by this one pass.

## Encryption

- **Corpus at rest in this backup:** no
- The corpus and every member of the artifact are encrypted. Copied large-data files (dumps, maps, model weights) are public, re-downloadable blobs and are NOT encrypted — that is what makes a 100 GB export feasible, and it is stated rather than implied.

## Versions

- **App version:** 0.3.0
- **Backup schema:** oo-backup-2 · container oo-volumes-2
- **Database schema (alembic):** c4f18b62d0a7

## What the corpus holds (rows per table, articles first)

| Table | Rows |
|---|---:|
| `articles` | 24 |
| `sources` | 6,404 |
| `source_qualification_attempts` | 6,400 |
| `keyword_mentions` | 1,551 |
| `keywords` | 607 |
| `keyword_supergroup_members` | 538 |
| `keyword_supergroups` | 77 |
| `law_documents` | 23 |
| `article_mentioned_dates` | 10 |
| `keyword_tags` | 4 |
| `article_entities` | 3 |
| `alembic_version` | 1 |
| `ai_custom_prompt` | 0 |
| `ai_keyword` | 0 |
| `app_state` | 0 |
| `article_analyses` | 0 |
| `article_keyword_association` | 0 |
| `article_keywords` | 0 |
| `article_links` | 0 |
| `article_mentioned_places` | 0 |
| `article_source_relationships` | 0 |
| `commodity_prices` | 0 |
| `derived_meta` | 0 |
| `event_imports` | 0 |
| `external_sources` | 0 |
| `feed_fetch_state` | 0 |
| `hazard_event_details` | 0 |
| `keyword_categories` | 0 |
| `keyword_family_overrides` | 0 |
| `law_revision_summaries` | 0 |
| `law_revisions` | 0 |
| `link_classification_rules` | 0 |
| `market_extraction_rules` | 0 |
| `merge_batches` | 0 |
| `merged_rows` | 0 |
| `source_articles` | 0 |
| `source_candidates` | 0 |
| `source_credibility_rules` | 0 |
| `source_group_association` | 0 |
| `source_groups` | 0 |
| `source_metadata` | 0 |
| `stat_figures` | 0 |
| `stat_snapshots` | 0 |
| `stat_subscriptions` | 0 |
| `watch_matches` | 0 |
| `watches` | 0 |
| `wiki_pages` | 0 |
| `wiki_revisions` | 0 |

## Attribution

- Tracked legal documents — this corpus records NO licence metadata for them. Each document's terms are those of the official source it was mirrored from (the official URL stored with the document); check them before redistributing. That is a gap in what was recorded, never a grant.
  - *applies because:* `table:law_documents`

---

This file was written by the export that made this folder. It describes only what is here; it is not a signature and proves nothing about the bytes — `volumes.json` carries the per-volume checksums that do.
