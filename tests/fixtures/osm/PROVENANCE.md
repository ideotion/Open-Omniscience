# `tests/fixtures/osm/` — provenance

**Everything in this directory is wholly synthetic: invented geometry and invented tags
only.** No byte of it is derived from OpenStreetMap or any other external source, so
**no ODbL obligation attaches to it** and nothing here touches the licence questions
that govern a real Geofabrik extract. That is a property of how it was made, not a
claim about how it looks: `synthetic.osm.pbf` is written by
`scripts/make_osm_fixture.py`, which contains every coordinate, tag and name as a
literal.

**The country is `ZZ`, which ISO 3166-1 reserves for private use** and will never assign,
the two-letter twin of the law fixture's `ZZZ`. Its border is a square of four invented
nodes, 0.1° to 0.2° north and east, in open water in the Gulf of Guinea, where no land
is. A row that leaked from a test into a real map would be identifiable on sight.

**It is deterministic.** The generator reads no clock and uses no randomness, and writes
each blob uncompressed (`Blob.raw`, which the format allows), because zlib's output is
not byte-identical across zlib builds. Re-running it produces a byte-identical file,
which is what lets a test pin the fixture's own digest —

```
sha256  95a5d5ea4fb9b4ea14d0cbfd3c7e1869d6800773b6969caf79dc133ac3b96f6f
bytes   1346
```

Regenerate with `python scripts/make_osm_fixture.py`; the script prints the digest it
wrote, and `tests/test_osm_fixture.py` fails if the committed file and the generator
have drifted apart, or if this note's digest goes stale.

## What it is shaped to exercise

| part | what it is for |
| --- | --- |
| an `OSMHeader` blob | the reader must skip it, as it skips a real one |
| four DenseNodes | the delta and granularity decode, checked against the literal degrees |
| two OPEN ways, `1-2-3` and `3-4-1` | stitching open segments into a closed ring, which is what real country borders need |
| one `boundary=administrative`, `admin_level=2` relation, `ISO3166-1:alpha2=ZZ` | the country the reader assembles, keyed the way the choropleth merges it |
| **the OSM lane's objects (0.5 row D, added 2026-09-28)** | every clause of the country cut in `src/osm/ingest.py`, one object each: |
| a cafe with all four completeness tags, `name:fr`, `payment:cash` | analytic 1's full row; a family column; the extended column list |
| a bakery whose e-mail is `contact:email` | the `contact:*` twin counted as present |
| a pharmacy whose `opening_hours` is EMPTY | an empty value stored as `""` and counted ABSENT, never NULL, never present |
| a `place=village` with `name:ar` | a notable place (Q817) |
| a cafe at 0.3/0.3, OUTSIDE the square | the cut must drop it |
| a road, a building with `addr:*`, an untagged way | roads and buildings (Q809 = b); the geocoder's input; an object with no tags never becomes a row |
| a `type=site` relation over the building | a relation stored with NO geometry: a gap, never a (0, 0) |
| `DenseInfo` / `Info` with version 3 and 2025-01-01T00:00:00Z | the lane keeps `version` and `timestamp` (Q813); user, uid and changeset are zero, as public extracts strip them |

Real extracts are zlib-compressed; `tests/osm_extract_node_test.js` re-wraps this file's
data blob through zlib at test time, so the inflate path is covered without putting a
machine-dependent byte into the fixture.

## Who reads it

`tests/test_osm_fixture.py` downloads it through the real `OsmDownloadManager` (the HTTP
client replaced by one that serves these bytes) with the airplane socket guard installed,
counts name resolutions, and hands the file it wrote to the in-browser reader
(`src/static/osmpbf.js`) under node. The versioned OSM adapter is an interface in 0.4;
0.5 consumes this fixture for it (S04-08's S5): `tests/test_osm_pbf.py`, `test_osm_ingest.py`
and `test_osm_completeness.py` run the lane's whole pipeline on it, through both readers.

## `admin_boundaries.osm` and `admin_boundaries.osm.pbf` (0.5 row E)

**Also wholly synthetic**: six invented squares written as literals, no byte from OpenStreetMap. Unlike
`synthetic.osm.pbf` it uses REAL codes (`FR`, `DE`, `FR-IDF`), because the boundary build keys
countries through the app's own ISO converter, which refuses a private-use code by design; the squares
are what make a leaked row identifiable on sight (a square "France" from 0°–10° E, 40°–50° N). It holds
one country, one region tagged `ISO3166-2`, one untagged region, one `boundary=disputed` area claimed by
two parties, one `boundary=claim` naming one, and one `admin_level=8` relation the build must skip.

The `.osm` XML is the readable source; the `.osm.pbf` is that file written by pyosmium with a header
`osmosis_replication_timestamp` of `2026-09-01T00:00:00Z` (the vintage the tests read back), so both of the
lane's reader backends can read it. Not digest-pinned: libosmium's zlib output is not byte-stable across builds.
