# Field data analysis, November 2026: summary

**Data.** Four running instances: Windows, Linux A, Linux B and Linux C, all app 0.5.0 on builds 175–2,529 commits
behind main. Their diagnostics and field exports are dated 2026-11-26/27. Added to that:
- seven historical VMs (H2–H8) and Linux C, exported 2026-10-16 and 2026-11-14;
- an earlier Windows export from 2026-11-15;
- the 2026-09-11 Stage A catalogue-candidate verification.

That gives 13 snapshots with a per-source sample. Main at analysis time is `cc99452b7`. Every claim cites main.
Measured and inferred are marked in each file. Details are in the per-goal files of this folder.

**Privacy.** Raw data stays on the analysing machine. This folder holds aggregates and the names of catalogue
sources only.

## The ten most important findings

1. **A qualification rule silently stops collecting about a hundred mainstream catalogue outlets per re-checking
   instance.**
   - Linux A and Linux C re-checked part of the catalogue and agree on 170 of 173 verdicts. 110 catalogue domains
     were disqualified by both.
   - By elimination, 108 of 110 and 103 of 103 were disqualified by `link_density_rate` alone. That criterion
     counts every navigation and footer link on the page and fires on each language cohort's top decile.
   - The disqualified sources' articles are normal (19 of 20 read) and have the same link density as qualified ones.
   - Disqualified sources are not collected (`src/scheduler/runner.py:512`).
   - Mechanism verified; still present on main (`src/analytics/source_audit.py:126-131`, `:589-618`, `:643-660`;
     `src/catalog/qualification.py:345-355`). → source-qualification.md §4.2
2. **Collection reaches a few dozen feeds per pass while ~7,000 wait.**
   - Passes process 22–117 sources (Linux A 22–31) and last 1–20 h. They end on their time budget with 6,600–7,100
     sources deferred.
   - Linux A and B are writer-gate saturated (0.98–0.99). One collector flush holds the single writer for 74 s on
     average on Linux A. The cause inside the hold is likely the index writes; not verified. → ingest.md §2.2
3. **A failed feed fetch leaves no trace.**
   - No status and no check time is written (`src/ingest/pipeline.py:733-752` vs `:895-907`).
   - As a result, the Coverage tab's "error" count can never fill (`src/scheduler/coverage.py:46-53`), and a
     failing feed looks "not reached".
   - Its back-off resets, so it is re-tried every pass. Verified. → ingest.md, PR 1
4. **2,339 of 6,612 catalogue feeds never stored a single article in any of 13 snapshots.**
   - 1,311: no fetch recorded on any Linux instance (not reached, or always failing: finding 3).
   - 649: feed-less, and regular passes skip feed-less sources (`src/scheduler/runner.py:857`). Only 13–18% of
     feed-less catalogue rows ever stored anything.
   - 301: the feed answers 200/304 but nothing is stored. → catalogue.md §1, appendices A–C
5. **About one source in six serves junk, and none of it is quarantined.**
   - Hand-reading 160 random per-source articles: 17.5% [12.4–24.1] are non-article pages, stubs, paywall walls,
     consent walls or bot walls.
   - The rate is the same on all four instances. None of the 28 was quarantined. → quality.md §1.1
6. **Page furniture is inside the stored text** of 31% of usable articles: bylines, "read more", related headlines,
   donation and cookie text. Main removes it only at read time, for "Related" and near-duplicates
   (`src/analytics/outlet_furniture.py`). Indexing still sees it. → quality.md §1.1, §1.3
7. **Keywords carry template words.**
   - 72–74% of sources (on fully indexed instances) have at least one top-12 keyword found on half of their pages.
   - Paywall words are indexed as keywords: `allerede` on 155 source rows, `tilaajille` on 58. So are journal
     furniture terms (`DOI`, `license`, `creative commons`). → quality.md §1.3
8. **Qualification has no freshness check and judges from one article.** 50–54% of the candidates each instance
   qualified itself have a newest article more than a year old or undated, and 9–35% rest on fewer than 5 articles
   (`src/catalog/qualification.py:209-212`). → source-qualification.md §4.3
