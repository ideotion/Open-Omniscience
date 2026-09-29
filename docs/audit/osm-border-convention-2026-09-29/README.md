# OSM's border convention as the default — Chromium record, 2026-09-29 (0.5 row L, S05-05, Q803)

**Chromium-verified (remote sandbox) · awaiting human UX pass.** Chromium through Playwright, the app booted on a
`--mini` seeded plaintext state (`scripts/ui_clickthrough_seed.py`), `OO_NO_SCHEDULER=1`, no saved worldview.

**The OSM files walked are a FIXTURE, not OpenStreetMap data**, built by the real script from
`tests/fixtures/osm/admin_boundaries.osm` with `--vintage 2026-09-01`. Its disputed area «Contested Zone» is
claimed by FR and DE; its «Lone claim» names FR only. Neither lies inside the fixture's France square, so the
build records `held_by: []` for both. They were removed from `src/static/` after the walk; none is committed.

## What was measured (`walk-fixture.json`, 48 observations)

Five surfaces × en, ar × 1440, 768 and 390 px wide. The World map and Library → World coverage drew from their
own data; Governments, Statistics and Insights → Supergroups have no data on this seed, so `ooMap` was rendered
into each of their own hosts with two values (as in the S2 record).

| Check | Result |
|---|---|
| Default on first open | every surface: worldview `osm`, first option «OpenStreetMap's convention, as of 2026-09-01» (ar: «اصطلاح OpenStreetMap، بتاريخ 2026-09-01») |
| Legend | «Contested: 2 · attributed under OpenStreetMap's convention, as of 2026-09-01»; «Borders: OpenStreetMap, as of 2026-09-01 · Natural Earth 50m elsewhere» |
| Both claims | «Contested Zone — contested: France / Germany · inside no country's border in OpenStreetMap, attributed to none»; no `data-iso`, so a click drills into no claimant |
| Single-party claim | «Lone claim — contested: France · OpenStreetMap names only one party · …» |
| The toggle | World map switched to «Natural Earth (de facto)»: Natural Earth's 28 areas, «attributed under Natural Earth (de facto)»; Library → World coverage followed; switched back to OSM's |
| Page errors | none |
| Horizontal overflow | none |

**Held by one country** (`held-world-en-1440.png`): the fixture file with «Contested Zone»'s `held_by` set to
FR by hand, to show that case on screen (the build computing it is pinned in `tests/test_admin_boundaries.py`):
«Contested Zone — contested: France / Germany · attributed to France», with France's `data-iso`.

**Without the files**: the World map opens on «Contested (assign nothing)», no OSM option, «Borders: Natural
Earth 50m»; a saved «osm» choice falls back to `contested`. No page errors.

## Not walked

The real OSM artifacts (the operator's build) and the maintainer's own click-through (Q1128 = a). At 390 px the
map's own control buttons cover much of the map, as before this change; not in this row's scope.
