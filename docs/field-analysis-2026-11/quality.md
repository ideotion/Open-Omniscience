# Goal 1: article quality

## Method

1. **Automatic flags over every per-source random article** (`scripts/article_quality.py`). The source-samples
   export holds one seeded-random stored article per source: 4,519 / 4,308 / 4,402 / 3,784 sources. The flags are
   simple regex and metadata rules, defined in the script header. They are cheap signals, not verdicts.
2. **Manual reading of 160 of those articles** (`scripts/label_sample.py`, seed 20261128, 40 per instance,
   drawn uniformly over sources). One reader looked at each article's title, its first 170 and last 120
   characters, and its word count and language fields. Every article was put in exactly one category:
   - ok
   - ok + page furniture
   - stub / teaser / paywall
   - consent wall
   - bot wall
   - non-article page
   - reference document (law, expected)

   Wrong language was recorded as an extra flag. The labels are held locally, because they are keyed to article
   ids. The counts below are recomputable from them.
3. Template-like keywords per source (`scripts/keyword_quality.py`).

**Unit.** Every rate in 1 and 2 is **per source**: a small source weighs as much as a large one. It is **not** the
share of articles. Large outlets are mostly clean, so the article-weighted junk rate is lower.

## 1.1 Hand-labelled sample (160 sources, 40 per instance)

| category | Windows | Linux A | Linux B | Linux C | total | share [95% Wilson] |
|---|---:|---:|---:|---:|---:|---:|
| ok | 21 | 24 | 23 | 21 | 89 | 55.6% |
| ok + page furniture (bylines, "read more", related headlines, donation or cookie text in the body) | 13 | 9 | 11 | 7 | 40 | 25.0% [18.9–32.2] |
| stub / teaser / paywall wall | 3 | 2 | 0 | 2 | 7 | 4.4% |
| consent wall | 0 | 1 | 0 | 1 | 2 | 1.2% |
| bot-check wall | 0 | 0 | 0 | 1 | 1 | 0.6% |
| non-article page (home, listing, product, "about us", navigation shell, template placeholder) | 2 | 3 | 6 | 7 | 18 | 11.2% [7.2–17.1] |
| reference document (law; expected for that source type) | 1 | 1 | 0 | 1 | 3 | 1.9% |
| **junk** (stub + walls + non-article) | 5 | 6 | 6 | 11 | 28 | **17.5% [12.4–24.1]** |
| stated language contradicted by the text (extra flag) | 0 | 1 | 0 | 4 | 5 | 3.1% [1.3–7.1] |

- **None of the 28 junk articles was quarantined** (all 160 had `quarantined = false`).
- 13 of the 18 non-article pages come from institution, religious, stock-exchange and journal source types
  (journal sites whose page shell was stored instead of the paper). Examples include a ministry "News" listing, a
  parish home page, a site-builder event placeholder whose text was never filled in, an exchange's "about us" page,
  and a journal article page holding only its tab labels.
- Page furniture is the most common defect: **31% of the usable articles** (40 of 129) carry it. Typical cases:
  - a public broadcaster that appends the same programme teaser to every article;
  - consortium journals that end every paper with "Total abstract views / Total article views";
  - news sites that close with "LEE TAMBIÉN", "LIRE LA SUITE" or "Allerede abonnent? Logg inn".
- **What the reading does not support.** The automatic flag `ends_mid_sentence` (28–30% on every instance) is
  **not truncation**. In a read of 25 such endings, the body ends in a byline, credits, contact lines, metadata or
  related headlines. The real truncation markers ("…", "Continue reading") occur on 1.1–1.5% of sources.

The four instances do not differ beyond sampling noise: junk 5–11 of 40, furniture 7–13 of 40. So this is a
property of the catalogue and the extractor, not of one machine.

## 1.2 Automatic flags over all sampled sources

| flag (per source; script header has the rule) | Windows | Linux A | Linux B | Linux C |
|---|---:|---:|---:|---:|
| n | 4,519 | 4,308 | 4,402 | 3,784 |
| words < 50 | 4.0% | 5.1% | 4.6% | 4.5% |
| words < 100 | 12.5% | 13.4% | 12.8% | 13.2% |
| paywall phrase and < 400 words | 1.6% | 2.0% | 2.0% | 2.1% |
| consent / login / JS / error-page phrase and < 400 words | 0.1% | 0.2% | 0.3% | 0.3% |
| published_at missing | 8.9% | 9.0% | 8.3% | 6.6% |
| published_at > 365 days before storage | 8.8% | 7.8% | 7.4% | 6.4% |
| published_at after storage + 1 day | 0 | 0 | 0 | 0 |
| published_at within 120 s of storage (fetch-time look) | 0.3% | 0.2% | 0.2% | 0.4% |
| no stated language (article and source) | 11.9% | 9.5% | 5.9% | 6.2% |
| script of the text contradicts the stated language | 1.1% | 1.0% | 1.0% | 1.0% |
| a ≥8-word sentence repeated ≥3 times | 0.7% | 1.1% | 0.7% | 0.7% |
| title generic ("Home", "News", "404"…) or equal to the source name | 0.5% | 0.5% | 0.5% | 0.3% |
| quarantined (sample may pick one) | 0.0% | 0.9% | 0.0% | 2.2% |

