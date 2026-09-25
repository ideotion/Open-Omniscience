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
sha256  2ade9a53bdaa8545be12f1ce87c6e4caeabff32fa43b39c1108ff3b6a9502cea
bytes   322
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

Real extracts are zlib-compressed; `tests/osm_extract_node_test.js` re-wraps this file's
data blob through zlib at test time, so the inflate path is covered without putting a
machine-dependent byte into the fixture.

## Who reads it

`tests/test_osm_fixture.py` downloads it through the real `OsmDownloadManager` (the HTTP
client replaced by one that serves these bytes) with the airplane socket guard installed,
counts name resolutions, and hands the file it wrote to the in-browser reader
(`src/static/osmpbf.js`) under node. The versioned OSM adapter is an interface in 0.4;
0.5 consumes this fixture for it (S04-08's S5).
