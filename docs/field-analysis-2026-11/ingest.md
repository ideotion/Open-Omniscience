# Goal 2: article ingest (fetch → store → index)

## Method

- `scripts/ingest_runs.py` reads `debug-bundle.json → scheduler.recent_runs`, the 30 newest collection passes per
  bundle. Passes are de-duplicated on start time across bundles of the same instance.
- Each pass carries:
  - `duration_s`, `sources_processed`, `deferred_next_pass` and `recycled` (why the pass ended);
  - `tally`: the per-item outcome sums named by `IngestResult` (`src/ingest/pipeline.py:110-131`) and the
    failure classes `ff:*` (`src/ingest/fetch_verdict.py:25-39`, `:397-442`).
- `scripts/collection_contention.py` reads `collect_perf_windows` and `contention.json` (the write gate's per-holder
  totals since that app start).
- All counts are full counts over the passes the bundles kept. They are not samples.

**What a pass tally can and cannot see** (verified in code). A feed whose own fetch fails returns before anything
is counted: `src/ingest/pipeline.py:733-752` adds only `skipped_offline`, and only when the cause is the kill
switch. So **feed-level failures are in no tally and in no table**. The item outcomes below are for article pages
reached through feeds that did answer.

## 2.1 Funnel per instance

| instance | passes | span | median pass | sources processed | stored | mean `deferred_next_pass` | stored / hour |
|---|---:|---|---:|---:|---:|---:|---:|
| Windows | 60 | 11-11..11-25 | 2.54 h | 16,023 | 53,986 | 6,777 | 335 |
| Linux A | 30 | 11-25..11-27 | 1.46 h | 688 | 7,666 | 7,034 | 171 |
| Linux B | 30 | 11-17..11-24 | 2.91 h | 1,027 | 7,207 | 6,672 | 47 |
| Linux C | 75 | 10-14..11-26 | 1.06 h | 173,323 | 42,160 | 3,973 | 586 |
| H3–H8 (2026-10/11) | 18–74 each | 09-28..11-14 | 0.62–2.03 h | | | 2,573–4,684 | 210–828 |

`sources_processed` counts feed-less sources, which return at once (`src/scheduler/runner.py:857-858`). Linux C's
last four passes processed 664–765 sources and stored 0–55 articles. The pass-level figure is therefore
"sources looked at", not "feeds read".

Per-item outcomes (share of item outcomes):

| instance | items | stored | duplicate | fetch_failed | extract_failed | non_article | blocked_robots | robots_unavailable |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Windows | 79,638 | 67.8% | 24.4% | 3.7% | 2.7% | 0.6% | 0.6% | 0.2% |
| Linux A | 11,762 | 65.2% | 21.5% | 6.4% | 3.4% | 0.9% | 0.4% | 2.1% |
| Linux B | 10,058 | 71.7% | 11.6% | 10.8% | 3.4% | 1.2% | 0.5% | 0.8% |
| Linux C | 85,859 | 49.1% | 39.9% | 7.3% | 2.5% | 0.3% | 0.3% | 0.5% |
| H3, H4, H5, H7, H8 | 41k–69k each | 48.5–52.7% | 35.8–39.2% | 6.4–9.1% | 2.5–3.3% | 0.4–0.5% | 0.2–0.3% | 0.4–0.9% |

The instances agree on these points, which are therefore likely real:
- **Duplicates are the largest loss after storage: 12–40% of items.** The pipeline drops them before or after
  fetch by canonical URL and by content hash (`src/ingest/pipeline.py:159-162`, `:273-323`). A high share means
  feeds re-serve items the instance already has. That is expected for a rotation over the same feeds, but every
  duplicate still costs a page fetch when the URL differs.
- **Extraction failures: 2.5–3.4%** (body under 200 characters, `src/ingest/extract.py:45`).
- **Non-articles rejected at the door: 0.3–1.2%.**

## 2.2 Throughput: the pass reaches a few dozen feeds while ~7,000 wait

| | Windows | Linux A | Linux B | Linux C |
|---|---|---|---|---|
| recent passes: sources processed per pass | 42–117 | 22–31 | 9–401 (mostly 9–62) | 74–765 |
| pass duration | 1.5–8 h | 1.2–1.8 h | 2.3–20.7 h | 0.7–2.2 h |
| why passes ended (`recycled`) | budget 56 of 60 | budget 29 of 30 | budget 29 of 30 | budget 38, storage_wal 9, none 28 |
| collection window decision | hill-up / saturated-at-floor (CPU-saturated share 0.35) | **writer-saturated** (share 0.98) | **writer-saturated** (0.99) | no-articles 10 of 11 |

Write gate (single SQLite writer), cumulative since the app last started:

| | Linux A | Linux C |
|---|---:|---:|
| grants | 50,717 | 44,377 |
| contended | 3,788 | 11,459 |
| total wait | 527,205 s | 365,036 s |
| longest wait | 1,021 s | 575 s |
| total held | 212,031 s | 167,250 s |
| CPU spent while holding | 111,502 s (53% of hold) | 109,804 s (66%) |
| collector threads: holds, mean hold | 2,202 holds, **74 s** | 12,608 holds, 7.2 s |
| biggest other holder | keyword day-counts job: 35,291 s over 44,856 holds | wiki drain 12,076 s; keyword day-counts 4,254 s |

Linux B and Windows: **not read**. Their latest bundles were taken just after an app restart (1 grant each).

- **Measured.** On Linux A one collector flush holds the writer for 74 s on average. Up to 8 collector threads and
  the keyword day-counts job queue behind it, and passes end on their time budget after 22–31 sources.
- **Verified in code.** The flush already computes keyword, sentiment and place extraction **before** taking the
  gate (`src/ingest/batch.py:313-319`). Inside the gate it runs the inserts, the per-article index writes and the
  link writes for the whole batch, then commits (`:320-338`).
- **Cause: likely, not verified.** The 53–66% CPU inside the hold points at the volume of index writes (mention
  rows, FTS) on an encrypted store. The data has no breakdown of a hold by statement, so this is a proposal for a
  diagnostic first (OPEN-QUESTIONS.md Q4).
- **Windows-only.** Windows is CPU-bound, not writer-bound, on a build 2,529 commits older. Its write gate was not
  readable, so whether the newer Linux builds introduced the writer saturation cannot be told from this data.
- **Local, not general.** Linux B was rebuilding its keyword index for a 1.87 M-article import during these passes
  (35% indexed), so its 47 stored per hour is that import's effect.

**Consequence (measured, catalogue.md §1).** 1,311 catalogue feeds have no fetch recorded on any of the three
Linux instances, and never stored an article in any of 13 snapshots.

## 2.3 Stalls and retries

- Fetch retries: 2 retries on network errors and on 429/500/502/503/504, with 0.5 s·2^n back-off
  (`src/ingest/__init__.py:765`, `:1696-1714`). The retry count per fetch is not recorded, so retries cannot be
  measured.
- Feed back-off advances only on a 200 that stored nothing. It **resets on a fetch error**
  (`src/ingest/pipeline.py:745`, `:917-950`). A feed that always fails is therefore due again on every pass, and
  its failure is never recorded. Proposal P6, after PR 1 makes failures visible.
- `crawl_delay_deferred` (wait > 180 s) is negligible: ≤ 0.1% of items.
