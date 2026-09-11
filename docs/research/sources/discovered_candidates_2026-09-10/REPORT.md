# Discovered candidates vs the shipped catalogue — what complements it

**Input:** `open-omniscience-sources.csv` (85,690 rows), the instance's sources export the
maintainer attached on 2026-09-10. **Method:** `scripts/analysis/complement_candidates.py`,
offline, from the file alone — no fetch, no verification. Every discovered row is a Wikidata
claim that an outlet exists and has a website; **none has a feed** and none has been reached.

## 1. Composition

| Set | Rows | With a feed |
|---|---|---|
| Catalogue (enabled) | 3,605 | 2,766 |
| Discovered (`via:wikidata-discovery`) | 81,968 | 0 |
| Other (promoted candidates, hand-added, cited) | 117 | — |

Discovered rows by type: **institution** 37,079, **religious** 22,844, **news** 22,045.
Institutions and religious organisations are **registry entries**, not trial candidates: the
trial judges extraction validity and would admit a ministry's press page as readily as a
newspaper. They stay discoverable, searchable and hand-promotable, and the per-country
institution counts below are the seed of the official-sources vertical.

## 2. The news rows, deduped against the catalogue

| Step | Rows |
|---|---|
| Discovered rows typed `news` | 22,045 |
| Removed: exact domain or known alias already in the catalogue | 0 |
| Kept for classing | 22,045 |
| Flagged (kept): subdomain of a catalogue domain | 398 |
| Flagged (kept): internationalised domain name | 20 |
| Language filled from a single-language ccTLD | 0 |
| Language still unknown after that | 6,014 |

## 3. Gap classes (a class, not a score)

| Class | Meaning | Rows |
|---|---|---|
| T1 | the catalogue has **no** source in the row's country | 30 |
| T2 | the catalogue has 1–4 sources in the country | 1,258 |
| T3 | the row's language has fewer than 20 catalogue sources | 5,121 |
| T4 | none of the above | 15,636 |

Countries with **zero** catalogue sources and at least one discovered news outlet
(12): ai, aw, bq, cw, fk, gi, gl, ky, mo, nu, vg, ye.

The shortlist (`shortlist.csv`, 3,588 rows) holds T1 + T2 + T3, ordered
by class, country and name — **no row outranks another** — capped at 100
per country so the file stays reviewable. Countries the cap truncated (total in brackets):
by (131), cz (269), dk (158), es (136), fi (271), gr (112), hu (195), id (131), il (114), in (210), ir (199), jp (413), kr (165), no (427), pl (780), ro (258), se (341), si (134), ua (277).

## 4. Catalogue vs discovered, by country (top 60 by discovered news rows)

