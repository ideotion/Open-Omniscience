# Goal 4: source evaluation and qualification

## 4.1 How main qualifies a source (code read, verified)

**Criteria version:** `oo-source-qualification-3` (`src/catalog/qualification.py:75`). The criteria panel is
`src/analytics/source_audit.py:109-144`.

Two criteria are **extraction-failure** criteria, and only these can disqualify:
- `pathology_rate`: a furniture-repetition signature, with an absolute floor of 0.5 that the code records as never
  reached in the field (`source_audit.py:52`, `:68-81`).
- `link_density_rate`: the share of a source's articles with external links / words ≥ 0.05
  (`src/analytics/source_quality.py:89`). It has **no absolute floor** and fires on the language cohort's tail
  alone (`source_audit.py:126-131`).

Four soft criteria (`outlier_rate`, `furniture_share`, `language_mismatch_rate`, `short_article_rate`) can never
disqualify on their own.

How an extraction-failure criterion flags:
- It flags when the source's value is above its same-language cohort's p90 and the source has ≥ 5 articles of
  that criterion's own evidence (`source_audit.py:589-618`).
- `derive_status` returns `degraded` for an extraction-failure flag alone (`:643-660`). Its docstring still says
  such a signal is "worth review, never yet auto-acted".
- `decide_verdict` turns `degraded` into **disqualified** (`src/catalog/qualification.py:345-355`).

What a verdict does:
- A disqualified source keeps `enabled`, but collection admits only `enabled AND qualified`
  (`src/scheduler/runner.py:512`). **A disqualified source stops being collected.**
- Qualification judges a candidate from as little as **1** stored article (`TRIAL_MIN_ARTICLES`,
  `qualification.py:209-212`).
- There is **no freshness criterion**.
- Catalogue rows start as `qualified` by curation and join the same re-check clock, every 3 months
  (`qualification.py:286`, `:1122-1255`).

External links are counted on the **whole fetched page**, navigation and footer included
(`src/ingest/pipeline.py:330`, `:379-425`). So `link_density_rate` measures a site's template as much as its
articles.

## 4.2 How the rules performed on this data

**Agreement between instances (measured).** Linux A and Linux C each re-checked part of the shipped catalogue
(`scripts/qualification_checks.py`):

| | Linux A | Linux C |
|---|---:|---:|
| measured verdicts (domains) | 200 | 377 |
| disqualified | 130 | 149 |
| judged by both | 173 | 173 |
| same verdict | 170 of 173 | 170 of 173 |
| **disqualified by both** | **110** | **110** |

The instances agree, so the cause is the rule, not the machine.

**Which criterion (inferred by elimination, from complete counts).**
- Of the 110 disqualified-by-both rows, 2 on Linux A have ≥ 5 pathological articles. On Linux C, 0 of the 103
  rows present in its export do.
- Pathology needs ≥ 5 such articles, so **108 of 110 (Linux A) and 103 of 103 (Linux C) were disqualified by
  `link_density_rate` alone.**
- Caveat: this uses today's corpus, not the corpus at verdict time. The `source-audit.json` member that would
  state the criterion directly was skipped on every instance.

**Were they bad sources?**
- The 110 are 108 curated catalogue rows plus 1 academic and 1 official row. By type: 73 news, 23 broadcaster,
  7 magazine, 4 wire agency, 3 other.
- Their random stored article (n = 110 per instance) has a median of 335 / 392 words. 15% / 12% are short or stub,
  against a 13% corpus baseline (quality.md).
- Their random article's link density is **the same as qualified sources'** (`scripts/qualification_checks.py`):

| random article, links/word | n | median | p75 | share ≥ 0.05 |
|---|---:|---:|---:|---:|
| disqualified-by-both, Linux A | 110 | 0.001 | 0.015 | 8% |
| qualified, Linux A | 4,083 | 0.003 | 0.013 | 9% |
| disqualified-by-both, Linux C | 103 | 0.001 | 0.009 | 8% |
| qualified, Linux C | 3,544 | 0.003 | 0.013 | 8% |

