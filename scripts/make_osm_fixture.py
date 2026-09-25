#!/usr/bin/env python3
"""Generate the synthetic OSM extract the offline-map lane's CI pass runs on.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q1018 = a asks for "a synthetic wiki edition, a synthetic OSM extract and a synthetic
jurisdiction in ``tests/fixtures/``, so every lane's pipeline runs end-to-end in CI
without a socket". The wiki edition (``scripts/make_wiki_fixture.py``) and the
jurisdiction (``tests/fixtures/law/synthetic/``) exist; this writes the third.

FULLY SYNTHETIC, AND THE CODE SAYS SO. One invented country, ``Fixture Land``, keyed
``ZZ`` -- an ISO 3166-1 alpha-2 code the standard reserves for private use and will
never assign, the two-letter twin of the law fixture's ``ZZZ``. Its border is a square
of four invented nodes a tenth of a degree across, off the coast of Null Island in the
Gulf of Guinea, where no land is. No byte comes from OpenStreetMap, so no ODbL
obligation attaches to it.

THE SHAPE IS A GEOFABRIK ``.osm.pbf``, BUILT BY HAND. An ``OSMHeader`` blob, then one
``OSMData`` blob holding a PrimitiveBlock: a string table, the four nodes as
DenseNodes, the border as TWO open ways, and one ``boundary=administrative``,
``admin_level=2`` relation whose outer members are those two ways. Two ways rather than
one closed way, because stitching open segments into a ring is what the reader does
with real country borders.

DETERMINISTIC, WHICH IS WHY THE BLOBS ARE RAW. The generator reads no clock and uses no
randomness, and it writes each blob uncompressed (``Blob.raw``), which the format
allows and the reader supports. Real extracts are zlib-compressed, but zlib's output
is not the same byte for byte across zlib builds, and a fixture whose bytes depend on
the machine that wrote it cannot have its digest pinned. The zlib path is covered by
re-wrapping this file's data blob at test time (``tests/osm_extract_node_test.js``).

Usage: ``python scripts/make_osm_fixture.py [--out PATH]``. Prints the digest written.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
from pathlib import Path

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "osm" / "synthetic.osm.pbf"

#: The four corners, (id, lat, lon) in degrees. A square from 0.1 to 0.2 on both axes.
NODES = [
    (1, 0.1, 0.1),
    (2, 0.1, 0.2),
    (3, 0.2, 0.2),
    (4, 0.2, 0.1),
]
#: The border as two open ways that share their end nodes: 1-2-3 and 3-4-1.
WAYS = [
    (10, [1, 2, 3], {"boundary": "administrative", "admin_level": "2"}),
    (11, [3, 4, 1], {"boundary": "administrative", "admin_level": "2"}),
]
RELATION = (
    100,
    {
        "type": "boundary",
        "boundary": "administrative",
        "admin_level": "2",
        "ISO3166-1:alpha2": "ZZ",
        "name": "Fixture Land",
    },
    [(10, "outer"), (11, "outer")],
)
GRANULARITY = 100  # nanodegrees per unit: the format's default, 1e-7 degrees


# --- protobuf, the four wire shapes this file needs ------------------------ #
def _varint(n: int) -> bytes:
    if n < 0:
        raise ValueError("unsigned varint only; zigzag signed values first")
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _zigzag(n: int) -> int:
    return (n << 1) ^ (n >> 63)


def _key(field: int, wire: int) -> bytes:
    return _varint((field << 3) | wire)


def _len(field: int, payload: bytes) -> bytes:
    return _key(field, 2) + _varint(len(payload)) + payload


def _uint(field: int, n: int) -> bytes:
    return _key(field, 0) + _varint(n)


def _packed(field: int, values: list[int], *, signed: bool) -> bytes:
    body = b"".join(_varint(_zigzag(v) if signed else v) for v in values)
    return _len(field, body)


def _deltas(values: list[int]) -> list[int]:
    out, prev = [], 0
    for v in values:
        out.append(v - prev)
        prev = v
    return out


# --- the two blocks ---------------------------------------------------------- #
def _header_block() -> bytes:
    # HeaderBlock{ 4: required_features, 16: writingprogram }
    return (
        _len(4, b"OsmSchema-V0.6")
        + _len(4, b"DenseNodes")
        + _len(16, b"open-omniscience scripts/make_osm_fixture.py")
    )


def _primitive_block() -> bytes:
    strings = [""]  # index 0 is reserved as the empty string by the format

    def sid(s: str) -> int:
        if s not in strings:
            strings.append(s)
        return strings.index(s)

    def units(deg: float) -> int:
        return round(deg * 1e9 / GRANULARITY)

    dense = (
        _packed(1, _deltas([n[0] for n in NODES]), signed=True)
        + _packed(8, _deltas([units(n[1]) for n in NODES]), signed=True)
        + _packed(9, _deltas([units(n[2]) for n in NODES]), signed=True)
    )
    ways = b""
    for wid, refs, tags in WAYS:
        ways += _len(
            3,
            _uint(1, wid)
            + _packed(2, [sid(k) for k in tags], signed=False)
            + _packed(3, [sid(v) for v in tags.values()], signed=False)
            + _packed(8, _deltas(refs), signed=True),
        )
    rid, rtags, members = RELATION
    relation = _len(
        4,
        _uint(1, rid)
        + _packed(2, [sid(k) for k in rtags], signed=False)
        + _packed(3, [sid(v) for v in rtags.values()], signed=False)
        + _packed(8, [sid(role) for _ref, role in members], signed=False)
        + _packed(9, _deltas([ref for ref, _role in members]), signed=True)
        + _packed(10, [1 for _ in members], signed=False),  # 1 = way
    )
    # One PrimitiveGroup per kind, as a real writer emits them.
    groups = _len(2, _len(2, dense)) + _len(2, ways) + _len(2, relation)
    table = _len(1, b"".join(_len(1, s.encode("utf-8")) for s in strings))
    return table + groups + _uint(17, GRANULARITY)


def _fileblock(kind: str, block: bytes) -> bytes:
    blob = _len(1, block) + _uint(2, len(block))  # Blob{ 1: raw, 2: raw_size }
    header = _len(1, kind.encode("ascii")) + _uint(3, len(blob))  # BlobHeader{ type, datasize }
    return struct.pack(">i", len(header)) + header + blob


def build() -> bytes:
    return _fileblock("OSMHeader", _header_block()) + _fileblock("OSMData", _primitive_block())


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
