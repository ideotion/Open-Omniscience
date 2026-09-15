# S05-04 — The OSM lane seeded: the first country · 0.5, `RELEASE_0.5_GATE.md` row D

> **Scope:** a new OSM lane on 0.4 row O's substrate — the `[geo]` extra (`pyosmium`), the extract pass over
> continent-level extracts, `osm.db` (SQLite, encrypted alike), the curated columns + JSON blob, the
> tag-level change-row MODEL, the tag-completeness view (analytic 1), notable Places as Articles through
> S05-03's Place entity, the "Places" facet, the local geocoder, Canvas 2D LOD caps, the country picker in
> Settings → Data sources → Maps, the full-history planet download. Must NOT build: the daily diff APPLY and
> the trend surfaces 2–6 (0.6), more countries (0.7–0.8), vector streets (Q821, 0.7), any export / bulletin
> / evidence member with OSM-derived rows (Q823 ⛔), an external geocoder, WebGL.
> **Implements:** Q106, Q806, Q807, Q808, Q809, Q810 (+ note), Q811, Q814, Q815 (· 1), Q817, Q820, Q822,
> Q823 ⛔ (PENDING — stop at the seam), Q824, Q825, Q828; via the gate row: Q813 (model only), Q819 · 3,
> Q1008 (OSM lines wait), the Q1140 note (the column ceiling).
> **Gated on:** 0.4 row O (substrate, `osm.db`, the fixture extract); 0.4 row H (the OSM hosts in
> `docs/SECURITY.md`); S05-03 S3 (the Place entity); S05-05 (admin-1 keys); operator downloads; Q823 ⛔.
> **Sequencing:** after 0.4 row O and S05-03 S1–S3; S05-03 S4 needs this ingest; operator steps last.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (their verified context and option lists). Grep the tree before building
anything — the sheet's anchors were verified at `main`@`bebcef4` on 2026-09-12 and may have moved.

## 1. The rulings this slice implements — verbatim, by ID

- **Q106** — **(a)** «(a) 0.5 seeds it (the Place entity + the first country's POIs + the tag-completeness
  view); 0.6 adds daily change tracking and the trend surfaces; 0.7–0.8 widen to more countries.»
  [placement: 0.5 seed; 0.6 = S06-01; 0.7-0.8 = S07-02 / S08-02]
- **Q806** — **(b)** «(b) Continent-level as today.»
- **Q807** — **(a)** «(a) Off until the user picks countries (sizes and the daily diff cost shown); the
  wizard suggests the countries of the UI language, never from the IP.»
- **Q808** — **(a)** «(a) A `[geo]` extra with `pyosmium` for the extract pass; `.osc` diffs are XML and stay
  pure Python; without the extra the lane says so and offers the small-country path.»
- **Q809** — **(b)** «(b) Also roads and buildings.»
- **Q810** — **(a)** «(a) A curated column set (`name`, `name:*`, `brand`, `brand:wikidata`, `operator`,
  `opening_hours`, `website`, `contact:*`, `phone`, `email`, `addr:*`, `wikidata`, `wikipedia`, `cuisine`,
  `level`, `check_date`, `disused:*`, `wheelchair`, `payment:*`) + every other tag in one compact JSON blob,
  so nothing is lost and the columns stay queryable.» — NOTE (verbatim): «yes, but extend the list of
  columns to minimize the JSON blob»
- **Q811** — **(b)** «(b) SQLite for everything.»
- **Q814** — **(b)** «(b) The full-history planet.» [placement: impact flagged: the full-history planet is
  one planet-wide file]
- **Q815** — **(a)** «(a) Confirm the six and the order (1–3 first).» [placement: analytic 1 in 0.5; 2-6 =
  S06-01] — analytic 1 = tag completeness per country / admin-1 (share of places with `opening_hours`,
  `website`, `email`, `phone`).
- **Q817** — **(a)** «(a) Notable Places only — admin areas, `place=*` (cities, towns, villages), and any
  object carrying `wikidata`/`wikipedia` — become Articles with a body (Q818); every other POI stays a
  structured row with its own search facet ("Places"), and the aggregates surface as cards.»
