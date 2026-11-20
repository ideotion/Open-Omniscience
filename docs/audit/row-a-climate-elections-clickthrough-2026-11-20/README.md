# 0.6 row A click-through — 2026-11-20 (S06-04 §4, Q1128 = a)

Chromium (Node Playwright, `/opt/pw-browsers/chromium`, 1440 × 1000) against one real server started
from a fresh `main` checkout with `OO_DATA_DIR=<seeded folder> OO_DB_PLAINTEXT=1 OO_AUTOSEED=0` and no
proxy variables. The app booted in airplane mode and stayed there: **every request the four walks made
went to 127.0.0.1** (`offsite: []` in every language), with **0 page errors, 0 console errors and 0
responses of 400 or more**, and no `undefined`, `null`, `NaN` or `[object Object]` in any surface read.

Everything was reached through the real controls: the sidebar, the Agenda's view switcher, the Climate
subtabs and the "Your place" form and Show button, Governments → Groups → "Computed from members" and
its two selects and the "Compute over the members that did report" button, Settings (top-bar button) →
Advanced → the collapsed "Statistics producers" section, and the top-bar language switcher (en, ar, hi,
es; `dir` read `rtl` in Arabic only). `report.json` holds every value read; `seed.py` and `walk.js`
reproduce it.

## The data is invented, in the published shape

`seed.py` writes each store through its OWN code, replacing only the transport:

- the six climate units (GISTEMP global, NSIDC north, ONI, USGS M6+, OWID CO2, GHCN station
  USW00094728) go through `src.stats.climate.fetch_and_store` with the real fetchers, whose `get` is
  handed a stand-in returning a publisher-shaped body; the parsers, diagnostics and vintages run for real;
- the place baseline goes through `src.weather.anomaly.fetch_anomalies` with a stand-in fetcher, so the
  1991–2020 slice and a June–August 2026 window are held in the store and read back with no request;
- ten European countries' 2023 population and GDP per capita are stored World Bank rows.

**Every number is invented** (smooth curves, a seasonal sine, a fixed seeded stream). The seed writes
GISTEMP's D-N column as `***` throughout, which is why that card counts 150 published gaps: an artifact of
the invented table, not of the app.

The elections calendar needed two more things, applied only in the throwaway checkout and never committed
there: `elections_snapshot.json` (the generator's shape around the repository's own
`tests/fixtures/election_snapshot_fixture.json` rows) as `configs/elections_snapshot.json`, and the two
entries in `walk_events.yml` appended to `configs/world_events.yml`. **No shipped entry carries a recurrence
rule yet** (the networked session of S06-04 §5 step 1 writes them), so the projected tier cannot be seen
without one. Both entries are titled "Walk … (invented rule)" and sourced "walk fixture, not a real rule".

## What was shown

