# Insights — keyword & entity analytics

## Intent

Turn the unified corpus from a search box into an analytical instrument. Keywords
and entities are extracted from **ingested article text**, stored with their
occurrences and context, and surfaced so an investigative journalist can ask:
*what is being talked about, where, when, by whom, and together with what?*

Everything here is a **real aggregate** over stored data with a stated method and
sample size — never a fabricated score (PRODUCT_SYNTHESIS §3.5).

## How it works

```
ingest an article ──► extract (baseline / opt-in spaCy) ──► KeywordMention rows
                          terms + entities, offsets        (count + first offset +
                                                            denormalised date/country/city)
                                                                   │
                          Insights tab / /api/insights  ◄──────────┘
                          trends · associations (PMI) · context · map
```

- **Extraction** (`src/analytics/extract.py`): topical n-gram **terms**
  (stopword-filtered) plus **entities** — people, companies/orgs, places — as
  single units. The baseline (no dependencies) detects entities as multi-word
  Title-Case sequences and assigns a `person`/`org`/`location` kind only from a
  gazetteer (otherwise the honest generic `entity`); an opt-in **spaCy** `[nlp]`
  extra adds real `PERSON`/`ORG`/`GPE` NER. Every keyword records **which extractor
  labelled it** — an entity type is a *labelled-by-X assertion*, not ground truth.
  Best for space-delimited scripts; CJK/Arabic segmentation is a known later step.
- **Storage** (`src/analytics/store.py`): one `KeywordMention` per (article,
  keyword) — occurrence count + first char offset (the context sentence is sliced
  from the stored article on read, so the DB stays lean) + denormalised
  `observed_on` / `country` / `city` from the source. Indexing runs best-effort at
  ingest (fast baseline, fail-open) and can be **back-filled** over the existing
  corpus from the Insights tab ("Index corpus").

## Functions (Insights tab + `/api/insights`)

| View | Endpoint | What it shows |
|------|----------|---------------|
| Explore — trend | `GET /trend?term=&bucket=` | Mention volume over time (day/week/month), with the resolved keyword + kind |
| Explore — mind-map | `GET /associations?term=` | Co-occurring keywords ranked by **PMI** (pointwise mutual information) with sample sizes + a "association ≠ causation" caveat; click a node to recenter |
| Explore — context | `GET /context?term=` | Recent mention snippets sliced from article text, with article/source links + country/city/date |
| Trends | `GET /trending`, `GET /top` | Rising terms (recent-vs-prior **ratio**, a labelled measure) and top terms, filterable by window / kind / country |
| Map | `GET /map?days=&kind=` | Top keywords **per country and per city** (source-based region signal) |
| Indexing | `GET /status`, `POST /reindex?limit=` | Indexed/remaining counts; chunked corpus backfill |

`kind` filters: `term`, `entity`, `person`, `org`, `location`.

## Honesty guarantees

- Trends/top are real counts; "rising" is a defined recent-vs-prior **ratio**,
  explicitly *not* a significance test.
- Associations use **PMI** over article co-occurrence, returned with `n` and the
  caveat that small samples are noisy.
- Entity kinds carry extractor provenance; the baseline never claims a precise
  person/org/place type it cannot justify.
- Region on the map is the **source's** country/city (the reliable signal). A
  graphical zoomable map with city pins (needing a coordinate gazetteer) is the
  documented next step; today the Map view is live tables.