- **Q820** — **(a)** «(a) Yes, for the countries the user ingested, disclosed ("addresses outside your OSM
  countries are not located"); never an external geocoding service.»
- **Q822** — **(a)** «(a) Canvas 2D with published level-of-detail caps (points per view, polygon vertices
  per zoom), degrading to clusters, never to a frozen tab.»
- **Q823** ⛔ — PENDING — blank on a ⛔ (ODbL); STOP at the seam: no OSM-derived row enters an export, a
  bulletin or an evidence ZIP (today's state, not a decision). Never propose a default.
- **Q824** — **(a)** «(a) Daily diff apply per selected extract inside the online consent; re-baseline when
  a diff gap exceeds the retention; the per-country cost shown before selection.»
- **Q825** — **(a)** «(a) Same answers as the Wikipedia lane (Q719, Q720).» — `osm.db` beside the corpus,
  linked by ids, a backup member per lane; encrypted with the same passphrase, no exceptions.
- **Q828** — **(a)** «(a) Settings → Data sources → Maps (invariant #8: data tabs show data, acquisition
  lives in Settings); the World map tab shows the vintage and a link there.»
- Carried by the gate row: **Q813 = (a)** tag-level change rows (key added / removed / modified, the diff's
  timestamp, the object's `version`) — the MODEL is defined here, the daily apply is 0.6; **Q819 · 3** press
  articles' mentioned places → the gazetteer → Places; **Q1008 = (a)** attribution lines at every export
  point — OSM lines only once Q823 is ruled; **Q1140 note** (the rulings index): anticipate PostgreSQL's
  column limit whenever a curated column set is widened (1,600 and SQLite's 2,000 are FROM MEMORY — confirm).

## 2. Where this stands in the tree — the staleness guard, with anchors

- No Python PBF reader, no stored features, no `.osc` handling, no Place entity (sheet §9 VERIFIED);
  `pyosmium`/`osmium` appear nowhere in `src/` or `pyproject.toml` and `src/versioned/` does not exist yet
  (grep-verified in this brief: `grep -rn 'pyosmium\|osmium' src/ pyproject.toml`; `ls -d src/versioned`).
- Nine Geofabrik regions with rounded sizes and `OSM_SIZES_AS_OF` in `src/geo/osm_regions.py` (planet 72 GB
  · europe 28 · north-america 14 · asia 13 · africa 5 · …, as of 2026-06 — sheet §9 VERIFIED; estimates,
  never a mirror's exact size); the resumable segmented downloader is `src/geo/osm_downloads.py`;
  `src/static/osmpbf.js` reads a ≤ 8 MB prefix in the browser (grep-verified heads). Tests:
  `tests/test_osm_regions.py`, `test_osm_downloads.py`, `test_osm_segmented_download.py`, `test_osm_jobs.py`.
- OSM facts (sheet, SEARCH-VERIFIED): Geofabrik daily change files per extract, kept about three months;
  public extracts stripped of user/uid/changeset since 2018-05-03; planet replication at
  `planet.openstreetmap.org/replication/`. FROM MEMORY — confirm before building on them: extracts keep
  `version`/`timestamp`; the Windows `pyosmium` wheels; a pure-Python decoder near 10⁵ nodes/s. The
  full-history planet is ONE planet-wide file (the 2026-09-15 head entry); its size is in no sheet — the row
  RECORDS it. `docs/SECURITY.md` omits the OSM mirrors (sheet §11 VERIFIED; 0.4 row H adds them; any host
  this slice adds goes there + the consent hover in the same diff, Q1001).
- `configs/language_countries.yml` maps each UI language to its countries (sheet §10 VERIFIED; grep-verified).

## 3. Slices — what to build, in order

### S1 — The `[geo]` extra and the reader seam (Q808)
- **What:** `pyosmium` behind a `[geo]` extra (registered in the external-artifact registry); the extract
  pass reads places, roads and buildings (Q809); `.osc` parsing pure Python; without the extra the lane SAYS
  SO and offers the small-country path; 0.4 row O's synthetic extract runs the same pipeline in CI.
- **Acceptance:** the fixture pipeline green; the "extra missing" message ×12 names what is unavailable.

### S2 — `osm.db`: the objects table, the blob, the change model (Q810 + note, Q811, Q813, Q825, Q1140)
- **What:** SQLite for everything, encrypted alike, an opt-in backup member per lane; the curated columns
  EXTENDED beyond Q810's list to shrink the blob (blob bytes per object measured before/after; the Q1140
  ceiling stated); every other tag in one JSON blob; the change-row schema (key, old, new, diff timestamp,
  object `version`) defined and left empty until 0.6.
- **Acceptance:** the migration's row counts; the blob-size measurement in the PR body; the column count
  and its ceiling in the schema docstring; a round-trip proving no tag is lost.

### S3 — The picker, the consent, the cost (Q806, Q807, Q824, Q828)
- **What:** Settings → Data sources → Maps: off until the user picks countries; the wizard suggests the UI
  language's countries from `configs/language_countries.yml`, never from the IP; continent extracts as today,
  so the picker shows the CONTINENT extract's size plus the per-country daily diff cost before selection;
  the cadence and re-baseline rule stated (the apply is 0.6); every download under the ONE online consent,
  refused under the kill switch by NAME, never downgraded (Q1014); the World map tab shows the vintage.
- **Acceptance:** the consent + kill-switch fixture; strings ×12 with the cost visible; the Chromium record.

### S4 — The full-history planet (Q814)
- **What:** the consented, sized download shown before it starts (a new host → `docs/SECURITY.md` + the
  hover in the same diff); ingest of the first country's history from it; the measured size and ingest time
  recorded — the row's artifact.
- **Acceptance:** the two measurements in the PR body (operator-run; `not-measurable-here` in the sandbox).

### S5 — Analytic 1, Places, the facet, the geocoder (Q815 · 1, Q817, Q819 · 3, Q820)
- **What:** tag completeness per country / admin-1 (S05-05's keys) for `opening_hours`, `website`, `email`,
  `phone` — counts, n, method, never a score; notable Places become Articles through S05-03's Place entity,
  every other POI a row behind a "Places" facet, aggregates as cards; mentioned places resolve through the
  gazetteer; a local geocoder from ingested `addr:*`, disclosed ("addresses outside your OSM countries are
  not located"), never an external service.
- **Acceptance:** the view renders from ingested rows (Chromium-verified); a Place opens as a card; a
  negative-space fixture (an address outside the ingested countries → the disclosed gap, never a guess).

### S6 — Rendering budgets (Q822)
- **What:** Canvas 2D with PUBLISHED caps (points per view, polygon vertices per zoom), degrading to
  clusters, never a frozen tab. **Acceptance:** the caps measured on the reference VM, in the legend hover.

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured. Plus: the
fixture pipeline with the socket guard armed (zero resolutions); the consent and named-refusal fixtures for
every new fetch; the full skeptic matrix on `osm.db` (negative-space inputs — an object with no tags, an
empty tag value, a relation with no geometry — round-trip as gaps, never 0); the whole-tree guard set;
`node --check`; the three i18n gates; the Chromium click-through of the picker, the World map vintage line,
the tag-completeness view and a Place card in `en` and `ar`; a negative-space test that no export, bulletin
or evidence ZIP member carries an OSM-derived row (Q823 ⛔).

## 5. Operator steps

1. On the reference VM, under the consent: download one country's continent extract and the full-history
   planet file → their measured sizes, the first country's ingest time, `osm.db`'s size (not measurable here).
2. The click-through of the §4 surfaces (Q1128 = a) → the record on the PR.

## 6. What this slice may not decide

- **Q823 ⛔ (ODbL):** nothing OSM-derived leaves the machine; the attribution lines of Q1008 wait; no default.
- What "the small-country path" without the extra concretely is (a bounded pure-Python read, or the
  existing ≤ 8 MB browser reader) — the sheet names the path, not its shape; proposed in the PR body.
- How a country is cut from a continent extract (S05-05's admin-0 relation, or the `ISO3166-1` tags) — a
  design point stated in the PR with its cost; which columns join the curated set (listed, blob measured);
  the LOD numbers, the per-country daily-diff cost, the planet file's size — measured, never estimated.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.5_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every §1 ruling in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
