# OSM boundaries on the five maps — Chromium record, 2026-09-29 (0.5 row E, S05-05 S2)

**Chromium-verified (remote sandbox) · awaiting human UX pass.** Chromium 1194 through Playwright,
the app booted on a `--mini` seeded plaintext state (`scripts/ui_clickthrough_seed.py`), `OO_NO_SCHEDULER=1`.

**The artifact walked is a FIXTURE, not OpenStreetMap data.** No OSM host is reachable from the sandbox
(`download.geofabrik.de`, `planet.openstreetmap.org` and `overpass-api.de` all answer the proxy's 403), so the
two files were built by the real script from `tests/fixtures/osm/admin_boundaries.osm`:

```
python scripts/build_admin_boundaries.py tests/fixtures/osm/admin_boundaries.osm --vintage 2026-09-01
```

That fixture holds one square "France" (admin_level=2, `ISO3166-1:alpha2=FR`), one region tagged `FR-IDF`, one
untagged region, one disputed area claimed by FR and DE and one claim naming FR alone. The squares are what the
screenshots show over Western Europe. The files were removed from `src/static/` after the walk; none is committed.

## What was measured

Five surfaces × en, ar × 1440, 768 and 390 px wide (30 observations, `walk.json`). The World map and the
Library → World coverage map rendered from their own data. Governments → Map, Statistics and Insights →
Supergroups have no data on this seed (the 2026-09-16 record found the same), so the walk rendered the shared
`ooMap` into each of their own hosts with two values; that proves the component, not those loaders.

| Check | Result |
|---|---|
| Country paths | 229 on every surface (Natural Earth's 229, France replaced by the artifact's polygon) |
| Region outlines | 2 on every surface, drawn after the last country fill and before the first contested area |
| Region hover | `Île-de-France (FR-IDF) · France — Sources: 130`; the untagged one names its OSM relation and "no ISO 3166-2 code in OpenStreetMap"; both carry the country's `data-iso`, so a click still drills into France |
| Legend | `Borders: OpenStreetMap, as of 2026-09-01 · Natural Earth 50m elsewhere` (en) and its Arabic line; the hover gives the ODbL attribution and the counts |
| Contested layer | 28 Natural Earth areas, unchanged (the OSM contested areas stay in the artifact until row L) |
| Regions toggle | 2 → 0 → 2 outlines, on every width and language |
| Page errors | none |
| Horizontal overflow | none |

Without the files (`fallback-en.png`): 229 countries, no region layer, no Regions button, legend
`Borders: Natural Earth 50m` / `الحدود: Natural Earth 50m`, no page errors.

## Not walked

The real artifacts (the operator's build), the admin-1 choropleth and the ranked table (S3, not built), and the
maintainer's own click-through (Q1128 = a).
