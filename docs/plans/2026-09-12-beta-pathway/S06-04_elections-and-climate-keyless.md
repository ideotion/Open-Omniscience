# S06-04 — Elections + climate, keyless · 0.6, `RELEASE_0.6_GATE.md` row A

> **Scope:** the elections vertical (`src/civic/coverage_floor.py`, `src/civic/elections.py`,
> `configs/world_events.yml`, `configs/language_countries.yml`, the Agenda rail); the climate vertical
> (`src/stats/oni.py`, `bulk.py`, `fetch.py`, `aggregate.py`, `src/hazards/`, `src/weather/openmeteo.py`,
> new lanes for OWID CO2 + Energy, GISTEMP v4, NSIDC G02135, GHCN-Daily, the IPCC AR6 SPMs); the
> statistics-agency directory (`src/stats/agencies.py`); K13 (`src/monitoring/kpi.py`); the registry;
> `docs/SECURITY.md` + the hover. Must NOT touch: FIRMS and OpenAQ (OUT under V1-2, not deferred),
> ElectionGuide (OUT under V1-3), rosters and poll Tier-2 (post-1.0, V1-8), any key-gated source (V1-2).
> **Implements:** Q1133, Q1134, Q1147, Q1153, plus the carried V1 content: `V1_PATHWAY_2026-07-14.md` §3
> (lines 297–343: the 0.6 row, amendments 1 and 2), §4.0, §4.3, §4.5, ruled 2026-09-07 (V1-1 with the four
> amendments; V1-2; V1-3; V1-8).
> **Gated on:** the `v0.5.0` tag; the StatFigure / Agenda rails (exist); S04-01 (the host list); S04-05
> (alpha-3 display). No ⛔ in the way; the operator steps gate the close, not the build.
> **Sequencing:** first row of 0.6; the two verticals are independent of rows B–D and of each other.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the sheet's §12
blocks for the four questions, then V1 §3, §4.0, §4.3, §4.5 in full. Grep the tree first (`bebcef4` anchors).

## 1. The rulings this slice implements — verbatim, by ID

- **Q1133** — **(a)** «(a) AR6 Summaries for Policymakers first; `pypdf` acceptable.»
- **Q1134** — **(a)** «(a) Temperature and precipitation first; 1991–2020 baseline; soil moisture later.»
- **Q1147** — **(a)** «(a) A networked session builds the directory; `news_url` per agency verified live.»
- **Q1153** — **(a)** «(a) Population-weighted with the weighting disclosed on the figure.»

The carried V1 content (no sheet IDs; ruled 2026-09-07 — `V1_PATHWAY_2026-07-14.md` §3 and §7):
- §3 line 312, the 0.6 row: «**Elections/civic activation** … **coverage floor = every language-covered
  country + the three-tier scheduled/window/projected date-confidence model** — the 2026-07-14 ruling, §4.5)
  + **climate/environment completion** (OWID CSVs, ONI verification, quakes, fires, air quality — §4.3)».
- Amendment 1 (lines 321–323): «0.6 climate survives keyless (ONI · USGS quakes · OWID · GISTEMP · NSIDC ·
  GHCN-Daily). V1-2 costs it NASA FIRMS (fires) and OpenAQ v3 (air quality) — and OpenAQ has no keyless path
  at all, so that layer is not deferred, it is **out**.»
- Amendment 2 (lines 324–325): «0.6 elections ships its CALENDAR as the 1.0 bar (V1-8); rosters and poll
  Tier-2 move post-1.0, and V1-3 removes ElectionGuide, leaving snap-election freshness as a stated gap.»
- §4.5's maintainer ruling (2026-07-14): the floor from a dated, sourced mapping; the tiers `scheduled` /
  `window` / `projected` rendered distinctly, caveat visible, ×12; never fabricate, never roll forward.
- Consumed from the sheet: Q912 = a (the same floor file); Q1001 / Q1002 / Q1014; Q1017 = a (K13 measured).

## 2. Where this stands in the tree — the staleness guard, with anchors

- grep-verified in this brief: `src/civic/coverage_floor.py:59` `LANGUAGE_COUNTRIES_AS_OF = "2026-09-07"`
  and `src/civic/elections.py` exist; `configs/language_countries.yml` («drafted-from-training-knowledge;
  clearnet check pending») excludes territories and marks contested rows; registry id
  `language-countries-floor` (`configs/external_artifacts.yml:344`) says «NOT verified against any primary
  source» — the elections denominator is itself unverified today.
