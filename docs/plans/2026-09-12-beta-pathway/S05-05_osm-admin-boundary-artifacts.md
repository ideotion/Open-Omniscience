# S05-05 — OSM-derived admin-0 / admin-1 artifacts keyed ISO 3166-2 · 0.5, `RELEASE_0.5_GATE.md` row E

> **Scope:** the OSM preprocessing bridge (`scripts/build_country_polygons.py` lineage, which today builds
> `src/static/world_countries.json` from Natural Earth 110m), a new admin-0 (alpha-3) + admin-1 (ISO 3166-2)
> artifact set with registry entries and a freshness test, rendering on all five map surfaces through 0.4
> row R's one `project(lon, lat)` seam, choropleths by alpha-3 and admin-1 with the ranked table in full,
> the vintage stated, contested borders CONTESTED with both claims. Must NOT touch: the projection seam
> itself (0.4 row R), WebGL (no-WebGL is firm), the OSM lane's ingest (S05-04 — the artifact build reads OSM
> data on the maintainer's machine, not through the lane), any export member (Q823 ⛔).
> **Implements:** Q314, Q804 [ASSUMPTION], Q816; via the gate row: Q802 (second half), Q826.
> **Gated on:** 0.4 row R (Equal Earth, NE 50m, the CONTESTED convention, the worldview toggle); 0.4 row L
> (alpha-3 display); S05-02 (alpha-3 in the store, so choropleth joins key alpha-3).
> **Sequencing:** after 0.4 row R; the operator's artifact build before the surfaces can render; S05-04's
> tag completeness per admin-1 (Q815 · 1) and S05-07's amendment map (Q914 · 4) consume these artifacts.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (their verified context and option lists). Grep the tree before building
anything — the sheet's anchors were verified at `main`@`bebcef4` on 2026-09-12 and may have moved.

## 1. The rulings this slice implements — verbatim, by ID

- **Q314** — **(a)** «(a) ISO 3166-2 (`FR-75`, `US-CA`) where OSM carries the `ISO3166-2` tag; the OSM
  relation id as the fallback identity.»
