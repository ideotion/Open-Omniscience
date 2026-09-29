#!/usr/bin/env python3
"""Generate the synthetic FULL-HISTORY OSM file the lane's history cut runs on (S05-04 S4).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q814 = b: the lane's history depth is the full-history planet, ONE planet-wide file. No CI
runner can hold it, so this writes the same SHAPE by hand, beside the current-state fixture
(``scripts/make_osm_fixture.py``) whose country, ids and coordinates it reuses: every object
of ``Fixture Land`` (``ZZ``, the ISO private-use code) with its past versions, plus the objects
that are gone from the current file and are exactly what a history file adds.

WHAT A HISTORY FILE HAS THAT AN EXTRACT DOES NOT. Several versions of one id, consecutive and
in version order; a ``visible`` flag, false on a deleted version (``Info`` / ``DenseInfo``
field 6); and the header's ``HistoricalInformation`` feature. Each is written below, because a
reader that skips one of them reads a history file as a stranger current one.

EACH OBJECT IS HERE FOR ONE CLAUSE of ``src/osm/history.py``:

* node 5 (the cafe): three versions, tags added at each -- the adoption rows;
* node 6 (the bakery): ``contact:email`` added later;
* node 7 (the pharmacy): ``opening_hours`` set, then EMPTIED -- a modification to ``""``,
  never a removal;
* node 26 (a butcher): created, then DELETED -- a closure the current extract cannot show;
* node 27 (a bench): its tags removed while the node stays -- not a deletion;
* node 28 (a cafe): first mapped OUTSIDE the border, then moved in -- its whole history counts;
* node 29 (a cafe): always outside -- never in the cut;
* way 15 (a service road): created, then deleted, so it is in no current cut -- the STATED GAP
  (a deleted way's country needs its nodes' past locations, which the cut does not index).

Deterministic like its twin: literal timestamps, raw blobs, no clock, no randomness.

Usage: ``python scripts/make_osm_history_fixture.py [--out PATH]``. Prints the digest written.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import make_osm_fixture as base  # noqa: E402

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "osm" / "synthetic-history.osm.pbf"

#: 2015-01-01, 2020-01-01 and 2025-01-01, 00:00 UTC. Literals, never a clock.
T1, T2, T3 = 1420070400, 1577836800, 1735689600
#: The file's replication timestamp, its VINTAGE: 2025-01-06T00:00:00Z.
VINTAGE = 1736121600

_LANE = {nid: (lat, lon, tags) for nid, lat, lon, tags in base.LANE_NODES}
_CAFE = _LANE[5][2]

#: (id, version, timestamp, visible, lat, lon, tags), in id then version order.
NODES: list[tuple[int, int, int, bool, float, float, dict[str, str]]] = [
    *[(nid, 1, T1, True, lat, lon, {}) for nid, lat, lon in base.NODES],
    (5, 1, T1, True, 0.15, 0.15, {"amenity": "cafe", "name": "Fixture Cafe"}),
    (5, 2, T2, True, 0.15, 0.15, {"amenity": "cafe", "name": "Fixture Cafe",
                                  "opening_hours": "Mo-Fr 08:00-18:00", "website": "https://cafe.invalid"}),
    (5, 3, T3, True, 0.15, 0.15, dict(_CAFE)),
    (6, 1, T1, True, 0.12, 0.18, {"shop": "bakery", "name": "Fixture Bakery", "phone": "+000 0000 0002"}),
    (6, 2, T3, True, 0.12, 0.18, dict(_LANE[6][2])),
    (7, 1, T1, True, 0.18, 0.12, {"amenity": "pharmacy", "name": "Fixture Pharmacy",
                                  "opening_hours": "Mo-Sa 09:00-19:00"}),
    (7, 2, T3, True, 0.18, 0.12, dict(_LANE[7][2])),
    (8, 1, T1, True, 0.14, 0.16, dict(_LANE[8][2])),
    (9, 1, T1, True, 0.3, 0.3, dict(_LANE[9][2])),
    *[(nid, 1, T1, True, _LANE[nid][0], _LANE[nid][1], {}) for nid in (20, 21, 22, 23, 24, 25)],
    (26, 1, T1, True, 0.15, 0.12, {"shop": "butcher", "name": "Fixture Butcher"}),
    (26, 2, T2, False, 0.0, 0.0, {}),
    (27, 1, T1, True, 0.11, 0.11, {"amenity": "bench"}),
    (27, 2, T3, True, 0.11, 0.11, {}),
    (28, 1, T1, True, 0.3, 0.3, {"amenity": "cafe", "name": "Drifting Cafe"}),
    (28, 2, T2, True, 0.19, 0.19, {"amenity": "cafe", "name": "Drifting Cafe"}),
    (29, 1, T1, True, 0.4, 0.4, {"amenity": "cafe", "name": "Far Cafe"}),
    (30, 1, T1, True, 0.12, 0.12, {}),
    (31, 1, T1, True, 0.12, 0.14, {}),
]

_LANE_WAYS = {wid: (refs, tags) for wid, refs, tags in base.LANE_WAYS}

#: (id, version, timestamp, visible, refs, tags).
WAYS: list[tuple[int, int, int, bool, list[int], dict[str, str]]] = [
    *[(wid, 1, T1, True, refs, tags) for wid, refs, tags in base.WAYS],
    (12, 1, T1, True, [20, 21], {"highway": "residential", "name": "Fixture Road"}),
    (12, 2, T3, True, [20, 21], dict(_LANE_WAYS[12][1])),
    (13, 1, T1, True, [22, 23, 24, 25, 22], {"building": "yes"}),
    (13, 2, T3, True, [22, 23, 24, 25, 22], dict(_LANE_WAYS[13][1])),
    (14, 1, T1, True, [20, 22], {}),
    (15, 1, T1, True, [30, 31], {"highway": "service"}),
    (15, 2, T2, False, [], {}),
]

#: (id, version, timestamp, visible, tags, members).
RELATIONS: list[tuple[int, int, int, bool, dict[str, str], list[tuple[int, str]]]] = [
    (base.RELATION[0], 1, T1, True, base.RELATION[1], base.RELATION[2]),
    *[(rid, 1, T2, True, tags, members) for rid, tags, members in base.LANE_RELATIONS],
]


def _header_block() -> bytes:
    # HeaderBlock{ 4: required_features, 16: writingprogram, 32: osmosis_replication_timestamp }
    return (
        base._len(4, b"OsmSchema-V0.6")
        + base._len(4, b"DenseNodes")
        + base._len(4, b"HistoricalInformation")
        + base._len(16, b"open-omniscience scripts/make_osm_history_fixture.py")
        + base._uint(32, VINTAGE)
    )


def _primitive_block() -> bytes:
    strings = [""]

    def sid(s: str) -> int:
        if s not in strings:
            strings.append(s)
        return strings.index(s)

    def units(deg: float) -> int:
        return round(deg * 1e9 / base.GRANULARITY)

    kv: list[int] = []
    for *_rest, tags in NODES:
        for k, v in tags.items():
            kv += [sid(k), sid(v)]
        kv.append(0)
    n = len(NODES)
    dense_info = (
        base._packed(1, [nd[1] for nd in NODES], signed=False)
        + base._packed(2, base._deltas([nd[2] for nd in NODES]), signed=True)
        + base._packed(3, [0] * n, signed=True)
        + base._packed(4, [0] * n, signed=True)
        + base._packed(5, [0] * n, signed=True)
        + base._packed(6, [1 if nd[3] else 0 for nd in NODES], signed=False)
    )
    dense = (
        base._packed(1, base._deltas([nd[0] for nd in NODES]), signed=True)
        + base._len(5, dense_info)
        + base._packed(8, base._deltas([units(nd[4]) for nd in NODES]), signed=True)
        + base._packed(9, base._deltas([units(nd[5]) for nd in NODES]), signed=True)
        + base._packed(10, kv, signed=False)
    )

    def info(version: int, stamp: int, visible: bool) -> bytes:
        return base._len(4, base._uint(1, version) + base._uint(2, stamp) + base._uint(6, 1 if visible else 0))

    def kvs(tags: dict[str, str]) -> bytes:
        if not tags:
            return b""
        return base._packed(2, [sid(k) for k in tags], signed=False) + base._packed(
            3, [sid(v) for v in tags.values()], signed=False
        )

    ways = b""
    for wid, version, stamp, visible, refs, tags in WAYS:
        refs_field = base._packed(8, base._deltas(refs), signed=True) if refs else b""
        ways += base._len(3, base._uint(1, wid) + kvs(tags) + info(version, stamp, visible) + refs_field)
    relations = b""
    for rid, version, stamp, visible, tags, members in RELATIONS:
        relations += base._len(
            4,
            base._uint(1, rid)
            + kvs(tags)
            + info(version, stamp, visible)
            + base._packed(8, [sid(role) for _ref, role in members], signed=False)
            + base._packed(9, base._deltas([ref for ref, _role in members]), signed=True)
            + base._packed(10, [1 for _ in members], signed=False),
        )
    groups = base._len(2, base._len(2, dense)) + base._len(2, ways) + base._len(2, relations)
    table = base._len(1, b"".join(base._len(1, s.encode("utf-8")) for s in strings))
    return table + groups + base._uint(17, base.GRANULARITY)


def build() -> bytes:
    return base._fileblock("OSMHeader", _header_block()) + base._fileblock("OSMData", _primitive_block())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    data = build()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(data)
    print(f"sha256  {hashlib.sha256(data).hexdigest()}")
    print(f"bytes   {len(data)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