- `configs/world_events.yml:109–115`: the hand-curated `elections` calendar (the France 2027 entry) — §4.5's
  «ruled first slice already shipped»; the snapshot EXTENDS it. `scripts/generate_wikidata_rings.py` exists.
- Climate today: `src/stats/oni.py` (the ONI parser; its docstring records the CPC host answering CONNECT
  403 via the sandbox proxy, 2026-09-07); `configs/climate_events.yml` («clearnet check pending»);
  `src/hazards/parse.py:97,137` `earthquake.usgs.gov`, `gdacs.org` (the opt-out scheduler exception,
  `docs/SECURITY.md:44–49`); `src/stats/bulk.py` (wide-CSV + ZIP, «OWID's `owid-energy-data.csv` shape»).
  `grep -rn -i -E 'gistemp|nsidc|ghcn|ipcc' src/ configs/` — GISTEMP only in `oni.py`'s vintage note; IPCC
  and NSIDC only as PRESS RSS sources (`configs/sources.yml:6168–6170`, `:6544`): the data lanes are new.
- `src/weather/openmeteo.py:33` `ARCHIVE_BASE = "https://archive-api.open-meteo.com/v1/archive"`;
  `ALLOWED_DAILY` already carries `temperature_2m_max`, `temperature_2m_min`, `precipitation_sum`;
  `ARCHIVE_FLOOR = date(1940, 1, 1)`, `MAX_WINDOW_DAYS = 366`; a consented click only; no baseline logic.
- `src/stats/agencies.py`: 29 `StatAgency(` rows, `grep -c 'news_url="'` = 0 — no agency carries a verified
  `news_url` today (a value «means someone fetched the page and confirmed it»). `pyproject.toml:166`
  `"pypdf>=4.0"` in the `[pdf]` extra. `src/monitoring/kpi.py:112–114`: K13 awaits the §4 vertical builds.

## 3. Slices — what to build, in order

### S1 — The elections CALENDAR at the coverage floor
- **What:** the Wikidata CC0 national-election snapshot (election QID · country · office · P585 date /
  P580–P582 range · official-source URL), generated on the maintainer's networked machine through the
  `generate_wikidata_rings.py` pattern into a dated, bundled config with `*_AS_OF`, registry entry and
  freshness test, LAYERED with the hand-curated `world_events.yml` entries and the networked session's
  sourced recurrence-rule research per floor country. The three tiers rendered distinctly on the Agenda
  rail, caveat visible, ×12; no rule + last-held date ⇒ no projected entry; a passed projected date renders
  «projected date passed — status unknown; check the official source», never re-projected; snap elections
  the stated gap. The coverage report lists every floor country's tier state + the floor's own status.
- **Why (ruling):** V1 §3 amendment 2; §4.5(1)–(4); V1-8; V1-3; Q912 = a.
- **Acceptance:** «the elections calendar covers the floor with each country's tier stated (a coverage
  report as the artifact)»; `test_external_freshness.py::test_every_as_of_constant_is_registered` green.
- **May not decide:** rosters, poll Tier-2, card #9 (post-1.0, V1-8); WDQS vs dumps (decide, record).

