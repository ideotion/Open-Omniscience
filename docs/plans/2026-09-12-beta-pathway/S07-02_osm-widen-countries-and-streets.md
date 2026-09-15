# S07-02 — More OSM countries; the self-rendered streets · 0.7, `RELEASE_0.7_GATE.md` row B

> **Scope:** the OSM lane (S05-04's store, S06-01's daily tracking), the region picker and its dated size
> catalogue (`src/api/geo.py`, `src/geo/osm_regions.py`, `src/geo/osm_downloads.py`), the task-manager
> download rows, the map surfaces (`src/static/app-map.js` and a new Canvas 2D street renderer),
> `docs/SECURITY.md` + the hover. Must NOT touch: the projection seam (Q801; S04-11), any external tile
> server (Q821 (c) was not chosen), WebGL (no-WebGL is firm), exports / bulletins / evidence ZIPs (Q823 ⛔),
> a per-job bandwidth cap (invariant #20's omission).
> **Implements:** Q821 (placement: «proposed placement 0.7 (needs the ingested roads of 0.5+)»). Consumes,
> as the gate row names them: Q106, Q822, Q824, Q801, Q823 ⛔ (blank).
> **Gated on:** the `v0.6.0` tag with the daily tracking running on one country (the 0.7 entry); S05-04's
> roads (Q809 = b: roads and buildings in the store — the OPEN_QUEUE head entry lists it among the choices
> made knowingly); S06-01's per-country cost line; S05-05's admin artifacts.
> **Sequencing:** the widening first (it is the row's substance), the streets second (they need roads from
> at least the widened countries); the downloads and daily applies are the operator's.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
§9 (Maps and OpenStreetMap: the verified context and the option lists). Grep the tree before building
anything — the sheet's anchors were verified at `main`@`bebcef4` on 2026-09-12 and may have moved.

## 1. The rulings this slice implements — verbatim, by ID

- **Q821** — **(b)** «(b) Self-rendered vector streets at high zoom from the ingested roads.» [placement
  note from the JSON: «proposed placement 0.7 (needs the ingested roads of 0.5+)» — a *proposed placement*,
  followed unless the maintainer moves it in the gate's §3]. The sheet's (a) («None at beta: data views on
  Equal Earth, zoomable admin polygons, clustered points and heat; a place opens as a card, not a street
  map») and (c) («External tile servers») were not chosen.

Named by the gate row, quoted from the sheet (S05-04 / S04-11's JSON; consumed, not re-decided):
- **Q106** = (a) «… 0.7–0.8 widen to more countries.»
- **Q822** = (a) «Canvas 2D with published level-of-detail caps (points per view, polygon vertices per zoom),
  degrading to clusters, never to a frozen tab.»
- **Q824** = (a) «Daily diff apply per selected extract inside the online consent; re-baseline when a diff gap
  exceeds the retention; the per-country cost shown before selection.»
- **Q801** = (a) «Equal Earth on all five map surfaces through the one `project(lon, lat)` seam, no toggle,
  named in the legend ("Equal Earth · equal-area").»
- **Q823** ⛔ — blank. PENDING; nothing OSM-derived leaves the machine.

## 2. Where this stands in the tree — the staleness guard, with anchors

- VERIFIED (sheet §9 context): the projection is equirectangular (`app-map.js:21–24`), nine `lon2x`/`lat2y`
  call sites, zoom rides the SVG `viewBox`; no admin-1; the browser-side PBF reader is an ephemeral ≤ 8 MB
  overlay; «street-level detail out of scope» was the standing ruling until Q821 = b. S04-11 replaces the
  projection — re-grep `app-map.js` for the `project(lon, lat)` seam before touching a map surface.
- grep-verified in this brief: `src/static/app-map.js:21–24` today reads `MAP_W = 720, MAP_H = 360`,
  `lon2x`, `lat2y` (the pre-S04-11 state); `grep -ln getContext src/static/*.js` — `ooviz.js` and
  `app-markets.js` already draw on Canvas 2D, and `oosky.js` is the hand-rolled Canvas 2D precedent
  (invariant #31): the street renderer follows that pattern, no library, no CDN. `src/geo/osm_regions.py:31`
  `OSM_SIZES_AS_OF = "2026-06"` + registry `osm-region-sizes` (`configs/external_artifacts.yml:320`) is the
  dated cost catalogue; `src/api/geo.py:24` «Curated OSM region extracts (Geofabrik-style) with bundled,
  DATED size» estimates; `src/static/app-map.js:1523` notes the OSM download passes the `ensureOnline`
  popup. `grep -rn -i -E 'ODbL|OpenStreetMap contributors' src/static/app-map.js src/static/index.html` —
  no on-map attribution string today (see §6). No `pyosmium` in `pyproject.toml` (S05-04's `[geo]` extra).
- FROM MEMORY (sheet §9) — confirm: Geofabrik offers country and, for large countries, sub-country
  extracts. The reference VM is 2 cores / 3.5 GB (sheet §11 VERIFIED) — the frame budget is measured there.
- OPEN_QUEUE head entry (2026-09-15, line 59): «Q809 = b + Q821 = b + Q811 = b (roads and buildings,
  self-rendered streets, all in SQLite)» — chosen knowingly.

## 3. Slices — what to build, in order

### S1 — Widen to more countries
- **What:** a second and a third country tracked: each shows its extract size and its daily diff cost
  BEFORE selection (the dated catalogue estimate, said to be an estimate; the real size at fetch), each
  download and daily apply under the one online consent, queued through the task-manager grammar
  (invariant #20: pause / reorder / resume, the measured rate, never a fabricated ETA), and each ingest
  MEASURED and recorded (rows per class, bytes, seconds, which machine) in the lane's diagnostics member.
- **Why (ruling):** Q106 = a; Q824 = a; Q812 🔒 (S06-01's feed applies per extract); Q1001 / Q1002 / Q1014.
- **Acceptance:** the row's «a second and third country are tracked with their measured figures».
- **May not decide:** which countries (the maintainer's selection); anything under Q823 ⛔.

### S2 — Self-rendered vector streets at high zoom
- **What:** above a zoom threshold, the ingested roads of the viewed area drawn on a Canvas 2D layer under
  PUBLISHED level-of-detail caps (points per view, polygon vertices per zoom — the numbers stated in the UI
  hover and in the docs, ×12), degrading to clusters and then to the data view, never to a frozen tab; the
  road classes limited to S05-04's curated column set; below the threshold the existing data views on Equal
  Earth through the one `project(lon, lat)` seam, the legend naming the projection; the vintage (extract
  date + last applied diff) stated on the street view; a place still opens as a card. No tiles, no external
  host, no WebGL.
- **Why (ruling):** Q821 = b; Q822 = a; Q801 = a; R13.
- **Acceptance:** the row's «a street-level view renders from ingested roads on the reference VM without a
  frozen tab at the published caps (Chromium-verified + click-through, the frame budget measured)»; the
  negative-space fixture — an area with zero ingested roads renders «no roads ingested for this area», not
  an empty canvas.
- **May not decide:** the numeric caps (set from measurement on the reference VM and PUBLISHED; not ruled)
  and the zoom threshold (a design note; record it).

### S3 — The measured figures in the diagnostics member and the release notes
- **What:** per country: sizes, daily cost, ingest figures; per street view: the frame budget measured (ms
  per frame at the caps, on which machine); a country not yet run reads «not measured», never 0.
- **Why (ruling):** anti-capping; the gate's «measured figures».
- **Acceptance:** the numbers read back from the bundle member.
- **May not decide:** a bar (Q1017 = a).

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), separately, exit codes captured. Plus: `node --check` on every
touched `<script>` block (the renderer is JS); the three i18n gates for every new string (the cost line,
the cap hover, the «no roads ingested» state, the vintage line, the named refusal); the whole-tree guard
set; the consent fixture — a second-country download and its daily apply refused under the kill switch
with the named refusal, `tests/test_network_consent.py::test_no_new_socket_capable_importers`
(grep-verified) green; the renderer's negative-space fixtures (zero roads · roads outside the viewport ·
more vertices than the cap → clusters, the cap named); the Chromium click-through record (Q1128 = a): the
picker with the cost line, a second country's task-manager row, the street view at high zoom on the
fixture area with the frame budget captured (the audit's `Performance.getMetrics` precedent,
`docs/audit/ui-visual-2026-09-08/findings.csv`), the legend — in `en`, `ar` (RTL), `ja`; then the
maintainer's pass on the reference VM.

## 5. Operator steps

1. The downloads and daily applies for the second and third countries on the maintainer's machine → the
   measured figures.
2. Confirm on a networked machine that Geofabrik offers the country / sub-country extract for each chosen
   country (FROM MEMORY) → the PR body.
3. The click-through on the reference VM (2 cores / 3.5 GB): the street view's frame budget at the
   published caps.

## 6. What this slice may not decide

- **Q823 ⛔** — nothing rendered here may leave the machine as data until ruled (a screenshot is the user's;
  an export is not).
- **On-map attribution wording** — no attribution string exists on the map today (grep-verified); ODbL's
  attribution requirement on a rendered map is not the same question as Q823's share-alike on exports.
  Record the question for the maintainer; ship what S05-04 decided for its layer, if anything.
- **The numeric LOD caps, the zoom threshold, the country selection, whether a street view can be pinned
  as a task-manager job** — design notes, recorded in the PR.
- **The Equal Earth coefficients** (FROM MEMORY; S04-11 confirms) — drawn through the seam, not re-derived.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.7_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
