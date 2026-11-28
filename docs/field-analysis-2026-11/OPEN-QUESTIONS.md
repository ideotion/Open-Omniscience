# Open questions: what this data could not answer, and the diagnostic that would

| # | question | why it could not be answered | diagnostic that would answer it (size) |
|---|---|---|---|
| Q1 | Which catalogue feeds are dead (DNS, TLS, 403/404, timeout) rather than not yet reached? | A failed feed fetch writes no state (`src/ingest/pipeline.py:733-752`). `last_feed_status` is null for both cases. | **PR 1** records `last_status` (HTTP code, or 0 with no status) and `last_checked_at` on failure. A follow-up adds the `ff:` class as a column (additive migration) and exports it in `sources_without_article.classes`. |
| Q2 | Extraction success by method | trafilatura's path is not recorded (`src/ingest/extract.py:31-40`) | Record which trafilatura branch produced the body (bare_extraction / extract fallback) in the pass tally as per-method counts. No per-article column is needed. Small. |
| Q3 | Where items are lost **per source** (duplicate, non-article, extract-failed, 403…) | Only per-pass sums exist (`src/scheduler/runner.py:885-891`). Detail goes to log lines. | A per-source rolling counter of outcomes over the last N passes, exported in source-samples' class table. Medium. |
| Q4 | Why a collector's write-gate hold lasts 74 s on Linux A | `contention.json` gives totals per holder, not per statement | Time the phases of `_flush_batched` (insert, index_article DML, links, commit) and export them in `collect_perf`. Small. |
| Q5 | Which criterion disqualified each source | `source-audit.json` was skipped by deadline on all 4 instances | Write `failing_criteria` into the `SourceQualificationAttempt` row at verdict time (it is computed then) and export it in `source-qualification.json`. Small. |
| Q6 | Where `published_at` came from, and how often it is wrong | not recorded | A date-provenance flag per article (meta / none). Feed-date fallback is proposal P10. |
| Q7 | Crawl-supplement coverage of feed-less sources | `last_crawled_at` is exported only for sources with an article | Add `crawled` to the never-collected class columns (`src/api/diagnostics/source_samples.py:183`, `:207-213`). Small. |
| Q8 | Politeness actually applied (spacing per host) and retries | not logged | A per-host spacing histogram in `collect_perf`. Small. |
| Q9 | Whether Windows' different bottleneck (CPU, not writer) is the OS or the older build | Windows ran a build 2,529 commits behind; its write gate was unreadable (restart) | A Windows export on current main |
| Q10 | Same-script language errors (es/pt, ru/be, ru/uk) | the script check cannot see them | Run the existing offline detector (`src/analytics/langdetect.py`) on each source's random article in the source-samples export, and report the per-source agreement with the catalogue language |
| Q11 | Are the 301 "feed answers, nothing stored" feeds refused (403), paywalled, or duplicates of a sibling? | Q3 | Q3 |
| Q12 | Accuracy, reliability, ownership of sources | no outside truth in the data; `reliability_score` is never computed (`src/database/models.py:437`) | not a diagnostic: needs curated reference data |