### S2 — Climate keyless: the six surviving rows through the vertical pattern
- **What:** in §4.3's recommended order, each through §4.0's nine steps (dated catalog + registry entry ·
  guarded fetch · pure parser with the negative-space skeptic · vintaged store · StatFigure / Agenda rail ·
  a distinct provenance class · data-first surface · per-vertical freshness · ledger): NOAA CPC ONI (exists
  — the El Niño table's clearnet check is the pending item), USGS quakes (exists as the hazards feed — join
  the freshness block, do not fork the fetch), OWID CO2 + Energy CSVs (`bulk.py`'s wide-CSV shape), GISTEMP
  v4 (monthly, retro-revised → vintages load-bearing), NSIDC G02135 (daily CSVs; pin the versioned filename),
  GHCN-Daily (per-station, never the tarball). Anomalies only against STATED baselines; the provider's own
  confidence fields surfaced; never a «climate risk score»; FIRMS and OpenAQ OUT, said on the surface.
- **Why (ruling):** V1 §3 amendment 1; §4.3; V1-2; Q1001 / Q1002 / Q1014 for every new host.
- **Acceptance:** «the climate series render from real fetches through the consent gate with their freshness
  diagnostics»; each new host in `docs/SECURITY.md` + the hover; each parser's negative-space fixture.
- **May not decide:** a freshness bar per series (K13: measured first).

### S3 — IPCC AR6 Summaries for Policymakers
- **What:** the AR6 SPMs as text sources: fetched under consent from the IPCC host (a press RSS source
  already; the DATA purpose is a new `docs/SECURITY.md` line + hover), extracted with `pypdf`, each an
  Article through `index_article` with its provenance class and a registry entry; «predictions tracked over
  time, never asserted futures» on the surface ×12.
- **Why (ruling):** Q1133 = a; §4.3's honest angles. **Acceptance:** one SPM in the reader with its
  provenance and disclosure line; the registry entry. **May not decide:** PDF-extraction quality bars.

### S4 — The Open-Meteo layer: temperature and precipitation against 1991–2020
- **What:** on the existing consented place-and-window slice: temperature and precipitation anomalies
  against a 1991–2020 baseline computed from the same archive; the baseline fetch is its own consented cost
  (`MAX_WINDOW_DAYS = 366` makes a 30-year baseline many windows — chunk, cache, show the cost before the
  click); the baseline's method on the figure; reanalysis ≠ station stays the caveat.
- **Why (ruling):** Q1134 = a; the gate row's «an external, consented call named in `SECURITY.md` and the
  popup hover per Q1001/Q1002». **Acceptance:** an anomaly figure with baseline, window and licence on it.
- **May not decide:** soil moisture (later); an anomaly threshold that reads as an alert.

### S5 — The official-statistics directory toward ~152 agencies
- **What:** the networked session builds the directory («29 of ~152» today); `news_url` per agency set ONLY
  after the page was fetched and confirmed; the verified count recorded beside the total in the directory's
  diagnostics and the release notes — the row's close. Agencies still register DISABLED (the module's rule).
- **Why (ruling):** Q1147 = a. **Acceptance:** «the directory's verified count is recorded beside the total».

### S6 — Population-weighted intensive indicators
- **What:** in `src/stats/aggregate.py`, intensive indicators with no exact weighting aggregate
  population-weighted, the weighting (population source, its `as_of`, the members covered) disclosed ON the
  figure ×12; a member with no population figure is a stated gap, never an unweighted mean presented as
  weighted; the population source is dated and registry-tracked.
- **Why (ruling):** Q1153 = a ((b) unweighted mean not chosen). **Acceptance:** a weighted figure with its
  weighting line; the negative-space fixture (no population for one member → the gap named).

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), separately, exit codes captured. Plus: `node --check` on touched
script blocks; the three i18n gates for every new string (tier labels and caveats, the passed-date notice,
the baseline and weighting disclosures, the OUT notices, the named refusals); the whole-tree guard set and
the registry guard for every new `*_AS_OF`; the parser skeptic matrix per parser (negative-space lens;
mutation-checked guards); the consent fixture per new host (GISTEMP, NSIDC, GHCN-Daily, OWID, the IPCC
host, the Open-Meteo baseline fetch) with `tests/test_network_consent.py::test_no_new_socket_capable_importers`
(grep-verified) green; the Chromium click-through record (Q1128 = a): the Agenda's three tiers and a passed
projected date, the climate figures with baseline and weighting lines, the freshness diagnostics, the
directory's verified-of-total line — in `en`, `ar` (RTL), `hi`, `es`; then the maintainer's pass.

## 5. Operator steps

1. The networked directory build: agencies toward ~152, each `news_url` fetched and confirmed (Q1147); the
   Wikidata election snapshot generated there too, with the per-floor-country recurrence-rule research.
2. Verify `configs/language_countries.yml` rows against their per-language `source`, contested rows first;
   flip `verification_status`; bump both `as_of` values together (the registry's refresh rule).
3. The pending clearnet checks: the El Niño table against the CPC ONI table; the 🔎 rows' exact URL / format
   / terms (GISTEMP, NSIDC, GHCN-Daily, OWID per-column terms, IPCC terms). Probe every host from the sandbox
   first (base §6); where it refuses, the maintainer's runs supply the fetch. Then the click-through pass.

## 6. What this slice may not decide

- **Rosters, poll Tier-2, card #9** — post-1.0 (V1-8); **FIRMS, OpenAQ, ElectionGuide** — out, not deferred
  (V1-2, V1-3); **Copernicus CDS / ERA5, EM-DAT** — excluded (§4.3). None may be re-proposed here.
- **The population source** (S6), **WDQS vs dumps** (S1), **the baseline chunking** (S4): the session's
  calls, recorded (the cost shown before the click is the ruled shape). **K13 bars**: none (Q1017 = a).
- **Territories** (Hong Kong, Macau, Puerto Rico …) hold elections but are excluded from the floor file by
  its recorded scoping decision; changing that is the maintainer's word.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.6_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
