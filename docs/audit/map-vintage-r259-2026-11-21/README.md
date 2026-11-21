# Every map states its OpenStreetMap date; contested borders render contested (row 259)

The 0.6 gate's exit text (`docs/product/RELEASE_0.6_GATE.md` §1) keeps two of the intake's rows: "the OSM
vintage stated on every map; a contested border rendering as contested." This folder is the proof, walked in
Chromium on 2026-11-21 against the branch's own build.

## Why "every map" holds

There is one world-map renderer, `ooMap` (`src/static/app-map.js`). `tests/test_map_vintage_r259.py` pins it:
no other script loads the world geometry, the contested areas or the OSM border files; the five files that call
`ooMap` are listed, so a new map surface is a visible change; the border-source legend is drawn with no
condition a caller can set; and the contested layer is chosen by the worldview alone.

## What the audit found, and fixed in the same PR

`ooMap` can draw OpenStreetMap data from three places besides the built border files, and two of them drew it
undated:

1. **The OSM lane's object and cluster views** (World map, OSM button, once a country's data is ingested). Only
   the street view stated the extract date and last diff. `src/osm/view.py:view` now returns `vintage` for every
   country whose border box meets the view (read from the country rows, so the cluster view that reads no object
   names it too), and the legend says it on every layer.
2. **The downloaded-region preview** (World map, OSM button, no lane). Its country boundaries replace Natural
   Earth's, yet the legend still said "Borders: Natural Earth 50m", with no date. The preview endpoint now sends
   the extract's own replication date (`X-OO-Region-Extract-Date`, read from the file's header block; `unknown`
   when the file stamps none, never today's date), and both the border legend and the overlay's own line say
   "Offline OSM preview, as of {date}" or "date not stated in the extract". Four new strings, ×12 locales.

## The walk

`walk.js` (Node Playwright) against a plaintext state seeded by `scripts/ui_clickthrough_seed.py`, plus ten
World Bank figures so Governments → Map draws. Two passes:

- **`ne-*`**: no OSM file installed. Legend "Borders: Natural Earth 50m"; all 28 disputed areas of the shipped
  asset hatched, none attributed (the default worldview assigns nothing).
- **`osm-*`**: a hand-made `osm_admin0.json` (five countries, the 28 disputed areas with `held_by: []`, vintage
  2026-10-15) placed in `src/static` for the walk only and removed after, never committed; and the synthetic
  `.osm.pbf` stamped 2026-09-21 as a "done" Africa download. Legend "Borders: OpenStreetMap, as of 2026-10-15 ·
  Natural Earth 50m elsewhere"; the map opens on OSM's convention and every disputed area is still hatched. With
  the OSM overlay on, the legend adds "Offline OSM preview, as of 2026-09-21" and the overlay line reads
  "Offline OSM preview, as of 2026-09-21: 15 nodes · 5 ways · 1 country boundary".

| Surface | Natural Earth pass | OSM pass |
|---|---|---|
| World map | `ne-world-map.jpg` | `osm-world-map.jpg`, `osm-world-map-offline-osm.jpg` |
| Library → World coverage | `ne-library-world-coverage.jpg` | `osm-library-world-coverage.jpg` |
| Governments → Map | `ne-governments-map.jpg` | `osm-governments-map.jpg` |
| Living sources → Law | `ne-living-law-map.jpg` | `osm-living-law-map.jpg` |

`walk.json` holds each surface's legend text, its hover, and the disputed-area counts (drawn, hatched,
attributed, convention). No page error in either pass. Every screenshot is under 200 KB.

**Not reached in the walk**, and covered by the source guard instead: Governments → Statistics, Insights → Map
and → Super-groups, and Living sources → Maps need data the seeded state does not hold (a statistics series, a
concept ring, an ingested OSM country). Each draws through `ooMap`, so it carries the same legend and the same
contested layer.
