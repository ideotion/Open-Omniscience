# `docs/research/` — sourced research artifacts (reference, not status)

These files are **committed reference material** for the design entry
**“Statistical-data ingestion + diversified honest visualization (TimesFM, official
statistics, data-viz)”** in [`docs/FUTURE_DEVELOPMENTS.md`](../FUTURE_DEVELOPMENTS.md).
They are **design inputs, not shipped features and not ground truth.**

## Provenance & honesty

- Generated **2026-06-25** by internet-connected research sessions, on the maintainer's
  request, then reviewed in-session. They are kept verbatim so the design entry can link
  to evidence rather than inline the bulk.
- **Verify before trust.** Every catalogue separates a **verified** tier (a live request
  or a verbatim value confirmed this session) from a **scaffold / medium-confidence** tier
  (organisation + URL known but the *exact* endpoint not individually fetched). A scaffold
  row is a **lead to confirm on a networked machine**, never a fact to wire blindly. This
  project has been burned by fabricated endpoints/tags before — the verification clause is
  load-bearing.
- **No scores.** None of these assign a credibility/quality/trust score. Statistical
  producers are **stanced sources** (a producing state has interests); media outlets carry
  **descriptive, contestable** ownership/lean *labels*, never a ranking.
- Country codes were mechanically validated (ISO-3166); a wrong code is worse than none, so
  uncertain ones are null.

## Contents

### `statistics/`
- `timesfm_reliability_report.md` — reliability assessment of TimesFM and the time-series
  foundation-model landscape (Chronos-2, Toto, Moirai, etc.), GIFT-Eval-anchored, dated.
- `producer_directory.md` + `producers.{csv,json}` + `coverage_matrix.json` +
  `machine_endpoint_summary.json` — directory of ~152 official statistical producers
  (national NSOs + IGOs), with confirmed machine endpoints (SDMX / REST-JSON) and a
  per-continent coverage matrix.
- `datasets_catalog_1.yaml` + `datasets_catalog_2_complementary.yaml` — concrete
  queryable indicator/dataset series (World Bank, Eurostat, OECD, IMF, ILO, FAO, WHO,
  OWID, V-Dem, UCDP, BIS, …) with example queries, formats, units, and a
  ready-to-ingest shortlist. Catalogue 2 fixes Catalogue 1's energy + governance gaps.

### `dataviz/`
- `chart_decision_framework.md` — an honest, accessible, no-library chart-type decision
  framework (perceptual ranking + honesty gate + reject list), grounded in
  Cleveland–McGill, Munzner, the FT Visual Vocabulary, and Chartability.
- `honest-charts.js` — zero-dependency, deterministic primitives (scales, nice ticks,
  seeded PRNG, gap-aware paths, binning, five-number summary). MIT.
- `honest-charts.test.mjs` — unit tests (run: `node honest-charts.test.mjs`).
- `chart-schematics.html` — 18 reference SVG schematics (one per recommended technique),
  themeable + RTL + `role="img"` + data tables.
- `check-schematics.mjs` — structural verifier for the schematics
  (run: `node check-schematics.mjs`). Both suites pass as committed.

### `sources/`
- `diversity_catalog_report.md` + `sources.{yml,csv}` — a 105-row gap-fill **news /
  plural-stance** source catalogue for under-represented regions (Caribbean, Pacific,
  sub-Saharan Africa, Central Asia, MENA, S/SE Asia), every row `enabled: false` for
  operator review, in managed languages only. This is the **de-US-centring / source
  diversity** thread, distinct from the statistics threads above.
