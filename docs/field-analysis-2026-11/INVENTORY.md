# Inventory (Phase 0)

All numbers come from the instances' own exports. "Not read" always gives its reason. Instances are named
**Windows, Linux A, Linux B, Linux C**. Seven more historical instances are named **H2–H8**. They are VMs on the
same hardware as Linux C and sent exports on 2026-10-16 and 2026-11-14. The 2026-11-14 snapshot labelled
"Linux C @11-14" is Linux C itself, three weeks earlier. Machine details (CPU model, host names, paths, instance
tags) are deliberately left out.

Current main at analysis time: `cc99452b7` (2026-11-26). Script: `scripts/inventory.py`.

## The four current instances

| | Windows | Linux A | Linux B | Linux C |
|---|---|---|---|---|
| OS | Windows 11 | Linux | Linux (VM) | Linux (VM) |
| App version | 0.5.0 | 0.5.0 | 0.5.0 | 0.5.0 |
| Build (diagnostics) | `8e1bc0aa4` (2026-11-14), 2,529 commits behind main | `9607f30df` (2026-11-24), 460 behind | `ac58a005b` (2026-11-25), 175 behind; second bundle `cc99452b7` = main | `42c8e9397` (2026-11-23), 890 behind |
| Diagnostics bundle(s) | 2026-11-26 11:14 | 2026-11-27 12:11 | 2026-11-26 00:18 (low memory: corpus totals not read) and 2026-11-26 11:04 | 2026-11-26 15:11 |
| Field export | 2026-11-26 12:23 | 2026-11-27 12:27 | 2026-11-26 18:33 | 2026-11-26 14:18 |
| Articles (source-quality export, non-quarantined) | 486,258 | 419,550 | 1,874,232 | 283,636 |
| Keyword-indexed share of ratio-audited articles | 100.0% | 100.0% | **35.37%** | 100.0% |
| Source rows (all, incl. unchecked candidates) | 55,946 | 55,930 | 83,967 | 36,928 |
| Sources with ≥1 stored article | 4,519 | 4,306 | 4,402 | 3,770 |
| Source-samples (one article per source) | 4,519 | 4,308 | 4,402 | 3,784 |
| sample_articles rows | 35,397 | 34,129 | 36,353 | 27,468 |
| keyword_outliers rows | 189,868 | 168,192 | 328,636 | 111,978 |
| Candidate sources (own-measured, not in catalogue) | 606 | 518 | 105 | 237 |
| Qualification verdicts measured locally (app-provided) | 0 | 200 (130 disqualified) | 6 | 421 (149 disqualified) |
| Stored dates of the sampled articles | 2026-10-20..11-25 | 2026-10-04..11-27 | 2026-07-31..11-25 | 2026-11-08..11-26 |

Linux B holds a 1.87 M-article corpus from a backup import. Its keyword index was still being rebuilt (35% indexed),
so every keyword-derived number for Linux B covers a small, non-random slice and is marked as such where used.

**Members that did not complete** (deadline). These are the same on every instance:
- `source-audit.json` was skipped on all four. That is the per-source criterion verdict, so which criterion
  disqualified a source has to be inferred (see source-qualification.md).
- `keyword-log-digest.json` was skipped or declined on all four.
- `performance`, `benchmark`, `card-audit` and `bulletin-weekly` are partial on all four.
- Linux B also skipped `non-article-scan`, `criteria-calibration`, `article-length` and `keyword-engine`.

## Historical and complementary data

| Set | Content | Used for |
|---|---|---|
| H2–H8 + Linux C, 2026-10-16 (v0.4.0, `d269ec397`) | diagnostics + source-quality bundle per VM | pass tallies (ingest.md) |
| H2–H8 + Linux C, 2026-11-14 (v0.5.0, `b8f2427ac`) | diagnostics, source-quality, source-samples | catalogue evidence across 13 snapshots, language check, pass tallies |
| Windows, 2026-11-15 (`8e1bc0aa4`) | full field export | catalogue evidence, Windows over time |
| H4, 2026-09-30 | all-diagnostics, session-forensics text | not used beyond identity (no field export) |
| Stage A kit, 2026-09-11 (`c7efa83`, `96d80b01`) | 8 shards × 2 passes of catalogue-candidate feed verification | discovery funnel (scraping.md) |
| Developer test-run folder (2026-11-14) | pytest logs, boot logs, freshly seeded empty databases | **not used**: no collection or field data (one boot log records "Seeded 6616 starter sources") |
| Diagnostics of a backup restore/reindex (2026-11-15) | job metrics | not used (import path, not ingest) |

## What every field means

Two code-read field dictionaries were written for this analysis, from the exporters on main. They are summarised
where each number is used. Points that change how a number must be read:

- A source row is a **feed**, unique on `(domain, feed_key)` (`src/database/feed_key.py:1-29`). One outlet can have
  several rows.
- `per_source_summary.article_count` excludes quarantined articles but includes articles still pending screening
  (`src/analytics/source_quality.py:1206-1216`).
- Source-samples pick one article per source with a seeded random offset over **all** its articles, quarantined
  included (`src/api/diagnostics/source_samples.py:144-154`). This is an unbiased per-source sample: each source
  weighs one, whatever its size.
- `external_link_count` counts cross-site links from the **whole fetched page**, navigation and footer included
  (`src/ingest/pipeline.py:330`, `:379-425`).
- `sources_without_article.last_feed_status`: null means "never recorded", 0 means "checked, no HTTP status"
  (`src/api/diagnostics/source_samples.py:191-192`). **But a failed feed fetch writes nothing**
  (`src/ingest/pipeline.py:733-752`; only `_record_feed_state` at `:895-907` writes, on 200 and 304). So the value 0
  never occurs, and null mixes "never fetched" with "every fetch failed". This is finding 3.
- `candidates.json` `evidence.last_article` is the newest **publisher** date (`published_at`), not the storage date.

## What is missing (not in any export)

- HTTP status, error class and retry count per feed or per article fetch. Only per-pass sums `ff:*` exist
  (`src/ingest/pipeline.py:803-805`), and none are kept per source.
- Drop reasons per source (duplicate, non-article, extract-failed). These go to log lines only.
- Extraction method, and where `published_at` came from. Neither is recorded (`src/ingest/extract.py:31-40`).
- Robots verdicts per host over time. The preflight covers at most 50 sources, once (`src/monitoring/preflight.py:44`).
- Politeness actually applied (inter-request spacing per host).
- Crawl-supplement coverage of feed-less sources (`last_crawled_at` is exported only for sources with an article).
