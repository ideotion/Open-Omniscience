# World Official-Statistics Producers — Verified Directory

Generated 2026-06-25. Records: 152 (122 national, 30 international). Distinct countries with at least one producer: 115.

Companion machine files (the primary deliverable): `producers.json`, `producers.csv`, `coverage_matrix.json`, `machine_endpoint_summary.json`.

## How to read this (verified vs. scaffold)

This directory separates two tiers and never blurs them:

- Tier 1 — verified (32 records). The machine endpoint was confirmed this run, either by a live request, by the sdmx1 daily-CI endpoint catalogue, or by official API documentation. These carry `verified_on` and an `api_base_url`, and are safe to point an ingester at.
- Tier 2 — scaffold (120 records). The organisation and home URL are from background knowledge but were NOT re-verified this run; `verified_on` is null and no endpoint is asserted. Treat these as leads to confirm, not as verified facts. Where a specific URL was uncertain it was set to null rather than guessed.

Per the brief's hard rules: every ISO-3166 country code was mechanically validated (invalid codes forced to null); intergovernmental bodies carry `country: null`; and no quality, credibility, or ranking score is assigned to any producer — this records who publishes, nothing more.

## 1. Coverage matrix

![Coverage by continent](coverage_by_region.png)

| Continent | National producers | Countries covered* | ISO countries (approx.) | Gaps (no producer) |
|---|--:|--:|--:|--:|
| Europe | 35 | 32 | 50 | 18 |
| Asia | 32 | 32 | 53 | 21 |
| Africa | 22 | 22 | 57 | 35 |
| North America | 15 | 12 | 40 | 28 |
| South America | 11 | 10 | 15 | 5 |
| Oceania | 7 | 7 | 24 | 17 |
| **Total** | **122** | **115** | — | **124** |

*Countries covered counts distinct countries; national producers counts records (a country may have an NSO plus a central bank, so producers ≥ countries).

## 2. Machine-endpoint summary

Of 152 records, 32 expose a confirmed machine endpoint:

- 29 are standard SDMX (consumable today by a generic SDMX client) — `sdmx_generic_client`.
- 3 are bespoke REST-JSON needing a custom parser — `bespoke_rest_json`.
- 120 Tier-2 records and 10 known IGO portals are `not_assessed` (endpoint not confirmed this run).

### 2a. SDMX endpoints (generic-client ingestable)

