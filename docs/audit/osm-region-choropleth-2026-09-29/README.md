# The ranked table and the region choropleth — Chromium record, 2026-09-29 (0.5 row E, S05-05 S3)

**Chromium-verified (remote sandbox) · awaiting human UX pass.** Chromium through Playwright, the app booted on a
`--mini` seeded plaintext state (`scripts/ui_clickthrough_seed.py`), `OO_NO_SCHEDULER=1`.

**The boundary files walked are a FIXTURE, not OpenStreetMap data**, built by the real script exactly as in the
S2 record (`docs/audit/osm-boundaries-clickthrough-2026-09-29/`): one square France, one region tagged `FR-IDF`,
one untagged region (`r1003`). They were removed from `src/static/` after the walk; none is committed.

## What was measured

Five renders × en, ar × 1440, 768 and 390 px wide (30 observations, `walk.json`): the World map by country and by
continent, Library → World coverage, and two direct `ooMap` renders into the World map's host with
`regionValues: {"FR-IDF": 5}`, one with the boundary files and one without. No map surface feeds region values
yet, so the region renders prove the component, not a loader. Governments → Map, Statistics and Insights →
Supergroups have no data on this seed; they draw through the same `ooMap` and its table.

| Check | Result |
|---|---|
| World map, by country | 209 table rows = 209 countries with a value; «27 areas with no data» under it, named in the hover |
| World map, by continent | 7 rows, one per continent (not one per country) |
| Library → World coverage | 4 rows = 4 countries with articles; «225 areas with no data» |
| Region mode | `FR-IDF` filled by its value; `r1003`, absent from the data, drawn with the no-data hatch and «no data» in its hover; «1 area with no data» under a one-row table; no Regions button |
| Region mode, no boundary files | no region drawn; the caveat «This measure is by region, but the region boundaries are not built on this install yet: the table below holds every value.»; the table still holds the value |
| Arabic | summary, count lines and caveat in Arabic; the table reads right to left |
| Page errors | none |
| Horizontal overflow | none (the table is the host's width at every width) |

`region-en-1440.png` and `region-ar-390.png` show the region render.

## Not walked

The real artifacts (the operator's build), a real region-valued producer (none exists yet), and the maintainer's
own click-through (Q1128 = a).
