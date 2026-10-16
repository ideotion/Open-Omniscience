#!/usr/bin/env python3
"""Scratch tool: tile a real extract K = gx*gy times into one composite country ZZ.

Faithful to what a real extract looks like to the reader: ids are SORTED (libosmium's sparse index needs it) and
SCATTERED uniformly over a planet-sized id space (an id-set's memory depends on the span of the ids, not their count).
Each input element is emitted K times, once per copy, with ids ((rank * K + copy) + 1) * step, so the output stays
sorted by id. Geometry is real, shifted per copy; the border is four invented ways around the grid.
"""
import sys

import osmium
from osmium.osm import mutable

base, out, gx, gy = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
NODE_SPACE, WAY_SPACE, REL_SPACE = 12_000_000_000, 1_350_000_000, 20_000_000
r = osmium.io.Reader(base)
box = r.header().box()
r.close()
dlat = box.top_right.lat - box.bottom_left.lat + 0.02
dlon = box.top_right.lon - box.bottom_left.lon + 0.02
lat0, lon0 = box.bottom_left.lat - 0.01, box.bottom_left.lon - 0.01
copies = [(ix, iy) for ix in range(gx) for iy in range(gy)]
K = len(copies)


class Count(osmium.SimpleHandler):
    def __init__(s):
        super().__init__()
        s.n = s.w = s.r = 0

    def node(s, o):
        s.n += 1 if o.location.valid() else 0

    def way(s, o):
        s.w += 1

    def relation(s, o):
        s.r += 1


c = Count()
c.apply_file(base)
NN, NW, NR = c.n, c.w, c.r
print("base counts", NN, NW, NR, "x", K, file=sys.stderr, flush=True)
step_n, step_w, step_r = NODE_SPACE / (NN * K + 8), WAY_SPACE / (NW * K + 8), REL_SPACE / (NR * K + 8)
B_NODE, B_WAY, B_REL = NODE_SPACE + 1, WAY_SPACE + 1, REL_SPACE + 1

h = osmium.io.Header()
h.set("generator", "tile_extract3.py (composite of a real extract)")
h.set("osmosis_replication_timestamp", "2026-10-15T00:00:00Z")
w = osmium.SimpleWriter(out, 1 << 20, h)
south, north = lat0, lat0 + gy * dlat
west, east = lon0, lon0 + gx * dlon
corners = [(B_NODE + 1, south, west), (B_NODE + 2, south, east), (B_NODE + 3, north, east), (B_NODE + 4, north, west)]

nrank, wrank, rrank = {}, {}, {}


def nid_of(k, ci):
    return int((k * K + ci + 1) * step_n)


def wid_of(k, ci):
    return int((k * K + ci + 1) * step_w)


def rid_of(k, ci):
    return int((k * K + ci + 1) * step_r)


class Nodes(osmium.SimpleHandler):
    def __init__(s):
        super().__init__()
        s.k = 0

    def node(s, n):
        if not n.location.valid():
            return
        nrank[n.id] = s.k
        for ci, (ix, iy) in enumerate(copies):
            w.add_node(mutable.Node(base=n, id=nid_of(s.k, ci), location=(n.location.lon + ix * dlon, n.location.lat + iy * dlat)))
        s.k += 1


class Ways(osmium.SimpleHandler):
    def __init__(s):
        super().__init__()
        s.k = 0

    def way(s, x):
        wrank[x.id] = s.k
        for ci in range(K):
            refs = [nid_of(nrank[nd.ref], ci) if nd.ref in nrank else 20_000_000_000 + nd.ref + ci * 1_000_000_000_000 for nd in x.nodes]
            w.add_way(mutable.Way(base=x, id=wid_of(s.k, ci), nodes=refs))
        s.k += 1


class Rels(osmium.SimpleHandler):
    def __init__(s):
        super().__init__()
        s.k = 0

    def relation(s, x):
        rrank[x.id] = s.k
        for ci in range(K):
            def mp(m):
                if m.type == "n":
                    return nid_of(nrank[m.ref], ci) if m.ref in nrank else 20_000_000_000 + m.ref
                if m.type == "w":
                    return wid_of(wrank[m.ref], ci) if m.ref in wrank else 3_000_000_000 + m.ref
                return rid_of(rrank[m.ref], ci) if m.ref in rrank else 40_000_000 + m.ref
            w.add_relation(mutable.Relation(base=x, id=rid_of(s.k, ci), members=[(m.type, mp(m), m.role) for m in x.members]))
        s.k += 1


Nodes().apply_file(base)
for nid, la, lo in corners:
    w.add_node(mutable.Node(id=nid, location=(lo, la), version=1, timestamp="2026-10-15T00:00:00Z"))
print("nodes", file=sys.stderr, flush=True)
Ways().apply_file(base)
ring = [(B_WAY + 1, [B_NODE + 1, B_NODE + 2]), (B_WAY + 2, [B_NODE + 2, B_NODE + 3]),
        (B_WAY + 3, [B_NODE + 3, B_NODE + 4]), (B_WAY + 4, [B_NODE + 4, B_NODE + 1])]
for wid, refs in ring:
    w.add_way(mutable.Way(id=wid, nodes=refs, version=1, timestamp="2026-10-15T00:00:00Z",
                          tags={"boundary": "administrative", "admin_level": "2"}))
print("ways", file=sys.stderr, flush=True)
Rels().apply_file(base)
w.add_relation(mutable.Relation(id=B_REL + 1, version=1, timestamp="2026-10-15T00:00:00Z",
                                members=[("w", wid, "outer") for wid, _ in ring],
                                tags={"type": "boundary", "boundary": "administrative", "admin_level": "2", "name": "Composite Land",
                                      "ISO3166-1": "ZZ", "ISO3166-1:alpha2": "ZZ", "ISO3166-1:alpha3": "ZZZ"}))
print("rels", file=sys.stderr, flush=True)
w.close()
