# S06-01 — OSM change tracking and the trend surfaces · 0.6, `RELEASE_0.6_GATE.md` row B

> **Scope:** the OSM lane seeded by S05-04 (`src/geo/`, its per-lane store on the 0.4 row O substrate, the
> Place entity of S05-03, the tag-completeness view), the admin-1 artifacts of S05-05, the choropleth map
> surfaces, the task-manager job rows for the daily apply, `docs/SECURITY.md` + the consent hover. Must NOT
> touch: the change MODEL (S05-04 defines it; this slice consumes it), the projection seam (S04-11, Q801),
> exports / bulletins / evidence ZIPs (Q823 ⛔ — no OSM-derived row leaves the machine), a per-job bandwidth
> cap (invariant #20's recorded omission — S04-13's per-process budget is the one authority).
> **Implements:** Q812 🔒, Q813. Consumes, as the gate row names them: Q106, Q814, Q815 · 2–6, Q816, Q824,
> Q823 ⛔ (blank).
> **Gated on:** S05-04 (places / roads / buildings, the change model, the extract + planet-history operator
> step), S05-05 (admin-1 keyed ISO 3166-2), S04-11 (Equal Earth), S04-08 (the substrate's change feed:
> cursor, gap detection, budget, politeness), S04-01 (the host list); the `v0.5.0` tag.
> **Sequencing:** first of the 0.6 breadth rows (the 0.7 entry needs "the OSM daily tracking running on at
> least one country"); the daily apply on a real selection is the last step and is the operator's.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
§9 (Maps and OpenStreetMap: the verified context and the option lists). Grep the tree before building
anything — the sheet's anchors were verified at `main`@`bebcef4` on 2026-09-12 and may have moved.

## 1. The rulings this slice implements — verbatim, by ID

- **Q812** 🔒 — **(a)** «(a) Geofabrik daily diffs per selected extract, applied to the ingested classes; if a
  diff older than the three-month retention is needed, re-baseline from a fresh extract and say so.»
- **Q813** — **(a)** «(a) Tag-level: for each object, each key added / removed / modified, with the diff's
  timestamp (and the object's `version`).» [placement note from the JSON: «the change model is defined in
  S05-04»]

Named by the gate row (S05-04 / S05-05's JSON; consumed here, never re-decided — read their blocks in §9):
- **Q106** = (a): 0.5 seeds the lane; «0.6 adds daily change tracking and the trend surfaces».
- **Q814** = (b) «The full-history planet.» — (a)'s extract-`version` prior and (c)'s ohsome were NOT chosen;
  the gate row still wants every trend to state the tracked window and the planet's prior separately.
- **Q815** = (a) «Confirm the six and the order (1–3 first).» — 1 is S05-04's; 2–6 are this slice's, in order.
- **Q816** = (a): choropleths by alpha-3 and admin-1 on Equal Earth + the ranked table in full, the vintage
  stated. **Q824** = (a): the daily apply inside the online consent; re-baseline when a diff gap exceeds the
  retention; the per-country cost shown before selection.
- **Q823** ⛔ — blank. PENDING; STOP at the seam (nothing here may leave the machine).

## 2. Where this stands in the tree — the staleness guard, with anchors

- VERIFIED (sheet §9 context): nine Geofabrik regions in `src/geo/osm_regions.py` (sizes as of 2026-06), a
  resumable segmented downloader through the guarded factory, a browser-side PBF reader (`osmpbf.js`, ≤ 8 MB
  prefix, ephemeral overlay); **no Python PBF reader, no stored features, no `.osc`/replication handling, no
  Place entity.** Everything this slice reads from the store is S05-04's output — re-grep for it first.
- SEARCH-VERIFIED (sheet §9): Geofabrik publishes daily change files per extract; change files are kept
  about three months; user, uid and changeset stripped from the public extracts since 2018-05-03. FROM
  MEMORY — confirm before building on it: the public extracts keep `version` and `timestamp`; Geofabrik
  offers country and, for large countries, sub-country extracts.
- grep-verified in this brief: `grep -rn -i -E 'geofabrik|pyosmium|osmium' src/ configs/ pyproject.toml
  .github/` — `src/geo/osm_downloads.py:61` `GEOFABRIK_BASE = "https://download.geofabrik.de"`; no
  `pyosmium` anywhere (S05-04's `[geo]` extra does not exist yet); `src/geo/osm_regions.py:31`
  `OSM_SIZES_AS_OF = "2026-06"`, registry id `osm-region-sizes` (`configs/external_artifacts.yml:320`);
  `ls src/versioned` — absent (0.4 row O, OPEN); `app-map.js:1523`: the OSM download passes `ensureOnline`.
- `docs/ledger/OPEN_QUEUE.md` head entry (2026-09-15, lines 57–60): Q814 = b was chosen knowingly — ONE
  planet-wide file; the per-region full-history extracts sit behind an OSM login, treated as key-gated.
  `RELEASE_0.5_GATE.md` rows D and E are OPEN; row D closes with OSM rows INSIDE the machine only (Q823 ⛔).

## 3. Slices — what to build, in order

### S1 — The daily diff feed and the re-baseline path
- **What:** a per-selected-extract daily-diff fetcher on the substrate's change feed (cursor = the last
  applied diff's timestamp; gap detection = the retention rule), through the ONE guarded fetch path, applied
  to the ingested classes only (what a diff carries for un-ingested classes is dropped and counted). If the
  oldest diff needed is older than the ~three-month retention, the lane re-baselines from a fresh extract
  and SAYS SO: a dated re-baseline event in the Living sources view and the diagnostics member, the trends'
  "observed since" clock stated accordingly. Geofabrik's file naming and retention is read in §5, not assumed.
- **Why (ruling):** Q812 🔒 = a; Q824 = a; Q1001/Q1002 (the host and its purpose in `docs/SECURITY.md` and
  the per-lane hover in the same diff); Q1014 (the lane declares its transport; never Tor → clearnet).
- **Acceptance:** the fixture day applies (adds / modifies / deletes over S05-04's fixture extract); the
  re-baseline path is exercised on a fixture whose oldest needed diff is "older than retention"; the
  kill-switch refusal is NAMED ("refused: airplane mode is on", never "fetch failed") — #14e's corollary.
- **May not decide:** the extract selection UI beyond the cost line; anything under Q823 ⛔.

### S2 — Tag-level change rows
- **What:** for each object in the applied diff, one row per key added / removed / modified, with the
  diff's timestamp and the object's `version`, in the change model S05-04 defined (if its shape differs
  from this brief, S05-04 wins and this brief is corrected in the PR). Refusals pinned by tests: an object
  outside the ingested classes yields no row; a geometry-only modify yields no tag row and a counted fact;
  a missing `version` is stored as absent with the reason, never fabricated; a delete yields the "object
  disappeared" row that surface 3 reads.
- **Why (ruling):** Q813 = a; the FROM MEMORY `version`/`timestamp` premise, confirmed in §5.
- **Acceptance:** the negative-space fixture (empty diff · un-ingested classes only · geometry-only
  modifies) yields zero tag rows with the reasons; the positive fixture yields the exact rows; each guard
  mutation-checked by name.
- **May not decide:** the change model's columns (S05-04).

### S3 — The trend surfaces 2–6, in order
- **What:** 2 adoption trends of each metadata type over time · 3 openings and closures (objects appearing
  / disappearing, `disused:*`, `shop=vacant`, `opening_hours` set to closed) · 4 brand and chain footprint
  by country · 5 contact-channel mix (site / phone / email / social) · 6 data freshness (`check_date`,
  last-edit age) by area. Counts with method + n, never a composite; `ooChart` (invariant #16: full
  resolution, bars below n = 10); every trend states "observed since <date>" for the tracked window and the
  planet's prior SEPARATELY — if S05-04's planet-history step has not run, the prior reads "not available"
  (no ohsome substitute: Q814 (c) was not chosen). Caveats visible, ×12.
- **Why (ruling):** Q815 = a (the order; 1 is S05-04's); Q814 = b; the gate row's "never blended".
- **Acceptance:** a tracked country shows a real day-over-day tag change on surface 2 or 3 from an applied
  diff, the diff's timestamp as the artifact (§5 produces it; the fixture proves the path first).
- **May not decide:** which keys count as "brand" / "chain" beyond the keys S05-04 ingested; record the set.

### S4 — The geography axis
- **What:** choropleths by alpha-3 and admin-1 on Equal Earth (S04-11's `project(lon, lat)` seam; S05-05's
  ISO 3166-2 artifacts, Q314) with the ranked table in FULL beside every choropleth (invariant #31(c): the
  table is canonical, never truncated), the vintage stated on every map (extract date + last applied diff
  timestamp) — the 0.6 exit's "the OSM vintage stated on every map".
- **Why (ruling):** Q816 = a; Q801 = a (no second projection); R6 (alpha-3 display, S04-05).
- **Acceptance:** Chromium-verified + click-through: the choropleth and its table agree on every value.
- **May not decide:** a bar for coverage; a colour scale that implies a verdict (ranked counts only).

### S5 — Diagnostics, the cost line and the Living sources entry
- **What:** the lane's diagnostics member gains: last diff applied (timestamp), diffs applied, gap events,
  re-baseline events, and the MEASURED per-country daily cost (bytes fetched, seconds, on which machine) —
  the row's "measured daily diff cost for one country". The picker shows the per-country cost BEFORE
  selection as a dated estimate from the registry catalogue (the `OSM_SIZES_AS_OF` pattern), the real size
  read at fetch; the estimate says it is an estimate.
- **Why (ruling):** Q824 = a; the vertical pattern's step 8; anti-capping.
- **Acceptance:** the numbers read back from the bundle member; no run yet reads "not measured", never 0.
- **May not decide:** a per-job bandwidth cap (invariant #20's omission stands; the S04-13 budget applies).

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured. Plus:
`node --check` on every touched `<script>` block; the three i18n gates for every new string (trend and
caveat labels, the re-baseline event text, the cost line, the named refusal); the whole-tree guard set;
the parser skeptic matrix (a diff parser and a write path: negative-space lens, every guard
mutation-checked by name, the mutation asserted applied); the consent fixture — the daily apply refused
under the kill switch with the named refusal, `tests/test_network_consent.py::test_no_new_socket_capable_importers`
(grep-verified) still green; the Chromium click-through record (Q1128 = a): the Places trend subtabs 2–6,
one choropleth with its ranked table at alpha-3 and at admin-1, the Living sources OSM entry with a
re-baseline event, the task-manager row of a daily apply — in `en`, `ar` (RTL), `zh`; then the maintainer's pass.

## 5. Operator steps

1. On the maintainer's machine: select one real country extract, run the daily apply on at least two
   consecutive days → the diagnostics member showing a real day-over-day tag change with the diff's
   timestamp and the measured cost (bytes, seconds). This closes the row.
2. On a networked machine, confirm the FROM MEMORY premises and write them into the PR body: the extracts
   keep `version` and `timestamp`; a country / sub-country extract exists for the selected country; how the
   daily files are named, numbered and retained (the retention figure the re-baseline rule uses).
3. Review the `docs/SECURITY.md` line and the hover text for the Geofabrik host; the click-through pass.

## 6. What this slice may not decide

- **Q823 ⛔ (ODbL)** — blank. Until ruled, no OSM-derived row, trend or change row enters an export, a
  bulletin or an evidence ZIP (today's state, not a decision); the PR body says so.
- **The change model** and **the planet-history download** (Q814 = b) are S05-04's — this slice reads what
  exists and states "not available" otherwise; it never pulls ohsome nor a login-gated full-history extract.
- **The per-country selection policy** is the maintainer's; **a numeric bar** for any trend is not set
  (V1-6, Q1017); **a per-job bandwidth cap** stays omitted (invariant #20 — S04-13's per-process budget,
  never a second rate authority); **the Equal Earth coefficients** (FROM MEMORY) are S04-11's to confirm.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.6_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