| code | agency | endpoint | api_base_url | conf. |
|---|---|---|---|---|
| ar-indec-sdds | INDEC | SDMX-XML | `https://sdds.indec.gob.ar/files/` | high |
| au-abs | ABS | SDMX-XML | `https://api.data.abs.gov.au` | high |
| be-nbb | NBB / BNB | SDMX-JSON | `https://stat.nbb.be/sdmx-json` | high |
| ca-statcan | StatCan | SDMX-XML | `https://www150.statcan.gc.ca/t1/wds/sdmx/statcan/rest/` | high |
| de-bundesbank | BBk | SDMX-XML | `https://api.statistiken.bundesbank.de/rest` | high |
| ee-stat | SE | SDMX-JSON | `http://andmebaas.stat.ee/sdmx-json` | medium |
| fr-insee | INSEE | SDMX-XML | `https://www.bdm.insee.fr/series/sdmx` | high |
| int-bis | BIS | SDMX-XML | `https://stats.bis.org/api/v1` | high |
| int-ec-dgcomp | DG COMP | SDMX-XML | `https://webgate.ec.europa.eu/comp/redisstat/api/dissemination/sdmx/2.1` | medium |
| int-ec-dgempl | DG EMPL | SDMX-XML | `https://webgate.ec.europa.eu/empl/redisstat/api/dissemination/sdmx/2.1` | medium |
| int-ec-dggrow | DG GROW | SDMX-XML | `https://webgate.ec.europa.eu/grow/redisstat/api/dissemination/sdmx/2.1` | medium |
| int-ecb | ECB | SDMX-XML | `https://data-api.ecb.europa.eu/service` | high |
| int-eurostat | Eurostat | SDMX-XML | `https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1` | high |
| int-eurostat-comext | Eurostat-Comext | SDMX-XML | `https://ec.europa.eu/eurostat/api/comext/dissemination/sdmx/2.1` | high |
| int-ilo | ILO | SDMX-XML | `https://sdmx.ilo.org/rest` | high |
| int-imf | IMF | SDMX-XML | `https://api.imf.org/external/sdmx/2.1` | high |
| int-oecd | OECD | SDMX-XML | `https://sdmx.oecd.org/public/rest` | high |
| int-sdmx-registry | SDMX GR | SDMX-XML | `https://registry.sdmx.org/ws/rest` | high |
| int-spc-pacific | SPC / PDH | SDMX-XML | `https://stats-nsi-stable.pacificdata.org/rest` | high |
| int-unesco-uis | UIS | SDMX-XML | `http://api.uis.unesco.org/sdmx` | high |
| int-unicef | UNICEF | SDMX-XML | `https://sdmx.data.unicef.org/ws/public/sdmxapi/rest` | high |
| int-unsd | UNSD | SDMX-XML | `http://data.un.org/WS/rest` | high |
| int-worldbank-wdi-sdmx | WB-WDI | SDMX-XML | `https://api.worldbank.org/v2/sdmx/rest` | high |
| int-worldbank-wits | WB-WITS | SDMX-XML | `https://wits.worldbank.org/API/V1/SDMX/V21/rest` | high |
| it-istat | ISTAT | SDMX-XML | `https://esploradati.istat.it/SDMXWS/rest` | high |
| lt-stat | LSD / VSADAS | SDMX-XML | `https://osp-rs.stat.gov.lt/rest_xml` | high |
| mx-inegi | INEGI | SDMX-XML | `https://sdmx.snieg.mx/servicev6/rest` | high |
| no-norgesbank | Norges Bank | SDMX-XML | `https://data.norges-bank.no/api` | high |
| uy-simel-labour | SIMEL | SDMX-XML | `https://sdmx-mtss.simel.mtss.gub.uy/rest` | high |

### 2b. REST-JSON endpoints (bespoke parser)

| code | agency | api_base_url | example_query_url | conf. |
|---|---|---|---|---|
| int-fao-faostat | FAO | `https://fenixservices.fao.org/faostat/api/v1` | `https://fenixservices.fao.org/faostat/api/v1/en/definitions/types/area?datasource=DB4` | high |
| int-who-gho | WHO GHO | `https://ghoapi.azureedge.net/api` | `https://ghoapi.azureedge.net/api/Indicator` | medium |
| int-worldbank-wdi-classic | WB-WDI | `https://api.worldbank.org/v2` | `https://api.worldbank.org/v2/country/all/indicator/SP.POP.TOTL?format=json&per_page=5` | high |

## 3. Could-not-verify list

Everything below is deliberately left endpoint-unverified. Nothing here should be ingested as fact without a confirming request.

### 3a. IGO portals known but endpoint not asserted (10)

Organisation and data portal are well established, but no machine endpoint was confirmed this run, so `endpoint_type` is null:

| code | organisation | data portal | reason |
|---|---|---|---|
| int-adb-kidb | Asian Development Bank — Key Indicators / Data Library | https://kidb.adb.org | endpoint not assessed this run |
| int-afdb-opendata | African Development Bank — Open Data / Statistics | https://dataportal.opendataforafrica.org | endpoint not assessed this run |
| int-afristat | Economic and Statistical Observatory for Sub-Saharan Africa | — | endpoint not assessed this run |
| int-caricom-stats | CARICOM Regional Statistics | — | endpoint not assessed this run |
| int-cisstat | Interstate Statistical Committee of the CIS | — | endpoint not assessed this run |
| int-gccstat | GCC Statistical Centre | — | endpoint not assessed this run |
| int-idb-numbersforDev | Inter-American Development Bank — Numbers for Development | https://data.iadb.org | endpoint not assessed this run |
| int-unctad-stat | United Nations Conference on Trade and Development — UNCTADstat | https://unctadstat.unctad.org | endpoint not assessed this run |
| int-undp-hdr | United Nations Development Programme — Human Development Reports | https://hdr.undp.org/data-center | endpoint not assessed this run |
| int-wto-stats | World Trade Organization — WTO Stats | https://stats.wto.org | endpoint not assessed this run |

