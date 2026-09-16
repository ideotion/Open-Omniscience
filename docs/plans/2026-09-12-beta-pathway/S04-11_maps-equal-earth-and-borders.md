# S04-11 — Maps: Equal Earth and the borders · 0.4, `RELEASE_0.4_GATE.md` row R

> **Scope:** `src/static/app-map.js` (the projection seam, graticule, viewBox maths, legend), every
> `lon2x` / `lat2y` / `ooMap` call site in `src/static/app-*.js` and `osmpbf.js`,
> `src/static/world_countries.json` + `scripts/build_country_polygons.py` (Natural Earth 50m), the
> `natural-earth-geometry` entry in `configs/external_artifacts.yml`, the CONTESTED layer and the worldview
> toggle, `tests/test_countries_geo.py`.
> It must NOT: build OSM-derived admin-0 / admin-1 artifacts (0.5, S05-05), the Place entity, admin-1, WebGL
> (the no-WebGL ruling is firm), street-level detail, or remove the ooMap embed on When / Where (the gate row
> says it stays, Q1150).
> **Implements:** Q801, Q802, Q803 (note: toggles, OSM's convention as the default), Q826.
> **Gated on:** the Equal Earth coefficients are FROM MEMORY in the sheet and must be confirmed (proj.org is on
> row V's allowlist list; else the maintainer supplies them); the 50m rebuild needs naturalearthdata.com or the
> maintainer's machine. No ⛔.
> **Sequencing:** S04-09's wiki map layer and S04-05's alpha-3 display ride the seam this slice makes — land the
> seam first; S05-05 replaces the geometry later through the same seam.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (§9 — its VERIFIED context, the SEARCH-VERIFIED UN vote, the FROM MEMORY
projection). Grep the tree before building anything — the sheet's anchors were verified at `main`@`bebcef4`
on 2026-09-12 and may have moved; this brief re-checked them at `7ca142e`.

## 1. The rulings this slice implements — verbatim, by ID

- **Q801** — **(a)** «Equal Earth on all five map surfaces through the one `project(lon, lat)` seam, no
  toggle, named in the legend ("Equal Earth · equal-area").»
- **Q802** — **(a)** «Natural Earth 50m now (a few hundred KB more; the 110m polygons facet under the polar
  shear), OSM-derived admin-0/admin-1 artifacts from 0.5 replacing it.» [placement: NE 50m in 0.4; the
  OSM-derived artifacts = S05-05]
- **Q803** — **(a)** «OSM's convention as of `<date>`, with every disputed area rendered CONTESTED showing
  both claims (the 2026-07-13 ruling), the convention named in the legend.» — NOTE (verbatim): «but users
  should be able to see difference with toggles ; the app should start with OSM's convention as of `<date>`
  as default»
- **Q826** — **(a)** «Rendered CONTESTED with both claims, never a silent pick; confirm.»

## 2. Where this stands in the tree — the staleness guard, with anchors

- The one projection is equirectangular at `app-map.js:21–24` (sheet VERIFIED; confirmed: `MAP_W = 720,
  MAP_H = 360`, `lon2x`, `lat2y`) — plate carrée, NOT Mercator (the 2026-09-12 lesson in `LESSONS.md`:
  "VERIFY A PREMISE IN BOTH DIRECTIONS"). The sheet counts nine `lon2x` / `lat2y` call sites; grep-verified
  today: 18 lines outside the two definitions
  (`grep -rn "lon2x\|lat2y" src/static/*.js | grep -v "const lon2x\|const lat2y"`) — recount before routing.
  **CORRECTED 2026-09-16 by the executing session (S04-11): the COUNT was right and the FILE LIST was
  wrong.** This paragraph previously named nine files (`app-boot.js`, `app-gov-law.js`, `app-insights.js`,
  `app-library.js`, `app-map.js`, `app-markets.js`, `app-shell.js`, `app-sources.js`, `osmpbf.js`); all
  **18 sites are in `app-map.js` alone**, and eight of the nine named files contain no projection
  arithmetic whatsoever (appending `| awk -F: '{print $1}' | sort -u` to the very command quoted above
  returns one path). A count and a breakdown come from DIFFERENT commands, so reproducing the quoted
  count corroborated only itself — recorded in `LESSONS.md` as "A BRIEF CAN BE RIGHT ABOUT THE COUNT
  AND WRONG ABOUT THE BREAKDOWN". Widening the sweep to the projection PRIMITIVE rather than the two
  names did find one thing the file list missed: an orphaned `// World map: equirectangular projection`
  comment stranded at the end of `app-corpus.js` by the module split, describing code that now lives in
  `app-map.js` (removed in the same PR).
- The five surfaces = the five `ooMap(host, …)` call sites — grep-verified: `app-gov-law.js:565`,
  `app-insights.js:478`, `app-map.js:965`, `app-map.js:1944`, `app-sources.js:43` (`grep -n "ooMap(host"
  src/static/app-*.js`); the definition is `app-map.js:313`.
- Geometry: `src/static/world_countries.json` = Natural Earth 110m, 175 countries, keyed alpha-2; ~75
  microstates drawn as gazetteer points; no admin-1 (sheet VERIFIED). The registry entry
  `natural-earth-geometry` at `configs/external_artifacts.yml:527–537` describes the 110m files and carries
  `pin: {path: src/static/world_countries.json, sha256: ""}` — a BLANK digest — with refresh scripts
  `scripts/build_country_polygons.py` and `scripts/build_world_outline.py` (grep-verified).
- The count test: `tests/test_countries_geo.py::test_bundled_asset_shape_and_coverage` asserts ≥ 150
  countries, `precision == 1`, and rings for thirteen named codes — grep-verified (`grep -n "^def test_"
  tests/test_countries_geo.py`); `tests/test_repo_invariants.py:4482` asserts ooMap loads
  `/static/world_countries.json`.
- CONTESTED rendering is ABSENT — grep-verified: `grep -rn -i "contested" src/static/app-map.js src/geo/`
  returns nothing; the legend code sits at `app-map.js:502–531`.
- Equal Earth (sheet, FROM MEMORY — proj.org was egress-blocked; confirm before shipping): θ = asin((√3/2)·sin
  φ); x = (2√3/3)·λ·cos θ / (9A₄θ⁸ + 7A₃θ⁶ + 3A₂θ² + A₁); y = A₁θ + A₂θ³ + A₃θ⁷ + A₄θ⁹; A₁ = 1.340264,
  A₂ = −0.081106, A₃ = 0.000893, A₄ = 0.003796; aspect ≈ 2.05:1; no closed-form inverse (Newton iteration).
- Borders (sheet): OSM draws by its "on the ground" rule and keeps disputed claims as separate relations;
  Natural Earth follows a de-facto policy of its own. The OSM-derived boundary artifacts do not exist (sheet
  VERIFIED: no Python PBF reader, no stored features) and are 0.5.
- The UN "Correct the Map" resolution of 2026-09-04 is SEARCH-VERIFIED context, not a requirement.

## 3. Slices — what to build, in order

### S1 — The `project(lon, lat)` seam
- **What:** ONE function `project(lon, lat)` (and its Newton inverse for pointer → lon/lat readouts and
  drilling) replacing `lon2x` / `lat2y` at every call site, including the marker, library, markets, shell,
  boot and `osmpbf.js` overlay users; Equal Earth with coefficients CONFIRMED against a published source
  (recorded with its tier and a registry entry if the source is dated); the box becomes the projection's own
  aspect instead of 720 × 360; the graticule is drawn curved; the viewBox zoom / pan maths follow; the legend
  names "Equal Earth · equal-area" (×12); NO projection toggle.
- **Why (ruling):** Q801 (one truth, no toggle).
- **Acceptance:** a node test that no residual `lon2x` / `lat2y` arithmetic survives outside the seam; the five
  surfaces render on Equal Earth in a Chromium click-through record with the legend visible.
- **May not decide:** anything about the geometry source (S2) or a second projection.

### S2 — Natural Earth 50m
- **What:** rebuild `world_countries.json` (and the outline) from the 50m admin-0 set through the existing
  build scripts on a machine that can reach naturalearthdata.com (probe first; else operator); update the
  registry entry (description, `last_verified`, and FILL the blank `sha256` pin — the registry rule requires
  it in the same commit); state the size delta in the PR (the label says "a few hundred KB more"); keep the
  gazetteer-point fallback for microstates; the asset stays alpha-2 keyed behind converters in 0.4 (row L,
  Q311 — the storage flip is 0.5).
- **Why (ruling):** Q802.
- **Acceptance:** `test_bundled_asset_shape_and_coverage` still pins the inventory (gate); the count of
  countries and rings before / after quoted in the PR.

### S3 — Borders: CONTESTED both claims, OSM's convention by default, toggles
- **What:** every disputed area rendered CONTESTED with BOTH claims drawn and labelled — never a silent pick;
  the convention in force named in the legend with its date ("OSM's convention as of <date>"); a worldview
  toggle letting the user see the difference between conventions (OSM's, the default; Natural Earth's; and a
  per-claim view), each state ×12 with the caveat visible and the method in the hover (#17). The disputed-area
  DATA for OSM's convention before the 0.5 OSM artifacts exist must be named with its source and date in the
  PR (§6) — nothing is hand-drawn from memory.
- **Why (ruling):** Q803 + note, Q826, the 2026-07-13 ruling the label cites.
- **Acceptance:** the CONTESTED rendering and the toggle in the Chromium click-through record on the five
  surfaces; a fixture disputed area proves both claims are emitted and the default is OSM's.
- **May not decide:** the `<date>` value and the data source for OSM's convention in 0.4 (§6).

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured; ratchet numbers
from `ci.yml` (470 / 231 today). Plus: `node --check` on every touched script block (all nine files); the three
i18n gates for the legend, the toggle states and the CONTESTED labels; the whole-tree guard set after the
asset rebuild; `tests/test_countries_geo.py` and `tests/test_oomap_focus_redraw.py` green; the residual-
arithmetic node test; the registry freshness test with the filled pin; the Chromium click-through record
(Q1128 = a) of the five surfaces (Map, Governments/Law, Insights When / Where, Sources, the analysis Where
subtab — name them by their `ooMap` call site) at 1440 and 390 widths, in en / fr / ar; no network is touched
by any of it (the asset is bundled — say so). The `shipped.csv` numstat + duplicate-key scan.

## 5. Operator steps

1. If `proj.org` and `naturalearthdata.com` still answer `000` from the sandbox (probe first), confirm the
   Equal Earth coefficients from the published paper and run the 50m rebuild on the maintainer's machine;
   artifacts: the rebuilt JSON + the confirmed constants with their source, recorded in the PR.
2. The click-through of the five surfaces, the CONTESTED areas and the worldview toggle (Q1128 = a).
3. The `<date>` for "OSM's convention as of `<date>`" — the maintainer's word if the session cannot derive it
   from a dated OSM source; recorded in the ledger in the turn it is given.

## 6. What this slice may not decide

- **The `<date>`** in Q803 and the SOURCE of OSM's disputed-area claims before the 0.5 artifacts (Natural
  Earth's own disputed-areas layer, an OSM relation extract, or a dated curated list) — the PR names it; the
  maintainer may move it. The ruling forbids only one thing: a silent pick.
- **Which toggles** — per convention, per claim, or both; the note says "toggles"; the default is ruled.
- **The 0.5 replacement** (OSM-derived admin-0 / admin-1, S05-05) and the Place entity (S05-04).
- **FROM MEMORY:** the coefficients and the aspect ratio — never shipped unconfirmed.
- **Q1150** (the ooMap embed on When / Where stays) is the gate row's citation, not this slice's to revisit.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.4_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