- **Q804** — **(a)** «(a) OSM `admin_level=4` relations → shipped artifacts keyed ISO 3166-2 (Q314),
  rendered on all five surfaces from 0.5.» [ASSUMPTION — blank, the sheet's default; reversible at any time]
- **Q816** — **(a)** «(a) Choropleths by alpha-3 and admin-1 on Equal Earth + the ranked table in full (the
  Observatory rule: the table is canonical), the vintage stated.»
- Carried by the gate row: **Q802 = (a)** «Natural Earth 50m now (a few hundred KB more; the 110m polygons
  facet under the polar shear), OSM-derived admin-0/admin-1 artifacts from 0.5 replacing it.» — the second
  half is this slice; **Q826 = (a)** «Rendered CONTESTED with both claims, never a silent pick; confirm.»

## 2. Where this stands in the tree — the staleness guard, with anchors

- `src/static/world_countries.json` is Natural Earth 110m, 175 countries keyed alpha-2, ~75 microstates as
  gazetteer points, **no admin-1** (sheet §9 VERIFIED); `scripts/build_country_polygons.py` "Build the
  offline country-polygons asset" (grep-verified head); `app-map.js:1233` draws "Country (admin_level=2)
  boundary polygons, keyed by ISO 3166-1 alpha-2" (grep-verified).
- No `ISO3166-2` anywhere in `src/` or `configs/` (grep-verified in this brief: `grep -rn 'ISO3166-2' src/
  configs/` → nothing); the only admin-level code is the browser-side `src/static/osmpbf.js:227–242`
  assembling `admin_level=2` polygons from a ≤ 8 MB prefix (grep-verified; sheet §9 VERIFIED).
- The projection is plate carrée at `src/static/app-map.js:21–24` (sheet VERIFIED; grep-verified) and
  Equal Earth is not in the tree (grep-verified: `grep -rn -i 'equal.earth' src/static/*.js` → nothing) —
  0.4 row R builds it; its coefficients are FROM MEMORY in the sheet and 0.4 row R must confirm them
  against a published source before this slice renders anything on them.
- Registry: the `natural-earth-geometry` entry at `configs/external_artifacts.yml:527–537` pins
  `src/static/world_countries.json` (sha256 blank, `refresh: python scripts/build_country_polygons.py ; …`,
  `freshness: {policy: rarely}`, `last_verified: "2026-06-18"`; grep-verified) — the entry the new artifacts
  replace or sit beside; `tests/test_external_freshness.py` (`test_every_as_of_constant_is_registered`,
  `test_nothing_is_stale`; grep-verified `def` names).
- Invariant #31(c) (`CLAUDE.md`): the ranked table renders in FULL beside the picture and is the canonical
  view — the Observatory rule Q816 imports onto the map surfaces.
- Not verified anywhere in the sheet: how many `admin_level=4` relations carry `ISO3166-2` — the build
  counts tagged vs fallback-keyed relations and reports the gap (never silently keys everything by id).
- Tests present: `tests/test_countries_geo.py`, `tests/test_ui_ring_map.py`, `test_ui_map_time_scale.py`.

## 3. Slices — what to build, in order

### S1 — The artifact build (session-written, operator-run)
- **What:** the bridge extended to emit admin-0 keyed alpha-3 (through `to_iso3` from the OSM
  `ISO3166-1:alpha2` tag — the external contract stays alpha-2 behind the converter, Q304) and admin-1 from
  `admin_level=4` relations keyed ISO 3166-2 where tagged, the relation id as the fallback identity, both
  counts reported (Q314); geometry simplified to published vertex budgets (Q822's caps); the extract's date
  embedded as the vintage; contested areas carried with both claims (Q826); registry entries with sha256
  and `last_verified`; a freshness test.
- **Why (ruling):** Q314, Q804 [ASSUMPTION], Q802, Q826.
- **Acceptance:** the artifacts with registry entries and a green freshness test; the tagged / fallback
  counts in the PR body; a geometry fixture (one country with admin-1, one untagged relation, one contested
  area) proving key assignment, fallback and both claims.

### S2 — Rendering from the artifacts on all five surfaces (Q804 [ASSUMPTION], Q802)
- **What:** the five map surfaces of 0.4 row R (its click-through record names them) read the OSM-derived
  artifacts instead of Natural Earth; the vintage in the legend beside "Equal Earth · equal-area"; admin-1
  drawn within the LOD budget, degrading to fewer vertices, never to a frozen tab (Q822); CONTESTED both
  claims (Q826).
- **Acceptance:** the Chromium record across the five surfaces; the `world_countries.json` count test of
  0.4 row R still pins the inventory or is re-pinned in the same PR with the reason.

### S3 — Choropleths by alpha-3 and admin-1 with the canonical table (Q816)
- **What:** choropleths on Equal Earth through the one seam; beside every choropleth the ranked table in
  FULL (never truncated; invariant #31(c)); the vintage stated; counts only, n shown; one measure per
  channel; a region with no data rendered as "no data", never as 0.
- **Acceptance:** a test asserting the table is never capped; the negative-space fixture (a region absent
  from the data renders the gap); the Chromium record in `en` and `ar`.

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured. Plus: the
registry and freshness tests; the S1 geometry fixture; the vertex-budget test (no polygon above the published
cap); the whole-tree guard set (a new artifact file reddens tree-scanning guards — run the named set);
`node --check` on touched scripts; the three i18n gates for the legend and hover strings ×12; the Chromium
click-through of the five surfaces at the three widths of the 2026-09-09 sweep (the audit's viewport table in
`docs/audit/11_VISUAL_UI_AUDIT_2026-09-08.md` names 375 × 812, 768 × 1024, 1024 × 800, 1440 × 900 and
1920 × 1080 — the session reads the sweep record for the three it used), in `en` and `ar`, stamped
"Chromium-verified (remote sandbox) · awaiting human UX pass".

## 5. Operator steps

1. The networked artifact build on the maintainer's machine (the bridge reads an OSM extract or the planet
   file) → the admin-0 / admin-1 artifacts, their sha256 in the registry, `last_verified` set.
2. The click-through of the five surfaces (Q1128 = a) → the record on the PR.

## 6. What this slice may not decide

- Q804 is an ASSUMPTION (blank, the sheet's default) — the PR body names it so it can be reversed.
- The artifact format and size budget — the sheet gives "a few hundred KB more" for NE 50m; the OSM-derived
  set is measured, then stated; no compression scheme is chosen without the number.
- Which countries' admin-1 ship in 0.5 (every country, or the ingested ones) — the ruling says "shipped
  artifacts", not the coverage; asked in the PR body.
- The LOD caps' numbers (Q822 says published; they are measured first, then published).
- A repo-shipped OSM-derived artifact is a redistribution: the registry `license` line carries the ODbL
  attribution; whether Q823 ⛔ reaches repo-shipped artifacts is recorded as a question, never decided here.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.5_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every §1 ruling in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
