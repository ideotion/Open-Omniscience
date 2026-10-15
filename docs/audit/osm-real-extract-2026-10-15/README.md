# Row D with real OpenStreetMap bytes, in the sandbox — 2026-10-15 (0.5 row D, S05-04)

**Measured in the remote sandbox · stands in for part of the operator's reference run, not for the
run · awaiting the human UX pass.** Asked for after the user's own run diagnostics could not be had:
carry on with everything that can be done without them. No OpenStreetMap host is reachable from the
sandbox (`download.geofabrik.de`, `planet.openstreetmap.org`, `overpass-api.de` and `www.wikidata.org`
all answer the egress proxy's 403; `raw.githubusercontent.com` and `pypi.org` answer), so every byte
below is from a small real extract that a public GitHub repository carries as test data. **No
OpenStreetMap byte is committed here** (ODbL): this directory holds scripts, the walk's record and four
screenshots, and the numbers.

## The real extracts

| File (where) | Data date | What it is | `scripts/osm_reference_run.py` |
|---|---|---|---|
| `liechtenstein-2013-08-03.osm.pbf` (osm2pgsql's tests) | 2013-08-03 | the whole country, polygon-cut, 593 KB | **ok on both readers**, identical counts and the same gazetteer sha256 |
| `monaco.osm.pbf` (OSRM's tests) | 2016-03-05 | a bounding box around Monaco, 1.76 MB | refused by name: relation 1124039 `could not be closed into a ring (12 member ways, 12 found, 1 left open)` |
| `monaco.pbf` (tilemaker's tests) | 2023-11-21 | a smaller bounding box, 534 KB | refused by name: `14 member ways, 8 found, 2 left open` |
| `andorra.osm.pbf` (GraphHopper's tests) | 2013-05-28 | a bounding box, 565 KB | refused by name: `19 member ways, 17 found, 1 left open` |
| `utrecht_netherlands.osm.pbf` (Valhalla's tests) | undated header | a city, 11.8 MB, 1.16 M nodes, 179 k ways, 1,070 relations | no country relation: used as the density source below |

The three bounding-box files are cut through Monaco's and Andorra's maritime or mountain borders, so
their country relation cannot close: the ingest names that and stops, which is the refusal doing its job
(a Geofabrik extract is cut with its relations whole). Both readers refused the same three, with the same
text.

**Liechtenstein, the only country that closed** (pyosmium, throwaway ENCRYPTED store, the runner's own
report): 7,367 kept objects (3,690 buildings, 2,663 roads, 667 places with metadata, 131 land-use areas,
115 administrative areas, 79 water, 20 `place=*`, 2 power); 2.6 s ingest, 259 MB peak (pure Python:
2.9 s, 262 MB); `osm.db` 3.54 MB settled, which is 480 bytes per object and 6.0 times the extract's bytes;
the encrypted store's header read confirms it is ciphertext at rest. The OSM-only gazetteer: 20 entries,
vintage `2013-08-03`, 3,035 bytes, the same sha256 from both readers.

## What a real extract showed that the synthetic fixture could not

1. **The Places search buried the capital.** `search_names` ordered by FTS5 `rank` alone, and BM25
   favours the shortest document. "Vaduz" the town carries its name in six spellings, five of them translations (a long document);
   a post office named "Vaduz" is one word. Of the 16 matches the town came **16th**, the post office first,
   and the one search box shows the first three (`_PER_GROUP`). Now notable objects lead, then `rank`:
   administrative area, town, post office. Test: `tests/test_osm_places.py::test_a_notable_place_leads_the_matches_however_long_its_names_are`
   (red without the change). Not claimed: that the order among equally notable matches is best (a search for
   "Schaan" lists the village "Schaanwald" first).
2. **The runner's disk floor can pass a run that cannot finish.** The floor is `2 x the extract + reserve` and says
   so. A real extract settled at **6.0 x its own bytes** (Liechtenstein) and **7.5 x** (Utrecht, 11.9 MB to 89.6 MB
   including its WAL), about 500 bytes per kept object, and a large file also keeps 16 bytes a node of locations
   (about 2 x the file) while the cut runs. The runner is handed the CONTINENT file and cannot know the country's share:
   for France in Europe 2 x is plenty, for the United States in North America (14 GB file) the worst case is about
   133 GB against a floor of 30. A refusal at the worst case would turn France away from any disk under 270 GB, so the
   refusal floor is unchanged and the preflight now carries `worst_case_bytes`, derived from the measured ratios, and
   a `warning` naming it (and `--min-free-gb` to refuse instead) whenever the disk is below it and no measured report or
   override replaced the guess; the CLI prints it. The mid-run sampler still stops a run whose disk reaches the reserve.
3. **Memory that grew with the country** (the section below): the search-index build read every object at once; now a page at a time, test red without it (`test_the_index_build_reads_the_country_a_page_at_a_time_and_finds_the_same_rows`).
4. **Two facts about 2013 data, not defects:** the extract holds two nodes named Gamprin-Bendern at one point
   (both `place=village`, both become Places and both rows are in the gazetteer), and its country tag is
   lower-case `li`.

## The reference-VM envelope, and what the memory is

`refvm.sh` runs a command inside a 3.5 GiB memory cgroup that the command sees at the mount root (the
way the reader's own cgroup check, `src/osm/reader.py:cgroup_headroom_bytes`, reads a container's limit)
pinned to two cores. The report records `cgroup_memory_limit_bytes: 3758096384`. The CPU is this machine's,
not the VM's, so **times are not the reference VM's**. The load is real Utrecht data tiled into one composite
country `ZZ` by `tile_extract.py`: every element is emitted once per copy with real tags and shifted geometry,
and ids that are **sorted** (libosmium's location index requires it: an unsorted first try resolved only one
copy's ways) and **spread over a planet-sized id range**. The geometry is a composite and says nothing about
anywhere; use the figures for time, memory and disk per object.

| Composite | PBF | Kept objects | Ingest | Peak RSS | `osm.db` (+WAL) | Objects/s |
|---|---|---|---|---|---|---|
| 1 x, real ids (4 cores, no limit) | 11.9 MB | 177 k | 54 s | 861 MB | 89.6 MB | 3.3 k |
| 1 x, planet-range ids | 13.2 MB | 180 k | 56 s | 1,156 MB | 88.8 MB | 3.2 k |
| 4 x | 23.2 MB | 720 k | 202 s | 1,368 MB | 363 MB | 3.6 k |
| 16 x, before the paged index build | 45.7 MB | 2.88 M | 817 s | **2,213 MB** | 1.46 GB | 3.5 k |
| 16 x, on-disk location index forced, before | 45.7 MB | 2.88 M | 838 s | 2,195 MB | 1.46 GB | 3.4 k |
| 16 x, **after** the paged index build | 45.7 MB | 2.88 M | 835 s | **1,443 MB** | 1.46 GB | 3.4 k |

**Two memories, and one was a defect.** (1) libosmium's id sets: `osmium.index.IdSet` (used by `_IdSet` for the kept
node and way ids) is a bitmap in 512 KB chunks. Measured: 6,000 ids scattered over the node-id range (1.2e10) cost
**1,433 MB** and 6,000,000 cost the same 1,433 MB; 2,000,000 way ids over 1.35e9 cost **160 MB**. Once a country has a few
thousand kept nodes its id sets cost about **1.6 GB flat**, whatever its size: that is why a city peaks at 1.16 GB. The 861 MB
first row is the same effect with Utrecht's own ids, which span 3.8e9 rather than 1.2e10. (2) **The search-index build read
every object with `.all()`**: the 16 x timeline climbs steadily to about 1.4 GB, then jumps to 1.7 to 2.2 GB for the last
seconds before the cut ends and falls back to 1.1 GB. `build_search_index` was the jump: measured alone on a 720 k-object lane,
417 MB before and 190 MB after reading a page of 50,000 rows at a time, and the full 16 x run's peak went from 2,213 MB to
1,443 MB. Without it the jump grows with the country (about 0.45 KB an object) and on a 3.5 GB VM a country of tens of millions of
objects would have ended in the kernel's OOM kill after the whole cut had been read. The on-disk location index changes the peak
disk (1,708 MB against 1,235 MB for the 18.5 M node locations) and not the memory: forcing it moved the peak from 2,213 to 2,195 MB.

What is NOT settled: the cut itself still grows by about 0.13 KB per kept object (1,184 MB at 0.9 GB of `osm.db` to 1,425 MB at 1.4 GB, same
run), from a source this record did not isolate. If that slope holds, 3.5 GiB is reached at about 15 to 19 million objects. At
roughly 500 bytes an object that is a 7 to 9 GB `osm.db`, so France (tens of millions of objects) is on the wrong side of it and
only the real run, with the runner's memory guard stopping it cleanly, will say where.

## The real-data walk (`walk.py`, `walk.json`)

Chromium 1194 through Playwright against the app booted on a `--mini` plaintext state with Liechtenstein
ingested by `scripts/osm_ingest.py` and `osm_countries = ["li"]`; **airplane mode engaged through the app's
endpoint and read back as `online: false` before the first page**, and the browser aborts any request that is not to
the loopback server (0 were attempted). Five surfaces by en and ar by 1440 and 390 px (20 observations).

| Surface | Result |
|---|---|
| World map: the vintage line | `OpenStreetMap places, roads and buildings: Liechtenstein (LIE), as of 2013-08-03 · Settings → OpenStreetMap` |
| Tag completeness (analytic 1) | n = 667; opening hours 11 (1.6 %), website 19 (2.8 %), e-mail 4 (0.6 %), phone 7 (1 %); the four counted separately; the caveat visible; "Per region: the region outlines are not built on this install" |
| Local geocoder | "Bahnhofstrasse" finds four real addresses with points; "Nowhere street 99" says `Not located … Nothing nearby is offered in its place.` |
| Settings → OpenStreetMap | the chosen country reads `Read · data as of 2013-08-03`; the Europe download is `~28.0 GB estimate` |
| Living sources | renders (its OSM block stays hidden: no region outlines) |

No page error, no horizontal overflow, no `undefined`/`NaN`/`[object Object]` text in any of the 20. The only console
errors are four 404s for the row E artifacts that are not built (`osm_admin0.json`, `osm_admin1.json`,
`osm_borders/admin{0,1}.world.json`), which every install without them shows on every map load.

## What stays open until a real run

- **Time and memory on the real 2-core VM, and the cut's remaining 0.13 KB per object** (above). This sandbox's CPU is not that machine's.
- **The true Geofabrik extract.** Sizes are the catalogue's dated estimates (the download reads the exact size
  first). By the ratios above France or Germany would settle near 25 to 35 GB of `osm.db`; that is arithmetic, not
  a measurement, and a continent file's PBF compresses differently from a 12 MB one.
- **The full-history phase.** No real history file is reachable here; only the synthetic one has been run.
- **The Wikidata join.** Liechtenstein 2013 carries zero Wikidata tags, so there was nothing to join, and
  `www.wikidata.org` is refused.
- **The sparse-file location index at real scale.** The on-disk branch runs only above 512 MiB; the forced run
  above exercises it on a 16 x composite, not on a continent file.
- **The human UX pass** (Q1128 = a).
