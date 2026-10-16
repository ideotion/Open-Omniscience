# Row D with real OpenStreetMap bytes, in the sandbox — 2026-10-15 (0.5 row D, S05-04)

**Measured in the remote sandbox · stands in for part of the operator's reference run, not for the
run · awaiting the human UX pass.** Asked for after the user's own run diagnostics could not be had:
carry on with everything that can be done without them. No OpenStreetMap host is reachable from the
sandbox (`download.geofabrik.de`, `planet.openstreetmap.org`, `overpass-api.de` and `www.wikidata.org`
all answer the egress proxy's 403; `raw.githubusercontent.com` and `pypi.org` answer), so every byte
below is from a small real extract that a public GitHub repository carries as test data. **No
extract (`.pbf`/`.osm`) is committed here** (ODbL): this directory holds scripts, the walk's record, four
screenshots and the numbers. The walk's record and one screenshot do show four street addresses with their points that
the local geocoder returned from the public Liechtenstein extract; they are OpenStreetMap data (© OpenStreetMap contributors, ODbL).

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
   147 GB against a floor of 30. A refusal at the worst case would turn France away from any disk under about 300 GB, so the
   refusal floor is unchanged and the preflight now carries `worst_case_bytes`, EXTRAPOLATED from those two small files' settled
   ratios (6 to 7.5 x, the high end taken) plus 3 bytes per extract byte for the node-location file (the forced on-disk run
   below measured +473 MB of peak disk for 18.5 M nodes, about 26 bytes a node; a large file only), and
   a `warning` naming it (and `--min-free-gb` to refuse instead) whenever the disk is below it and no measured report or
   override replaced the guess; the CLI prints it. The mid-run sampler still stops a run whose disk reaches the reserve.
3. **Memory that grew with the country** (the section below): the kept-id sets cost the SPAN of the ids and not their count (now 8 bytes an id), and the search-index build read every object at once; now a page at a time, test red without it (`test_the_index_build_reads_the_country_a_page_at_a_time_and_finds_the_same_rows`). The review of the paging found that it must also be read in id order from the rowid: through the country index SQLite looks up every remaining row of the country and sorts them to keep one page (`EXPLAIN QUERY PLAN` on the real schema: the index plus a temp b-tree; the lane never runs ANALYZE), which costs about the square of the country (reads only, 2 M rows: 5.0 s as one read, 13.9 s paged). The query now takes the rowid plan and the same test reads the plan. The 16 x row below was run before that fix, and the build has no timing since: only the plan has been checked.
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
| 16 x, after the paged index build | 45.7 MB | 2.88 M | 835 s | 1,443 MB | 1.46 GB | 3.4 k |
| 16 x, **after** the paged build and 8-byte kept-id arrays | 45.7 MB | 2.88 M | 758 s | **823 MB** | 1.42 GB | 3.8 k |

**Two memories, and both were defects of this build, not of the country.** (1) **The kept-id sets.** `osmium.index.IdSet` (what `_IdSet`
used for the kept node and way ids) allocates 4 MiB for every 2**25-id window an id falls in (measured, pyosmium 4.3.1), so its memory
follows the SPAN of the ids and not their count: ids spread over the node range (1.2e10 is 358 windows) cost up to **1,433 MB**
(6,000 scattered ids already cost that; a hundred cost about 400 MB), way ids over 1.35e9 up to **160 MB**. A file lists ids
ascending, so the cost also arrives steadily as the scan walks the id space: sorted way ids
added one per step grew the process by 164 MB linearly over the pass, node ids by 1,432 MB (`idset_probe.py` here; the
numbers are the probe's). The composite's tagged ids touch 226 node windows and 41 way windows, about 1 GB, which fits the drop from
1,443 to 823 MB; the 1.16 GB peak of the 177 k-object city is a different mixture and was not isolated to this. It is the slope of the cut through the 16 x run, which
this record first read as "about 0.13 KB of growth per kept object" and extrapolated to a ceiling of 15 to 19 million objects.
**That extrapolation was wrong**: the forced on-disk location index (below) left the slope in place, which refuted the
location-array explanation, and the probe reproduced it with no cut at all. `_IdSet` is now a sorted `array('q')` with a binary
search (8 bytes an id whatever the span; an id out of order goes to a side set, counted in the run record as
`id_sets.out_of_order`). The 16 x run's peak went from 1,443 MB to **823 MB** and its slope through the ways and relations from
about 0.3 MB/s to 0.05 MB/s (633 MB to 654 MB over the last 430 s, the array and the Python heap). (2) **The search-index build read
every object with `.all()`**: the timeline jumped from about 1.4 GB to 1.7 to 2.2 GB for the last seconds before the cut ended. Measured
alone on a 720 k-object lane, 417 MB before and 190 MB after reading a page of 50,000 rows at a time, and the full 16 x run's peak went from
2,213 MB to 1,443 MB. The on-disk location index changes the peak disk (1,708 MB against 1,235 MB for the 18.5 M node locations,
about 26 bytes a node) and not the memory: forcing it moved the peak from 2,213 to 2,195 MB.

What is NOT settled: with both removed the 16 x plateau is about 650 MB, of which the in-memory location array is about 300 MB
(18.5 M nodes at 16 bytes; below 512 MiB of FILE it is chosen whatever the node density: see "The location index" below for the
density arithmetic and the guard that now stops it by name) and the rest is the Python heap, SQLite
and the batch lists. Whether anything still grows with the object count at a hundred times this size is for the real run.

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

## The history phase, the pure-Python reader and the location index (night of 2026-10-16)

Everything here is the same 3.5 GiB, 2-core envelope as above (`refvm.sh`), the sandbox's CPU, and **its times are an upper figure**:
these runs shared the machine with probes and test runs (the same 16 x cut took 642 s on the quiet machine and 1,405 s here), so read the
memory columns, which did not move, and not the seconds.

**The history phase at scale.** `tile_history.py` writes a full-history file for the composite: every tagged node, way and relation with
two or three versions (v1 one tag fewer, v2 the current object, every seventh one deleted), ids as sorted and as spread as the extract's.
It is a SYNTHETIC history of real, tiled objects: it says what the phase costs per version, not what the planet's edits look like.

| Composite | History file | Versions | Phase time | Peak RSS | Peak disk | Rows written |
|---|---|---|---|---|---|---|
| 2 x 2 (4 copies) | 25.3 MB | 3.04 M read | 377 s | 1,204 MB | 949 MB | 7.4 M added |
| 4 x 4 (16 copies), in the envelope | 68.1 MB | 12.18 M read | 2,484 s | **1,250 MB** | 4,779 MB | 29.8 M added |

The memory is a plateau, not a slope: 213 to 224 MB for the first 193 s, then 1,205 MB from 289 s to 1,443 s and 1,234 MB at the end, in
both runs at the same height whatever the file's size. The plateau is `osmium.filter.IdFilter`, which the node pass hands every tracked
node id: it is backed by the same `IdSet` as the kept-id sets (above) and costs **4 MiB for every 2**25-id window an id falls in, whatever
the count** (`idfilter_probe.py`: 1,000 ids spread over 1.2e10 cost the same 1,434 MiB as 4,000,000; 4,000,000 ids inside 8e6 cost 4 MiB; a
Python `set` as `ways_by_id` and `nodes_by_id` pass it costs the same; the memory is returned when the filter is deleted). So this is a
flat price of the id RANGE, paid once per pass and freed, that no country size changes: node ids to 1.2e10 touch at most 358 windows. It
fits the envelope and is not changed; it is now written into the runner's plan (`history_memory`, below). The BORDER pass uses the same
filter on a border's way and node ids and would pay the same price while the border is assembled (a real border's ids are spread over
the range); the composite's border is four invented ways and Liechtenstein's ids are 2013-era, so that one was not measured on a real
border. **Disk:** the phase wrote 3.3 GB on top of a 1.46 GB `osm.db` (12.2 M versions, 29.8 M change rows, about 110 bytes a row);
the preflight counts the history phase as one more ingest-sized footprint, which this synthetic file exceeded by more than two times.
How many rows a real planet history yields per version is not known from here, so the figure is recorded and the guess is not changed.

**The pure-Python reader (no `[geo]` extra) at 16 x.**

| Reader | Cut time | Peak RSS | `osm.db` | Where the locations went |
|---|---|---|---|---|
| pyosmium (kept-id arrays) | 642 s | 823 MB | 1,462,594,696 B | `sparse_mem_array`, 18.5 M nodes at 16 B |
| python | 902 s (979 s with the runner) | **2,263 MB** | 1,468,234,920 B | dict to 9.7 M nodes (budget 1,842,669,568 B = half the cgroup headroom), then a SQLite file |

The counts, the blob sizes and the border are identical to the pyosmium run (compared as dictionaries). The peak is the dict just before
it spills: 2,263 MB less 158 MB of baseline over 9.7 M nodes is about 217 bytes a node of resident memory, 14 % above the 190 of
`DICT_BYTES_PER_NODE` (which the budget divides by), so the budget keeps the process near 63 % of the 3.5 GiB limit rather than 50 %; after
the spill the process settles at 258 to 288 MB, creeping 0.04 MB/s. The pure-Python cut was 1.4 times slower than pyosmium here, where
the database writes dominate; `reader.py` said "one to two orders of magnitude (FROM MEMORY)" and now says what was measured.

**The location index.** The run record now carries `location_index` (`nodes_set`, the index chosen, the rule that chose it, the settled
bytes, and the room it was checked against). `location_probe.py` measured libosmium's `sparse_mem_array` at **16.0 bytes a location** once
settled, with a peak of **1.7 times** that while its vector grows (1,024 MB over 611 MB at 40 M locations). The index is chosen by the
extract FILE's size, so what a node-dense file just under 512 MiB costs is arithmetic on the density: the 16 x composite sets 0.404
locations per file byte (18.49 M in 45.7 MB), which at 512 MiB would be 217 M locations, 3.5 GB settled and about 5.9 GB at the growth
peak; the planet's average, FROM MEMORY about 0.13 nodes a byte, would be 70 M locations, 1.1 GB settled and about 1.9 GB at the peak.
A city extract is the first kind and no such file sits near 512 MiB; the second kind fits. Because the density is only known as the
scan runs, the scan now checks itself: `reader.memory_room()` reads the tighter of the cgroup's headroom and `MemAvailable` once, naming
what is absent, unreadable or "no limit" in `notes` (a limit that cannot be read is never read as unlimited: with nothing readable the
file index is taken), and `_OsmiumLocations` stops with `LocationIndexTooLarge` when `1.7 x settled + 600 MB` would pass that room. The
600 MB is the rest of the cut on the 16 x run (823 MB peak less 296 MB of locations is 527, rounded up); on a 3.5 GiB machine the stop
comes at 115 M locations. The error carries the figures and its way out, `OO_OSM_LOCATION_INDEX=file`, and is written to the country's
row by the ingest's existing handler before anything can be killed.

**The runner's plan.** `--plan` and the start of a run with `--history` now carry `history_memory`: the node filter's 1,432 MiB plus the
256 MiB the phase holds before it, compared with the room read from this machine, as a warning (it starts; the kernel may kill it in the
node pass) or "unchecked" with the reason when no limit could be read. The 8 bytes per tracked id are named and not counted, because
they are known only after the cut.

## What stays open until a real run

- **Time and memory on the real 2-core VM** (above: the cut's memory no longer grows with the country in this sandbox; whether it holds at a hundred times the size is the run's to say). This sandbox's CPU is not that machine's.
- **The true Geofabrik extract.** Sizes are the catalogue's dated estimates (the download reads the exact size
  first). By the ratios above France or Germany would settle near 25 to 35 GB of `osm.db`; that is arithmetic, not
  a measurement, and a continent file's PBF compresses differently from a 12 MB one.
- **The full-history phase on real history.** No real history file is reachable here; the synthetic one above ran at 16 x and says what the phase costs per version, not how many versions and rows a real country's past holds, nor how long the planet file takes to read.
- **The Wikidata join.** Liechtenstein 2013 carries zero Wikidata tags, so there was nothing to join, and
  `www.wikidata.org` is refused.
- **The sparse-file location index at real scale.** The on-disk branch runs only above 512 MiB; the forced run
  above exercises it on a 16 x composite, not on a continent file.
- **The human UX pass** (Q1128 = a).
