"""The pure-Python ``.osm.pbf`` decoder, the lane's small-country path (Q808 = a; S05-04 S1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Every expected value is read from ``scripts/make_osm_fixture.py``'s LITERALS, never from the
decoder itself, so a decoder that got the file wrong cannot agree with itself here.
"""

from __future__ import annotations

import struct
import zlib
from datetime import UTC, datetime

import pytest

from src.osm import pbf
from tests._osm_lane_helpers import FIXTURE, generator


def _all():
    return list(pbf.iter_elements(FIXTURE))


def test_every_node_way_and_relation_decodes_to_the_generators_literals():
    g = generator()
    els = _all()
    nodes = {e.id: e for e in els if isinstance(e, pbf.Node)}
    ways = {e.id: e for e in els if isinstance(e, pbf.Way)}
    rels = {e.id: e for e in els if isinstance(e, pbf.Relation)}

    expected_nodes = [(i, la, lo, {}) for i, la, lo in g.NODES] + g.LANE_NODES
    assert sorted(nodes) == sorted(n[0] for n in expected_nodes)
    for nid, lat, lon, tags in expected_nodes:
        n = nodes[nid]
        assert (n.lat, n.lon) == (lat, lon), nid
        assert n.tags == tags, nid
        assert n.version == g.VERSION
        assert n.timestamp == datetime.fromtimestamp(g.TIMESTAMP, UTC)
    for wid, refs, tags in g.WAYS + g.LANE_WAYS:
        assert ways[wid].refs == tuple(refs)
        assert ways[wid].tags == tags
        assert ways[wid].version == g.VERSION
    for rid, tags, members in [g.RELATION, *g.LANE_RELATIONS]:
        r = rels[rid]
        assert r.tags == tags
        assert [(m.type, m.ref, m.role) for m in r.members] == [("w", ref, role) for ref, role in members]


def test_an_empty_tag_value_survives_as_the_empty_string_never_as_absent():
    pharmacy = next(e for e in _all() if e.id == 7 and isinstance(e, pbf.Node))
    assert "opening_hours" in pharmacy.tags
    assert pharmacy.tags["opening_hours"] == ""


def _records(data: bytes):
    pos = 0
    while pos < len(data):
        (hlen,) = struct.unpack(">i", data[pos : pos + 4])
        hdr = data[pos + 4 : pos + 4 + hlen]
        size = list(pbf._fields(hdr))[-1][2]
        yield hdr, data[pos + 4 + hlen : pos + 4 + hlen + size]
        pos += 4 + hlen + size


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | 0x80 if n else b)
        if not n:
            return bytes(out)


def _len(field: int, payload: bytes) -> bytes:
    return _varint((field << 3) | 2) + _varint(len(payload)) + payload


def _rewrap(tmp_path, *, field: int, compress):
    """The fixture with every blob re-encoded as ``field`` (3 = zlib, 4 = lzma)."""
    out = b""
    for hdr, blob in _records(FIXTURE.read_bytes()):
        raw = pbf._inflate(blob)
        body = _varint(2 << 3) + _varint(len(raw)) + _len(field, compress(raw))
        kind = next(v for f, _w, v in pbf._fields(hdr) if f == 1)
        header = _len(1, bytes(kind)) + _varint(3 << 3) + _varint(len(body))
        out += struct.pack(">i", len(header)) + header + body
    p = tmp_path / "rewrapped.osm.pbf"
    p.write_bytes(out)
    return p


def test_a_zlib_extract_decodes_to_the_same_elements_as_the_raw_fixture(tmp_path):
    """Geofabrik ships zlib; the fixture is raw so its digest can be pinned."""
    p = _rewrap(tmp_path, field=3, compress=zlib.compress)
    assert list(pbf.iter_elements(p)) == _all()


def test_an_lzma_blob_is_REFUSED_by_name_never_skipped(tmp_path):
    import lzma

    p = _rewrap(tmp_path, field=4, compress=lzma.compress)
    with pytest.raises(pbf.UnsupportedCompression, match="LZMA"):
        list(pbf.iter_elements(p))


def test_a_file_cut_short_raises_TruncatedExtract_and_yields_no_partial_country(tmp_path):
    cut = tmp_path / "cut.osm.pbf"
    cut.write_bytes(FIXTURE.read_bytes()[:-20])
    with pytest.raises(pbf.TruncatedExtract):
        list(pbf.iter_elements(cut))


def test_the_header_reports_no_vintage_when_the_file_carries_none():
    """The fixture stamps no replication timestamp: the vintage is unknown, never today."""
    hdr = pbf.read_header(FIXTURE)
    assert hdr.replication_timestamp is None
    assert "make_osm_fixture.py" in (hdr.writing_program or "")
    assert "DenseNodes" in hdr.required_features


def test_a_garbage_file_is_refused_as_not_a_pbf(tmp_path):
    p = tmp_path / "junk.osm.pbf"
    p.write_bytes(b"\x7f\xff\xff\xff" + b"x" * 64)
    with pytest.raises(pbf.PbfError):
        list(pbf.iter_elements(p))