- **Read sample:** 20 of the 110 random articles, drawn at random, were read. **19 are normal news articles.** One
  is an extraction failure: raw HTML stored as text.

**Conclusion (likely, with the mechanism verified).** The cohort-tail test flags about the top decile of each
language cohort by construction, wherever its absolute level is. It only needs 5 link-dense articles, which a
large source reaches through its short items on a link-heavy template. So `link_density_rate` alone has
disqualified roughly a hundred mainstream catalogue outlets per re-checking instance, and they are no longer
collected there. **Still present on main** at the lines above.

## 4.3 What actually separates good sources from bad in this data

From the hand-labelled sample (160 sources, quality.md §1.1) and the per-source tables:

| signal | separates? | evidence |
|---|---|---|
| source type: institution / religious / stock exchange / journal vs news, broadcaster, wire | **yes** | 13 of the 18 non-article pages come from institution, religious, stock-exchange and journal source types. News, broadcaster and wire sources are almost all clean or clean-with-furniture. Whether each was discovered rather than curated was not checked per source. |
| freshness of the newest stored article | **yes, strongly** for candidates | 50–54% of instance-qualified candidates have a newest article > 365 days old or undated (table below) |
| has a working feed | **yes** | feed-less catalogue rows: 13–18% ever stored an article |
| link density (whole page) | **no** | same distribution for disqualified and qualified (table above) |
| keyword outlier rate | weak | ~10% of any cohort by construction (the export's own README) |
| article count | weak alone | large sources get the most ≥ 5-article flags |

**Candidates qualified by each instance's own measurement, by age of the newest stored article**
(`scripts/freshness_rule.py`; age = export time minus the newest publisher date):

| instance | candidates | undated | ≤ 30 d | ≤ 90 d | ≤ 180 d | ≤ 365 d | > 365 d | < 5 articles |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Windows | 606 | 111 | 181 | 242 | 268 | 292 | 203 | 57 |
| Linux A | 518 | 108 | 120 | 212 | 235 | 258 | 152 | 78 |
| Linux B | 105 | 17 | 17 | 42 | 48 | 53 | 35 | 21 |
| Linux C | 237 | 48 | 86 | 98 | 103 | 110 | 79 | 84 |

## 4.4 Proposed rules and how they would have classified this data

These are proposals, not code. Each changes a verdict meaning, so each needs a ruling and a criteria-version bump.

**Q-R1. `link_density_rate` stops disqualifying on its own.**
- Treat it like `short_article_rate`: it may make a source `failing` only together with `pathology_rate`.
- Separately, count only links inside the extracted body, not the whole page.
- Effect on this data: the 108 + 103 link-density-only disqualifications become `watch`, so those sources are
  collected again.
- Mistake it makes: the one raw-HTML source in the 20 read would be re-admitted. That case needs its own article
  check (Q-R4), not a link count.

**Q-R2. Freshness.** A candidate qualifies only if its newest stored article is ≤ 180 days old and dated.
- Effect: it keeps 268 / 235 / 48 / 103 of the 606 / 518 / 105 / 237 candidates (44% / 45% / 46% / 43%).
- Mistakes it makes: it rejects slow-publishing institutions and journals, and the undated 17–21% (date
  extraction misses, quality.md). For catalogue re-checks use ≤ 365 days and report, never disqualify, on
  undated sources.

**Q-R3. Minimum evidence.** No verdict from fewer than 5 stored articles. Today it is 1.
- Effect: 57 / 78 / 21 / 84 candidates (9–35%) would stay `unqualified` rather than qualified.

**Q-R4. Article-level non-article check, before any source verdict.**
- Use the hand-labelled categories as a test set: the 18 non-articles, 7 stubs and 3 walls.
- A body detector for raw HTML would catch the one disqualified extraction failure. `<` / `>` density is a simple
  candidate.

## 4.5 What the data could not answer

- The per-criterion verdict of each source: `source-audit.json` was skipped on every instance.
- Any source quality signal that needs an outside truth (accuracy, ownership, reliability). `reliability_score` is
  never computed (`src/database/models.py:437`).
