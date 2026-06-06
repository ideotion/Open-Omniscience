# Worldwide source catalog — strategy & runbook

Goal: cover the news media **and** official political institutions of **every
country**, so the corpus approximates a genuine digital world view. Social
networks are out of scope for now. The guiding constraint is the project's: the
list must be **real, attributable and refreshable**, not guessed.

## Why data-derived (not hand-typed)

Hand-typing thousands of domains produces wrong/dead entries and can never reach
true global completeness. Instead the catalog is **generated from Wikidata**
(CC0, machine-readable), which has, per entity: an *official website* (P856), a
*country* (P17 / ISO code P297) and a *language* (P407). That's an honest,
attributable backbone we can regenerate on demand and audit.

## How it works

```
configs/catalog_query.yml      # which Wikidata TYPES count as a source (editable)
        │
        ▼
scripts/build_world_news_catalog.py   # queries Wikidata per country (needs network)
        │   • src/catalog/wikidata.py   build per-country SPARQL (keyed on ISO P297)
        │   • src/catalog/normalize.py  registrable domain · drop social hosts · dedup
        │   • src/catalog/build.py      orchestrate · resilient per-country · emit YAML
        ▼
configs/world_news_sources.yml  # generated catalog (seeder picks it up automatically)
        │
        ▼
seed_default_sources()          # merges it with sources.yml + markets_sources.yml,
                                # deduping by domain → the unified store
```

The pure logic (query building, parsing, normalisation, dedup, coverage) is
unit-tested with fixtures and runs anywhere. Only the *fetch* needs network, so it
lives in the CLI — run it on a networked machine/CI; the app sandbox may be egress
restricted.

## Running it

```bash
# Full run (all ISO countries × the configured source types):
python scripts/build_world_news_catalog.py

# A subset while iterating, or a dry run (prints stats, writes nothing):
python scripts/build_world_news_catalog.py --countries fr,jp,ke,br --dry-run
python scripts/build_world_news_catalog.py --source-types news

# Fold in an external export (GDELT / Media Cloud) — a CSV with a url/domain
# column plus optional name/country/language:
python scripts/build_world_news_catalog.py --merge-csv mediacloud_sources.csv
```

It excludes social networks and any domain already shipped in `configs/sources.yml`
or `configs/markets_sources.yml`, then writes `configs/world_news_sources.yml` and
prints a country-coverage summary. Be polite: `--delay` (default 1s) spaces out
Wikidata queries.

## Tuning what counts as a source

Edit `configs/catalog_query.yml`. Each spec is a `source_type` + a list of
Wikidata **type item-ids** (subtypes are included automatically). The news ids are
well-established; **verify the institution ids** on <https://www.wikidata.org> for
your needs before a full run — a wrong id simply returns fewer rows, never fake
data. To add a concept: search it on Wikidata, copy its `Q…` id into a spec.

## Augmenting beyond Wikidata

Wikidata misses some small/local outlets. Comparable open sources to fold in via
`--merge-csv`:

- **GDELT** monitored-domain lists — <https://www.gdeltproject.org/>
- **Media Cloud** country source collections — <https://www.mediacloud.org/>
- Any institutional registry you trust, exported to CSV.

## Measuring progress

`GET /api/database/coverage` (and the **Sources & Database → World coverage**
panel) report covered vs total countries, the **missing** country codes, and the
**thin** ones (covered but with very few sources) — computed from the data. Use
the missing/thin lists to target the next generation run (`--countries …`).

## Ethics

Same rules as all ingestion: only public data, robots.txt respected (fail-closed)
and rate-limited at fetch time. The catalog stores only metadata (name, domain,
country, language); nothing is fetched until an ingest runs.