### 3b. National scaffold records (120)

These NSOs / sectoral bodies have a home URL from background knowledge but were not re-verified this run (`verified_on: null`). Listed by code for follow-up; full rows are in the machine files:

  ae-fcsc, am-armstat, ao-ine, at-statistik, az-stat, bd-bbs, be-statbel, bg-nsi
  bo-ine, br-ibge, bw-statsbots, by-belstat, ch-bfs, ci-ins, cl-ine, cm-ins
  cn-nbs, co-dane, cr-inec, cu-onei, cz-czso, de-destatis, dk-dst, do-one
  dz-ons, ec-inec, eg-capmas, es-ine, et-ess, fi-stat, fj-fbos, gb-ons
  ge-geostat, gh-gss, gr-elstat, gt-ine, hn-ine, hr-dzs, hu-ksh, id-bps
  ie-cso, il-cbs, in-mospi, int-adb-kidb, int-afdb-opendata, int-afristat, int-caricom-stats, int-cisstat
  int-gccstat, int-idb-numbersforDev, int-unctad-stat, int-undp-hdr, int-wto-stats, ir-sci, is-statice, jm-statin
  jo-dos, jp-stat, ke-knbs, kg-stat, kh-nis, kr-kostat, kz-stat, lb-cas
  lk-dcs, lv-csp, ma-hcp, mn-nso, mu-statsmru, my-dosm, mz-ine, na-nsa
  ng-nbs, ni-inide, nl-cbs, no-ssb, np-nso, nz-stats, om-ncsi, pa-inec
  pe-inei, pg-nso, ph-psa, pk-pbs, pl-gus, ps-pcbs, pt-ine, py-ine
  qa-npc, ro-insse, rs-stat, ru-rosstat, rw-nisr, sa-gastat, se-scb, sg-singstat
  si-surs, sk-statistics, sn-ansd, th-nso, tn-ins, to-statistics, tr-tuik, tt-cso
  tz-nbs, ua-ukrstat, ug-ubos, us-bea, us-bls, us-census, us-fred, uy-ine
  uz-stat, ve-ine, vn-gso, vu-vnso, ws-sbs, za-statssa, zm-zamstats, zw-zimstat

## 4. Explicit gap list (countries with no producer yet)

The next countries to chase, grouped by continent. Names and ISO-2 from pycountry:

### Europe (18)

  Albania (AL); Andorra (AD); Bosnia and Herzegovina (BA); Faroe Islands (FO); Gibraltar (GI); Guernsey (GG); Isle of Man (IM); Jersey (JE); Liechtenstein (LI); Luxembourg (LU); Malta (MT); Moldova, Republic of (MD); Monaco (MC); Montenegro (ME); North Macedonia (MK); San Marino (SM); Svalbard and Jan Mayen (SJ); Åland Islands (AX)

### Asia (21)

  Afghanistan (AF); Bahrain (BH); Bhutan (BT); British Indian Ocean Territory (IO); Brunei Darussalam (BN); Christmas Island (CX); Cocos (Keeling) Islands (CC); Cyprus (CY); Hong Kong (HK); Iraq (IQ); Korea, Democratic People's Republic of (KP); Kuwait (KW); Lao People's Democratic Republic (LA); Macao (MO); Maldives (MV); Myanmar (MM); Syrian Arab Republic (SY); Taiwan, Province of China (TW); Tajikistan (TJ); Turkmenistan (TM); Yemen (YE)

### Africa (35)

  Benin (BJ); Burkina Faso (BF); Burundi (BI); Cabo Verde (CV); Central African Republic (CF); Chad (TD); Comoros (KM); Congo (CG); Congo, The Democratic Republic of the (CD); Djibouti (DJ); Equatorial Guinea (GQ); Eritrea (ER); Eswatini (SZ); Gabon (GA); Gambia (GM); Guinea (GN); Guinea-Bissau (GW); Lesotho (LS); Liberia (LR); Libya (LY); Madagascar (MG); Malawi (MW); Mali (ML); Mauritania (MR); Mayotte (YT); Niger (NE); Réunion (RE); Saint Helena, Ascension and Tristan da Cunha (SH); Sao Tome and Principe (ST); Seychelles (SC); Sierra Leone (SL); Somalia (SO); South Sudan (SS); Sudan (SD); Togo (TG)

