#!/usr/bin/env python3
"""Scratch tool: a full-history file for a composite country, to run the history phase at scale in the sandbox.

usage: tile_history.py COMPOSITE.osm.pbf OUT.osm.pbf

Reads the composite ``tile_extract.py`` wrote and emits, for every TAGGED node, every way and every relation in it, the
same id with two or three versions: v1 (one tag fewer, 2015), v2 (the current object, 2020), and for every seventh object a
v3 that deletes it (2024). Ids keep the composite's, so they are SORTED and SPREAD OVER A PLANET-SIZED RANGE like the extract's
(a history reader's memory can depend on the span of the ids it is handed). Untagged nodes are left out: the history phase
reads tagged node versions only, and the ways' vertices are not resolved there. The geometry is real but tiled, and says
nothing about anywhere; use the file for time, memory and disk per object.
"""
import sys

import osmium
from osmium.osm import mutable

src, out = sys.argv[1], sys.argv[2]
T1, T2, T3 = "2015-01-01T00:00:00Z", "2020-01-01T00:00:00Z", "2024-01-01T00:00:00Z"

h = osmium.io.Header()
h.set("generator", "tile_history.py (history of a composite)")
h.set("osmosis_replication_timestamp", "2026-10-15T00:00:00Z")
h.has_multiple_object_versions = True
# The header flag alone is not written: libosmium takes the "history" format option from the FILE, not the header.
w = osmium.SimpleWriter(osmium.io.File(out, "pbf,history=true"), 1 << 20, h)


def reduced(tags):
    items = sorted(tags)
    return {k: tags[k] for k in items[:-1]} if len(items) > 1 else {k: tags[k] for k in items}


class Hist(osmium.SimpleHandler):
    def __init__(s):
        super().__init__()
        s.k = {"n": 0, "w": 0, "r": 0}
        s.versions = 0

    def _emit(s, kind, o, add, **extra):
        k = s.k[kind]
        s.k[kind] += 1
        tags = {t.k: t.v for t in o.tags}
        add(mutable.__dict__[{"n": "Node", "w": "Way", "r": "Relation"}[kind]](base=o, version=1, timestamp=T1, visible=True,
                                                                                tags=reduced(tags), **extra))
        add(mutable.__dict__[{"n": "Node", "w": "Way", "r": "Relation"}[kind]](base=o, version=2, timestamp=T2, visible=True,
                                                                                tags=tags, **extra))
        s.versions += 2
        if k % 7 == 0:
            cls = {"n": mutable.Node, "w": mutable.Way, "r": mutable.Relation}[kind]
            gone = {"n": dict(), "w": dict(nodes=[]), "r": dict(members=[])}[kind]
            add(cls(id=o.id, version=3, timestamp=T3, visible=False, tags={}, **gone))
            s.versions += 1

    def node(s, o):
        if o.tags and o.location.valid():
            s._emit("n", o, w.add_node, location=o.location)

    def way(s, o):
        if o.tags:
            s._emit("w", o, w.add_way, nodes=[n.ref for n in o.nodes])

    def relation(s, o):
        if o.tags:
            s._emit("r", o, w.add_relation, members=[(m.type, m.ref, m.role) for m in o.members])


hs = Hist()
hs.apply_file(src)
w.close()
print("objects", hs.k, "versions", hs.versions, file=sys.stderr)