| Surface | en · ar · hi · es |
|---|---|
| Agenda, list view | The three tiers side by side: **scheduled** (the US 2026 midterm, its stated day now gone by and saying so: "This date has passed, as the source stated it."), **window** (France 2027, the snapshot's DE/ES/IT/PT rows), **projected** (Walk Portugal, 2028: pill `projected`) and the **passed projection** (Walk Greece, last held 2020 + 5 = 2025: pill `⚑ projected · passed`, red, with "The projected date has passed and no result is recorded here — status unknown. Check the official source." in the hover). Greece was not rolled forward to 2030. |
| Agenda, Elections coverage | 140 floor countries, list as of 2026-09-07, the "drafted, not verified" caveat visible; counts scheduled 0 · window 10 · projected 0 · passed 3 · projected-passed 0 · dateless 7 · missing 120; the snapshot line (as of 2026-11-20: 5 entries added, 1 already in the hand-curated list, 2 refused). Portugal reads **window**, correctly: its best entry is the snapshot's window row, and the most certain tier wins; Greece is not a floor country (no Greek UI language), so neither walk entry moves a count. |
| Climate, per dataset | Source (local preview link, full URL), licence, last fetched, stored values and fetches, shape documented, then the freshness diagnostics: new/revised/unchanged/gaps on every unit, plus NSIDC's 2 days with part of the pole unobserved, USGS's 1 quarry blast left out, OWID's five curated columns missing from the file, GHCN's 1 quality-flagged day. GISTEMP's baseline line ("against the 1951-1980 average", and the caveat "An anomaly is a difference from the 1951-1980 average, not a temperature …") is visible above the figure. |
| Climate, Your place | 48.86, 2.35 rounded to 48.9, 2.4; "Read from this machine; nothing was sent."; three rows against "Same days, 1991-2020 average" with "30 of 30 years used"; the reanalysis caveat visible; both slices' fetch dates and the CC BY 4.0 licence. In Arabic the signed difference reads `+1.3` left to right. |
| Governments → Groups, computed | Europe, GDP per capita, 2023: refused first as incomplete (10 of 52 members report), then computed over the reporters on request; the population-weighted card carries its weighting line **visible**: "Weights: stored series SP.POP.TOTL, as of 2023. Covers 10 of 52 members." |
| Settings → Advanced → Statistics producers | "Continents covered: 6 · 29 producers · News page verified for **0 of 29** (about 152 planned)", the method and caveat in the hover. |

## Found by this walk, fixed before it was recorded

1. **The projected tier could never appear.** `src/events/catalog.py` rebuilt each catalogue entry from a
   fixed list of keys and dropped `interval_years`, `last_held` and `recurrence_rule_source`, so
   `src.civic.elections` never saw a sourced rule: once the networked session writes its rules, every one
   would have been silently ignored, and the coverage report would have kept saying "missing:
   interval_years, last_held, recurrence_rule_source" for entries that carry all three. The loader now
   carries them as written (an unquoted YAML date becomes ISO text) and the elections module still decides
   what they are worth: an unreadable interval or a missing source is still no projection
   (`tests/test_elections_catalog_projection.py`, which fails on the old loader).
2. **Every ONI fetch reported a refusal that never happened.** The parser refuses CPC's header line on
   purpose (pinned by its own tests), and the Climate tab printed it as "1 lines refused by the parser as
   not matching the documented layout". The header is now counted apart (`header_lines`) and a genuinely
   foreign line is still a refusal (`tests/test_climate_api.py::test_the_oni_header_is_the_documented_layout_not_a_refused_line`,
   which fails without the fix).
3. **The directory's method and caveat hover was English in every language.** It is a caveat surface and
   ships ×12: both sentences are now locale keys, drawn through `t()`.
4. **"stored series SP.POP.TOTL" sat in English inside every translated weighting line.** The two shapes
   the server writes (`stored series {id}`, `operator table: {name}`) are now drawn in the UI language with
   the id or the operator's source name verbatim.

## Seen, not changed here

- **Singular counts read as plurals** in English and Spanish ("1 lines", "1 days", "1 events", "1 published
  gaps"). The Living sources walk solved the same thing by rewording to "Label: {n}"; these diagnostics need
  the same pass across twelve languages.
- **Catalogue text is not translated** (event descriptions, cadences such as "every 5 years", tags). In
  Arabic an English description's final full stop lands on the left. It is data from `world_events.yml`, not
  chrome.
- The place form's date inputs follow the browser's locale (MM/DD/YYYY in this headless Chromium), not the
  UI language.

## Reproduce

```
OO_DATA_DIR=<empty dir> OO_DB_PLAINTEXT=1 OO_AUTOSEED=0 python -c "import runpy,sys; sys.path.insert(0,'.'); runpy.run_path('docs/audit/row-a-climate-elections-clickthrough-2026-11-20/seed.py', run_name='__main__')"
cp docs/audit/row-a-climate-elections-clickthrough-2026-11-20/elections_snapshot.json configs/elections_snapshot.json
# append the two lines of walk_events.yml to the events list of configs/world_events.yml (throwaway checkout only)
OO_DATA_DIR=<same dir> OO_DB_PLAINTEXT=1 OO_AUTOSEED=0 python -m uvicorn src.api.main:app --loop asyncio --host 127.0.0.1 --port 8761
OO_WALK_BASE=http://127.0.0.1:8761 OO_WALK_OUT=<dir> node docs/audit/row-a-climate-elections-clickthrough-2026-11-20/walk.js
```

The maintainer's own pass comes after this record (S06-04 §4).
