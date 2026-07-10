# Concept memo — Energy as Intelligence: commodity expansion, energy analytics, the global datacenter map

Maintainer request 2026-06-14. Thesis: in the AI era, despite compute capacity, ENERGY
is the binding constraint on intelligence — "energy IS intelligence." Develop an ambitious
plan. (Energy analytics is a REPEAT ask the maintainer says didn't previously land — capture
firmly.) Concept to seed a design doc, not an implementation spec.

## The three asks
1. Extend the commodity list as much as possible ("not sure how").
2. Incorporate energy-related analytics ("not sure how"; REPEAT — didn't get through).
3. A datacenter world-map tool: location + size (power), GPU/CPU counts, technology, owner…

## Pillar 1 — Massive commodity expansion (the "how")
Current: ~28 commodities via FRED (US-centric, Tor-hostile timeouts, dead series
gold/silver/sawnwood 404). The breadth ceiling is the SOURCE. Fix = add comprehensive
official/open providers:
- **World Bank "Pink Sheet"** — ~70 commodities (energy/metals/agri/fertilizers), free
  official CSV/Excel. The single biggest breadth win.
- **IMF Primary Commodity Prices (PCPS, SDMX API)** — ~60 commodities.
- **Exchange open/reference data:** LME, CME, ICE, SHFE, MCX, DCE.
- **UN Comtrade / UNCTAD** (trade flows).
Ingest via the parked OFFICIAL-STATISTICS design: controversial sources + provenance
(producer/methodology/units) + VINTAGES (revisions) + comparability guards + official
machine endpoints (SDMX/API) before scraping + coverage measured per continent
(de-US-centring). Prefer Tor-tolerant official endpoints. Each new commodity extends the
Item-18 symbol↔keyword-family table.

## Pillar 2 — Energy analytics as a first-class THEME ("energy = intelligence")
A dedicated energy domain spanning:
- **PRICES:** oil (WTI/Brent/OPEC basket), gas (Henry Hub/TTF/JKM), coal, LNG, uranium,
  wholesale electricity, carbon (EU ETS).
- **PRODUCTION / CONSUMPTION** by country & source (EIA open API, IEA, Energy Institute
  Statistical Review (ex-BP), Our World in Data).
- **CAPACITY & generation mix** (renewables/nuclear/fossil) — Ember (global electricity),
  IRENA.
- **GRID / real-time:** ENTSO-E (Europe, open API), EIA (US), carbon-intensity feeds.
- **The AI–ENERGY NEXUS:** datacenter electricity demand, PPAs, nuclear restarts for
  compute, grid strain — the thesis made measurable.
Analytics: energy price × corpus article-timeline overlay (Item-18 pattern, co-occurrence ≠
causation); production/consumption trends; carbon intensity; compute–energy linkage. SI /
metric units (app ruling); J/Wh/toe with conversions; provenance + vintages per figure.

## Pillar 3 — The global Datacenter map (flagship new tool)
A geospatial registry on the existing world-map substrate (Natural Earth + gazetteer):
datacenters sized/colored by power, filterable by owner/region/status, with a buildout
timeline.
Attributes (each with method + source + confidence, NEVER fabricated): location,
operator/owner, power capacity (MW), IT load, GPU/CPU counts (where disclosed/estimable),
chip/cooling technology, commissioning date, status, energy source/PPA, PUE.
DATA SOURCES (honest — no single authoritative open set):
- **OpenStreetMap — OSM PBF extracts (e.g. Geofabrik), NOT Organic Maps' lossy MWM** —
  tagged datacenters (`man_made=data_center`) = the seed. The same offline-OSM substrate also
  feeds the gazetteer, energy infra (`power=*`), and place resolution; OSC-diff version
  tracking (Item 8) surfaces new datacenters/plants appearing over time. See ledger Item 22.
- Hyperscaler region disclosures (AWS/Azure/GCP/Meta/Oracle).
- Grid interconnection queues + environmental/planning permits (FERC, ENTSO-E, local).
- **CORPUS-DRIVEN extraction:** the app already extracts place+owner+date+entity from
  articles → a datacenter = (place, owner, capacity, date) tuple deducible from press;
  "deduced from N articles, never confirmed" (the WWW discipline). The map grows from the
  corpus itself — a natural fit.
- Research/agency reports (IEA datacenter energy, academic studies).
HONESTY (critical): GPU counts + exact power are usually proprietary/ESTIMATED → every
attribute marked disclosed vs estimated vs deduced (two-class metadata); confidence + source
+ method shown; never a fabricated number.
SENSITIVITY: aggregating critical-infrastructure locations is dual-use — but ALL from PUBLIC
sources (OSM/filings/press); provenance shown; reproducibility is the defense; nothing
secret. Flag honestly; robots/ToS/ethics stand (don't scrape ToS-violating directories).

## Cross-cutting
- Reuses: the world-map substrate, When×Where×Who extraction, the official-statistics
  ingestion design, the Item-18 symbol↔family + commodity overlay, ooChart, the corpora window.
- Honesty-by-construction: provenance/vintages, SI units, disclosed-vs-deduced,
  co-occurrence-not-causation, coverage measured (de-US-centring).

## Sequencing + scope
- ALPHA slice: World Bank Pink Sheet + IMF SDMX = immediate commodity breadth, AND an energy
  theme tab (prices + production + grid) on those feeds.
- V0.1+ flagship: the datacenter map (OSM seed + corpus extraction, attributes honesty-tiered).

## Open questions / decisions
- v0.1 vs V0.1+ split (commodity-breadth + energy-feeds for alpha; datacenter map later).
- Data licensing (OSM = ODbL; commercial DC directories = ToS-restricted → avoid).
- Estimation methodology for undisclosed GPU/power (publish the method; never assert).
- Sensitivity/ethics review of the infrastructure map (public-source-only; provenance-forward).

## Maintainer ruling (2026-06-14, Q11)
The datacenter map is a **consequence of the OSM ingestion** (the Pillar-3 backbone = OSM PBF;
see ledger Item 22), NOT a predefined app feature. Datacenter analytics become **user-driven**
search/filter over OSM feature classes (no feature-class cap — ledger Item 23), not an
app-predefined "datacenter map" angle. ⇒ For alpha keep **Pillars 1–2** (commodity breadth via
World Bank/IMF + the energy theme/feeds); **Pillar 3 folds into the OSM/map-analytics work**
(Items 22/23) as a user-driven view, gated on the map-UI input.