9. **23 catalogue entries declare the wrong language**, on up to 12 of 12 snapshots. Examples: RIA Novosti and
   Meduza as `en`, Independent Arabia as `ar`. Articles inherit the source language (`src/ingest/pipeline.py:297`),
   so all of their articles are mislabelled. → catalogue.md §3, PR 3
10. **Publishers refuse, Linux VMs fail DNS, and discovery loses most candidates to robots.txt.**
    - HTTP 403 is 36–70% of article fetch failures everywhere.
    - DNS is 17–48% on the Linux instances but 2% on Windows, which is likely local.
    - In the 2026-09-11 discovery verification, 42.8% of 37,079 candidates were lost because robots.txt could not
      be read (fail-closed by ruling), and a retry recovered 1.1%. → scraping.md

Windows-only effects:
- CPU-bound, not writer-bound. Its build is 2,529 commits older, so OS and build cannot be separated (Q9).
- More redirect loops, 429 and 5xx failures, which fits its larger request volume.
- Article quality: no difference from Linux.

## Ranked recommendations

Ranked by expected benefit to users. Code PRs are marked **PR**. Everything else is a proposal: it needs a ruling,
re-processing, a version bump or new network activity, which this work does not do.

| rank | recommendation | evidence | size | risk |
|---|---|---|---|---|
| 1 | **P1** `link_density_rate` no longer disqualifies alone (corroborator only, like `short_article_rate`), or counts only in-body links; then re-check the sources it disqualified | finding 1 | small code, but a verdict-meaning change: ruling + criteria version | re-admits the rare real link farm until Q-R4 exists |
| 2 | **PR 1** record failed feed fetches (`last_status` = HTTP code or 0, `last_checked_at`) | finding 3 | small | low: diagnostics and Coverage counts change from "not reached" to "error" |
| 3 | **P2** find the writer-gate hold cost: time `_flush_batched` phases (Q4), then shrink the hold (smaller batches, moving index DML out of the hot window, the keyword day-counts job yielding) | finding 2 | diagnostic small; the fix is an engine change | medium |
| 4 | **PR 3** fix 23 catalogue languages | finding 9 | data only | low: reaches existing installs at seed; no re-extraction |
| 5 | **P3** qualification freshness (newest article ≤ 180 d for candidates, ≤ 365 d for re-checks) and ≥ 5 articles before any verdict | finding 8; the effect on this data is in source-qualification.md §4.4 | small code + ruling | rejects slow publishers |
| 6 | **P4** quarantine-at-door for non-article institution pages, raw-HTML bodies and paywall stubs; turn on the existing opt-in `paywall_stub` / `menu_stub` screen after a calibration run on the 160-article test set | finding 5 | medium | false positives on short real news |
| 7 | **P6** feed back-off on consecutive failures (after PR 1 shows the rate) | findings 2, 3 | small | politeness gain; a recovered feed is seen later |
| 8 | **P7** find feeds for feed-less catalogue rows offline (`feed_find` on stored homepages), or let the crawl supplement report its reach (Q7) | finding 4 | medium | none |
| 9 | **P9** index-time outlet furniture: strip per-outlet repeated shingles before indexing; add wall words to the stoplist | findings 6, 7 | medium; changes the keyword engine id, so a full re-index | high cost |
| 10 | **P10** feed-entry date as a fallback for `published_at`, with a provenance flag | quality.md §dates | small | new data for new articles only |
| 11 | **PR 2** candidate-sources export leaves out non-web provenance (Wikipedia editions, hazard and the like) | catalogue.md §4 | small | none |
| 12 | Q1–Q12 diagnostics (OPEN-QUESTIONS.md), Q5 first | | small each | none |

No catalogue removals are proposed. The appendix lists are evidence for one quarter of PR 1 data
(catalogue.md §2).

## Code pull requests opened from this report

(kept up to date in the report PR description)

- PR 1: record failed feed fetches. Pending.
- PR 2: candidate export leaves out non-web channels. Pending.
- PR 3: catalogue language fixes, 23 entries. Pending.

## Files

INVENTORY.md · quality.md · ingest.md · scraping.md · source-qualification.md · catalogue.md
(+ catalogue-appendix-a/b/c.md) · OPEN-QUESTIONS.md · scripts/ (README.md gives the run order)