### North America (28)

  Anguilla (AI); Antigua and Barbuda (AG); Aruba (AW); Bahamas (BS); Barbados (BB); Belize (BZ); Bermuda (BM); Bonaire, Sint Eustatius and Saba (BQ); Cayman Islands (KY); Curaçao (CW); Dominica (DM); El Salvador (SV); Greenland (GL); Grenada (GD); Guadeloupe (GP); Haiti (HT); Martinique (MQ); Montserrat (MS); Puerto Rico (PR); Saint Barthélemy (BL); Saint Kitts and Nevis (KN); Saint Lucia (LC); Saint Martin (French part) (MF); Saint Pierre and Miquelon (PM); Saint Vincent and the Grenadines (VC); Turks and Caicos Islands (TC); Virgin Islands, British (VG); Virgin Islands, U.S. (VI)

### South America (5)

  Falkland Islands (Malvinas) (FK); French Guiana (GF); Guyana (GY); South Georgia and the South Sandwich Islands (GS); Suriname (SR)

### Oceania (17)

  American Samoa (AS); Cook Islands (CK); French Polynesia (PF); Guam (GU); Kiribati (KI); Marshall Islands (MH); Micronesia, Federated States of (FM); Nauru (NR); New Caledonia (NC); Niue (NU); Norfolk Island (NF); Northern Mariana Islands (MP); Palau (PW); Solomon Islands (SB); Tokelau (TK); Tuvalu (TV); Wallis and Futuna (WF)

## 5. Source citations for non-obvious endpoints (verified 2026-06-25)

- SDMX endpoint catalogue (base URLs, content types) — the `sdmx1` Python library's bundled source list, which is re-tested daily by CI. Reference: https://sdmx1.readthedocs.io/en/latest/sources.html and the CI status board https://khaeru.github.io/sdmx . Used for all 27 SDMX base URLs above.
- OECD SDMX — https://sdmx.oecd.org/public/rest (v2 at /public/rest/v2; Data Explorer data-explorer.oecd.org). Confirmed live this run (returned HTTP 429 throttle, i.e. the service is up).
- Eurostat SDMX 2.1 dissemination — https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1 (a 3.0 variant exists).
- World Bank classic REST-JSON — base https://api.worldbank.org/v2 , example https://api.worldbank.org/v2/country/all/indicator/SP.POP.TOTL?format=json . No key; bulk via downloadformat=csv. Confirmed returning data this run. Docs: datahelpdesk.worldbank.org.
- FAOSTAT REST-JSON + bulk-CSV — base https://fenixservices.fao.org/faostat/api/v1 (mirror faostatservices.fao.org/api/v1; bulk bulks-faostat.fao.org). No key. Confirmed this run.
- WHO GHO OData (REST-JSON) — base https://ghoapi.azureedge.net/api , example /Indicator. No auth. CAVEAT: WHO announced deprecation of this endpoint around end-2025 in favour of a new OData service tied to data.who.int — confidence set to medium; re-verify before ingest.
- ILO SDMX — https://sdmx.ilo.org/rest (migrated from www.ilo.org/sdmx/rest around 2024).
- IMF SDMX 2.1 — https://api.imf.org/external/sdmx/2.1 (new Data portal ~Q1 2025; legacy dataservices.imf.org; structure-only sdmxcentral.imf.org).
- Estonia SDMX — http://andmebaas.stat.ee/sdmx-json . CAVEAT: this SDMX service stopped updating around Mar 2023; the current data.stat.ee portal is non-SDMX. Confidence medium.
- Argentina INDEC SDDS — https://sdds.indec.gob.ar/files/ are static SDMX-ML files, not a live query service.

Endpoints not in this list (the remaining SDMX base URLs) are sourced from the same sdmx1 daily-CI catalogue cited in the first bullet.