| code | country | region | catalogue | discovered news | discovered institutions |
|---|---|---|---|---|---|
| ca | Canada | North America | 42 | 1845 | 851 |
| br | Brazil | South America | 30 | 1690 | 681 |
| es | Spain | Europe | 40 | 1117 | 1252 |
| pl | Poland | Europe | 20 | 1113 | 334 |
| ru | Russia | Europe | 36 | 957 | 399 |
| it | Italy | Europe | 31 | 792 | 455 |
| in | India | Asia | 83 | 742 | 738 |
| au | Australia | Oceania | 31 | 667 | 727 |
| mx | Mexico | North America | 28 | 598 | 216 |
| jp | Japan | Asia | 22 | 587 | 2256 |
| no | Norway | Europe | 9 | 476 | 306 |
| tr | Türkiye | Asia | 31 | 454 | 231 |
| ua | Ukraine | Europe | 24 | 438 | 620 |
| ro | Romania | Europe | 15 | 430 | 156 |
| ir | Iran | Asia | 18 | 411 | 104 |
| se | Sweden | Europe | 13 | 406 | 397 |
| ar | Argentina | South America | 13 | 383 | 165 |
| cn | China | Asia | 70 | 364 | 970 |
| cz | Czechia | Europe | 11 | 355 | 5737 |
| kr | South Korea | Asia | 20 | 337 | 823 |
| cl | Chile | South America | 11 | 336 | 191 |
| ch | Switzerland | Europe | 18 | 317 | 295 |
| fi | Finland | Europe | 7 | 301 | 210 |
| at | Austria | Europe | 11 | 287 | 196 |
| be | Belgium | Europe | 19 | 278 | 347 |
| hu | Hungary | Europe | 16 | 240 | 170 |
| co | Colombia | South America | 12 | 222 | 115 |
| pt | Portugal | Europe | 14 | 218 | 265 |
| ph | Philippines | Asia | 18 | 209 | 446 |
| id | Indonesia | Asia | 22 | 203 | 1140 |
| ng | Nigeria | Africa | 31 | 200 | 266 |
| za | South Africa | Africa | 19 | 199 | 173 |
| dk | Denmark | Europe | 10 | 186 | 200 |
| il | Israel | Asia | 11 | 173 | 144 |
| gr | Greece | Europe | 18 | 150 | 148 |
| bg | Bulgaria | Europe | 7 | 142 | 831 |
| rs | Serbia | Europe | 12 | 142 | 94 |
| my | Malaysia | Asia | 15 | 138 | 222 |
| hr | Croatia | Europe | 11 | 136 | 82 |
| si | Slovenia | Europe | 4 | 134 | 72 |
| by | Belarus | Europe | 4 | 131 | 200 |
| nz | New Zealand | Oceania | 11 | 125 | 138 |
| tw | Taiwan | Asia | 11 | 123 | 416 |
| ve | Venezuela | South America | 11 | 116 | 77 |
| pe | Peru | South America | 12 | 115 | 145 |
| pk | Pakistan | Asia | 18 | 114 | 143 |
| ie | Ireland | Europe | 9 | 111 | 161 |
| bd | Bangladesh | Asia | 20 | 99 | 199 |
| sk | Slovakia | Europe | 6 | 98 | 86 |
| cu | Cuba | North America | 6 | 89 | 72 |
| iq | Iraq | Asia | 7 | 88 | 65 |
| eg | Egypt | Africa | 18 | 87 | 172 |
| ee | Estonia | Europe | 4 | 81 | 74 |
| nl | Netherlands | Europe | 19 | 80 | 7 |
| ec | Ecuador | South America | 9 | 78 | 67 |
| lt | Lithuania | Europe | 4 | 75 | 157 |
| ba | Bosnia and Herzegovina | Europe | 4 | 65 | 73 |
| lv | Latvia | Europe | 5 | 63 | 108 |
| th | Thailand | Asia | 13 | 63 | 222 |
| ae | United Arab Emirates | Asia | 11 | 59 | 115 |

## 5. By language (top 40 by discovered news rows; ∅ = unknown after the ccTLD fill)

| language | catalogue | discovered news |
|---|---|---|
| ∅ | 247 | 6014 |
| en | 2327 | 4031 |
| es | 195 | 1735 |
| pt | 55 | 1594 |
| ru | 38 | 973 |
| pl | 19 | 760 |
| it | 30 | 597 |
| fr | 205 | 449 |
| ja | 13 | 421 |
| sv | 12 | 363 |
| de | 62 | 340 |
| no | 0 | 340 |
| zh | 31 | 279 |
| uk | 14 | 277 |
| ro | 14 | 270 |
| cs | 9 | 264 |
| tr | 26 | 257 |
| fi | 4 | 255 |
| hu | 12 | 213 |
| fa | 11 | 193 |
| ar | 51 | 174 |
| ko | 10 | 166 |
| da | 8 | 158 |
| id | 18 | 132 |
| sl | 3 | 117 |
| he | 1 | 114 |
| el | 13 | 112 |
| hr | 9 | 97 |
| sr | 10 | 96 |
| bg | 5 | 72 |
| ca | 2 | 71 |
| sk | 5 | 70 |
| hi | 7 | 61 |
| nl | 24 | 57 |
| lt | 3 | 55 |
| nb | 8 | 55 |
| et | 3 | 51 |
| lv | 3 | 49 |
| bn | 15 | 48 |
| hy | 1 | 44 |

## 6. How to read this, and what it is not

- A discovered row that reaches collection still passes the trial: this file changes the
  ORDER in which the discovery queue is worked (complement first), never the gate.
- The classes measure the catalogue's own thinness, not an outlet's worth. A T4 row can be
  the best newspaper in its country; a T1 row can be a defunct site. Nothing offline can tell.
- The catalogue's country field is empty on 1,463 of its
  3,605 rows, so the per-country denominators UNDERSTATE coverage for
  countries whose catalogue sources carry no country. The fix for that is the catalogue's
  NULL-only country reconcile, not this file.
- Nothing here is a source until a feed (or a sitemap) is found and the trial stores real
  articles. The next step is networked: feed autodiscovery over the shortlist, through the
  app's own guarded fetcher.