The app's own pre-labels on the random control (`sample_articles.jsonl`, `selection_method` contains
`random_per_source`) fire on 10.9% / 11.0% / 13.4% / 11.1% of sources. That is below the 17.5% junk rate from
reading, and they fire on different articles. Their link-density label counts navigation links, which is why it
also fires on clean articles (see source-qualification.md §4.2).

### Dates

- **Measured.** 6.6–9.0% of sampled sources have an article with no publication date, and 6.4–8.8% have one dated
  more than a year before it was stored. None is in the future.
- **Code.** `published_at` comes only from trafilatura's page metadata (`src/ingest/extract.py:237`). The feed
  entry's own date is discarded: only `entry.link` is kept (`src/ingest/pipeline.py:765`). Nothing records where a
  date came from.
- **Inferred, not measured.** Some of the >1-year dates are genuine (journals, archives, the backup import on
  Linux B). This data cannot separate those from wrong dates. Open PR #2031 (held) stops an import day from being
  read as a publication date. That is a different case.

### Language

- **Code.** `Article.language = doc.language or source.language` (`src/ingest/pipeline.py:297`). trafilatura
  fills `doc.language` only when its detector is on (`src/ingest/extract.py:235-236`). So in practice an article
  takes its **source's catalogue language**.
- **Measured.** 23 catalogue entries declare a language whose script never matches what they publish, on most of
  12 snapshots (catalogue.md §3). Every article from them is stored under the wrong language, which skews the
  keyword stopwords, the language cohorts used by qualification, and the language filters.
- **Measured.** 6–12% of sampled sources carry no language at all, mostly discovered sources.

## 1.3 Keyword quality

A top-12 term found on at least half of a source's articles is counted as template-like. This is the same
structural rule as main's read-time `outlet_furniture` (`MIN_SHARE = 0.5`, `src/analytics/outlet_furniture.py`).
Counted over audited sources with ≥20 articles:

| | Windows | Linux A | Linux B* | Linux C |
|---|---:|---:|---:|---:|
| sources | 3,178 | 3,104 | 3,408 | 2,456 |
| with ≥1 template-like top-12 term | 73.8% | 72.6% | 23.4%* | 72.1% |
| template-like terms per source (mean, of 12) | 3.73 | 3.61 | 1.23* | 3.68 |

\*Linux B is 35% keyword-indexed, so its counts are not comparable.

The most frequent template-like terms, summed over instances, include:
- **paywall wall words indexed as keywords:** `allerede` (155 source rows), `tilaajille` (58);
- **journal page furniture:** `DOI`/`doi` (445), `journal`, `license`, `creative`, `commons`, `abstract`, `citecite`
  (a doubled tab label);
- **navigation and site words:** `email`, `share`, `alert`, `google`, `post`, `category`.

A single-topic outlet's topic word also passes this rule, so these are candidates, not verdicts.

**Fixed on main?** Only partly. Main leaves outlet-repeated text out of near-duplicate grouping and "Related"
**at read time** (`src/analytics/outlet_furniture.py`, used at `src/api/main.py:3382-3393` and `:3499`). Stored
text, word counts and the keyword index still include it, so trends, keyword counts and source fingerprints are
still affected. Any change to what is indexed changes the keyword engine id and re-indexes every install
(`src/analytics/engine_identity.py`). That is why it stays a proposal (P9 in SUMMARY.md).

## Causes

| finding | cause | status |
|---|---|---|
| non-article pages stored and not quarantined | The door rules only catch bodies under 100 words with a homepage, section or pagination URL shape, or a boilerplate wall under 40 words (`src/ingest/non_article.py:168-241`). The prose gate needs function-word density < 0.12 **and** punctuation < 0.01 (`src/services/prose_gate.py`). Institution pages with real sentences pass both. | verified (code), likely (that this is why each case passed) |
| page furniture inside bodies | trafilatura output is stored as-is. Only a closed list of ad placeholders and banners and a leading nav run are removed (`src/ingest/furniture.py:34-47`, `src/ingest/page_notices.py:129-199`). | verified |
| paywall stubs | stored when ≥ 200 characters remain (`src/ingest/extract.py:45`). `paywall_stub` quarantine is opt-in, default off (`src/analytics/quarantine_job.py:159`). | verified |
| wrong language | catalogue language fallback (`src/ingest/pipeline.py:297`) | verified |
| missing dates | metadata-only date, feed date discarded | verified |
