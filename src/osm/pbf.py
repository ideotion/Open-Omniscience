"""A pure-Python ``.osm.pbf`` decoder: the lane's small-country path (Q808 = a).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q808 = a: «A ``[geo]`` extra with ``pyosmium`` for the extract pass; ``.osc`` diffs are XML and
stay pure Python; without the extra the lane says so and offers the small-country path.» This
module IS that path: it decodes the format with the standard library alone (``struct``,
``zlib``), so a core install can still ingest an extract small enough to read this way.

WHY IT IS BOUNDED, AND BY WHAT. Pure Python is one to two orders of magnitude slower than
pyosmium's C++ (FROM MEMORY; no real extract was read in the sandbox, and the operator's run
records the real figure on the country row). A continent extract (5 to 28 GB) would take this
decoder a day or more, so :data:`SMALL_PATH_MAX_BYTES` refuses a larger file by name
(``src/osm/reader.py``) rather than starting a read nobody should wait for.

WHAT IT DECODES. The OSM PBF format as the wiki page on it describes: a sequence of
``BlobHeader`` + ``Blob`` records; ``OSMHeader`` blocks (the replication timestamp, which is
the extract's VINTAGE) and ``OSMData`` blocks holding ``PrimitiveGroup``s of plain nodes,
``DenseNodes``, ways and relations, each with its ``Info`` (version and timestamp; public
extracts carry no user, uid or changeset since 2018-05-03). Blobs may be raw or zlib; an
LZMA or ZSTD blob is refused BY NAME, never skipped, because skipping a block would drop
every object in it without a trace.

A FILE CUT SHORT STOPS, IT DOES NOT GUESS. A truncated record raises
:class:`TruncatedExtract`, the same stance ``src/static/osmpbf.js`` takes for the in-browser
reader: a partial download must never become a partial country that reads as complete.
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

#: The small-country path's ceiling. 256 MiB holds every Geofabrik country extract of a
#: small country (Luxembourg, Malta, Cyprus, the Baltic states, most of the Caribbean and
#: Oceania, as of 2026 from memory) and no continent. A number the operator can read in
#: the refusal, never a silent truncation.
SMALL_PATH_MAX_BYTES = 256 * 1024 * 1024

#: The format caps a BlobHeader at 64 KiB and a Blob at 32 MiB; a larger one means a
#: corrupt or hostile file, and allocating it would be the failure.
_MAX_HEADER = 64 * 1024
_MAX_BLOB = 32 * 1024 * 1024


class PbfError(ValueError):
    """The file is not a readable ``.osm.pbf``."""


class TruncatedExtract(PbfError):
    """The file ends inside a record: an incomplete download, never a smaller country."""


class UnsupportedCompression(PbfError):
    """A blob compressed with something the standard library cannot inflate (LZMA, ZSTD)."""


@dataclass(frozen=True, slots=True)
class Node:
    id: int
    version: int | None
    timestamp: datetime | None
    tags: dict[str, str]
    lat: float
    lon: float
    #: False on a deleted version, which only a full-history file carries (Info field 6).
    visible: bool = True


@dataclass(frozen=True, slots=True)
class Way:
    id: int
    version: int | None
    timestamp: datetime | None
    tags: dict[str, str]
    refs: tuple[int, ...]
    visible: bool = True


@dataclass(frozen=True, slots=True)
class Member:
    type: str  # "n" | "w" | "r"
    ref: int
    role: str


@dataclass(frozen=True, slots=True)
class Relation:
    id: int
    version: int | None
    timestamp: datetime | None
    tags: dict[str, str]
    members: tuple[Member, ...]
    visible: bool = True


@dataclass(slots=True)
class Header:
    """What an ``OSMHeader`` block says about the file. Every field may be absent."""

    writing_program: str | None = None
    source: str | None = None
    #: The extract's vintage: the replication timestamp the writer stamped. Geofabrik
    #: stamps it; a hand-made file (the fixture) does not, and then it is ``None`` --
    #: the World map tab says "vintage unknown", never today's date.
    replication_timestamp: datetime | None = None
    replication_sequence: int | None = None
    bbox: tuple[float, float, float, float] | None = None  # (min_lon, min_lat, max_lon, max_lat)
    required_features: list[str] = field(default_factory=list)


# --- protobuf wire decoding ------------------------------------------------ #
def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if pos >= len(buf):
            raise PbfError("a varint runs past the end of its message")
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, pos
        shift += 7
        if shift > 70:
            raise PbfError("a varint longer than ten bytes")


def _fields(buf: bytes) -> Iterator[tuple[int, int, int | bytes]]:
    """``(field_number, wire_type, value)`` for every field of one message."""
    pos = 0
    end = len(buf)
    while pos < end:
        key, pos = _varint(buf, pos)
        fnum, wire = key >> 3, key & 7
        if wire == 0:
            val, pos = _varint(buf, pos)
            yield fnum, wire, val
        elif wire == 2:
            n, pos = _varint(buf, pos)
            if pos + n > end:
                raise PbfError("a length-delimited field runs past its message")
            yield fnum, wire, buf[pos : pos + n]
            pos += n
        elif wire == 1:
            yield fnum, wire, buf[pos : pos + 8]
            pos += 8
        elif wire == 5:
            yield fnum, wire, buf[pos : pos + 4]
            pos += 4
        else:
            raise PbfError(f"unsupported protobuf wire type {wire}")


def _packed(buf: bytes) -> list[int]:
    out: list[int] = []
    pos = 0
    end = len(buf)
    while pos < end:
        v, pos = _varint(buf, pos)
        out.append(v)
    return out


def _zz(n: int) -> int:
    return (n >> 1) ^ -(n & 1)


def _packed_signed(buf: bytes) -> list[int]:
    return [_zz(v) for v in _packed(buf)]


def _delta(values: list[int]) -> list[int]:
    out = []
    acc = 0
    for v in values:
        acc += v
        out.append(acc)
    return out


def _signed64(n: int) -> int:
    """A plain (non-zigzag) int64 varint read as two's complement."""
    return n - (1 << 64) if n >= (1 << 63) else n


def _ts(seconds: int | None) -> datetime | None:
    if seconds is None or seconds <= 0:
        return None  # an absent timestamp is absent, never 1970-01-01
    return datetime.fromtimestamp(seconds, UTC)


# --- file records ---------------------------------------------------------- #
def _records(path: Path) -> Iterator[tuple[str, bytes]]:
    """``(blob_type, block_bytes)`` for each record, the block already inflated."""
    with open(path, "rb") as fh:
        while True:
            head = fh.read(4)
            if not head:
                return
            if len(head) < 4:
                raise TruncatedExtract("the file ends inside a record length")
            (hlen,) = struct.unpack(">i", head)
            if hlen <= 0 or hlen > _MAX_HEADER:
                raise PbfError(f"a BlobHeader of {hlen} bytes is not a valid .osm.pbf")
            hbuf = fh.read(hlen)
            if len(hbuf) < hlen:
                raise TruncatedExtract("the file ends inside a BlobHeader")
            btype = ""
            datasize = 0
            for f, _w, v in _fields(hbuf):
                if f == 1:
                    btype = bytes(v).decode("ascii", "replace")  # type: ignore[arg-type]
                elif f == 3:
                    datasize = int(v)  # type: ignore[arg-type]
            if datasize <= 0 or datasize > _MAX_BLOB:
                raise PbfError(f"a Blob of {datasize} bytes is not a valid .osm.pbf")
            blob = fh.read(datasize)
            if len(blob) < datasize:
                raise TruncatedExtract("the file ends inside a Blob")
            yield btype, _inflate(blob)


def _inflate(blob: bytes) -> bytes:
    raw = None
    zdata = None
    raw_size = None
    for f, _w, v in _fields(blob):
        if f == 1:
            raw = bytes(v)  # type: ignore[arg-type]
        elif f == 2:
            raw_size = int(v)  # type: ignore[arg-type]
        elif f == 3:
            zdata = bytes(v)  # type: ignore[arg-type]
        elif f == 4:
            raise UnsupportedCompression("an LZMA-compressed blob; install the [geo] extra")
        elif f in (5, 6, 7):
            raise UnsupportedCompression("a blob in a compression the standard library lacks; install the [geo] extra")
    if raw is not None:
        return raw
    if zdata is not None:
        out = zlib.decompress(zdata)
        if raw_size is not None and len(out) != raw_size:
            raise PbfError("a zlib blob inflated to a size other than the one it declared")
        return out
    raise PbfError("a Blob with no data")


def read_header(path: str | Path) -> Header:
    """The first ``OSMHeader`` block's facts. Reads no data block."""
    hdr = Header()
    for btype, block in _records(Path(path)):
        if btype != "OSMHeader":
            break
        for f, _w, v in _fields(block):
            if f == 1:
                box = {ff: _signed64(int(vv)) for ff, _ww, vv in _fields(v)}  # type: ignore[arg-type]
                if len(box) == 4:
                    hdr.bbox = (box[1] / 1e9, box[4] / 1e9, box[2] / 1e9, box[3] / 1e9)
            elif f == 4:
                hdr.required_features.append(bytes(v).decode("utf-8", "replace"))  # type: ignore[arg-type]
            elif f == 16:
                hdr.writing_program = bytes(v).decode("utf-8", "replace")  # type: ignore[arg-type]
            elif f == 17:
                hdr.source = bytes(v).decode("utf-8", "replace")  # type: ignore[arg-type]
            elif f == 32:
                hdr.replication_timestamp = _ts(_signed64(int(v)))  # type: ignore[arg-type]
            elif f == 33:
                hdr.replication_sequence = _signed64(int(v))  # type: ignore[arg-type]
        break
    return hdr


# --- primitive blocks ------------------------------------------------------ #
class _Block:
    __slots__ = ("strings", "gran", "lat_off", "lon_off", "date_gran", "groups")

    def __init__(self, block: bytes) -> None:
        self.strings: list[str] = []
        self.gran = 100
        self.lat_off = 0
        self.lon_off = 0
        self.date_gran = 1000
        self.groups: list[bytes] = []
        for f, _w, v in _fields(block):
            if f == 1:
                self.strings = [
                    bytes(s).decode("utf-8", "replace")  # type: ignore[arg-type]
                    for ff, _ww, s in _fields(v)  # type: ignore[arg-type]
                    if ff == 1
                ]
            elif f == 2:
                self.groups.append(v)  # type: ignore[arg-type]
            elif f == 17:
                self.gran = int(v)  # type: ignore[arg-type]
            elif f == 18:
                self.date_gran = int(v)  # type: ignore[arg-type]
            elif f == 19:
                self.lat_off = _signed64(int(v))  # type: ignore[arg-type]
            elif f == 20:
                self.lon_off = _signed64(int(v))  # type: ignore[arg-type]

    def lat(self, raw: int) -> float:
        return round((self.lat_off + self.gran * raw) / 1e9, 7)

    def lon(self, raw: int) -> float:
        return round((self.lon_off + self.gran * raw) / 1e9, 7)

    def when(self, raw: int | None) -> datetime | None:
        if raw is None:
            return None
        return _ts(raw * self.date_gran // 1000)

    def tags(self, keys: list[int], vals: list[int]) -> dict[str, str]:
        s = self.strings
        return {s[k]: s[v] for k, v in zip(keys, vals, strict=False)}


def _info(blk: _Block, buf: bytes) -> tuple[int | None, datetime | None, bool]:
    version = None
    ts = None
    visible = True  # absent outside history files, where every version is a live one
    for f, _w, v in _fields(buf):
        if f == 1:
            version = int(v)  # type: ignore[arg-type]
        elif f == 2:
            ts = blk.when(_signed64(int(v)))  # type: ignore[arg-type]
        elif f == 6:
            visible = bool(v)
    return version, ts, visible


def _dense(blk: _Block, buf: bytes) -> Iterator[Node]:
    ids: list[int] = []
    lats: list[int] = []
    lons: list[int] = []
    kv: list[int] = []
    versions: list[int] = []
    stamps: list[int] = []
    visibles: list[int] = []
    for f, _w, v in _fields(buf):
        if f == 1:
            ids = _delta(_packed_signed(v))  # type: ignore[arg-type]
        elif f == 5:
            for ff, _ww, vv in _fields(v):  # type: ignore[arg-type]
                if ff == 1:
                    versions = _packed(vv)  # type: ignore[arg-type]
                elif ff == 2:
                    stamps = _delta(_packed_signed(vv))  # type: ignore[arg-type]
                elif ff == 6:
                    visibles = _packed(vv)  # type: ignore[arg-type]
        elif f == 8:
            lats = _delta(_packed_signed(v))  # type: ignore[arg-type]
        elif f == 9:
            lons = _delta(_packed_signed(v))  # type: ignore[arg-type]
        elif f == 10:
            kv = _packed(v)  # type: ignore[arg-type]
    if not (len(ids) == len(lats) == len(lons)):
        raise PbfError("a DenseNodes group whose id, lat and lon arrays disagree in length")
    s = blk.strings
    k = 0
    for i, nid in enumerate(ids):
        tags: dict[str, str] = {}
        if kv:
            while k < len(kv) and kv[k] != 0:
                tags[s[kv[k]]] = s[kv[k + 1]]
                k += 2
            k += 1  # the 0 that ends this node's pairs
        yield Node(
            id=nid,
            version=versions[i] if i < len(versions) else None,
            timestamp=blk.when(stamps[i]) if i < len(stamps) else None,
            tags=tags,
            lat=blk.lat(lats[i]),
            lon=blk.lon(lons[i]),
            visible=bool(visibles[i]) if i < len(visibles) else True,
        )


def _node(blk: _Block, buf: bytes) -> Node:
    nid = 0
    keys: list[int] = []
    vals: list[int] = []
    lat = lon = 0
    version = None
    ts = None
    visible = True
    for f, _w, v in _fields(buf):
        if f == 1:
            nid = _zz(int(v))  # type: ignore[arg-type]
        elif f == 2:
            keys = _packed(v)  # type: ignore[arg-type]
        elif f == 3:
            vals = _packed(v)  # type: ignore[arg-type]
        elif f == 4:
            version, ts, visible = _info(blk, v)  # type: ignore[arg-type]
        elif f == 8:
            lat = _zz(int(v))  # type: ignore[arg-type]
        elif f == 9:
            lon = _zz(int(v))  # type: ignore[arg-type]
    return Node(nid, version, ts, blk.tags(keys, vals), blk.lat(lat), blk.lon(lon), visible)


def _way(blk: _Block, buf: bytes) -> Way:
    wid = 0
    keys: list[int] = []
    vals: list[int] = []
    refs: list[int] = []
    version = None
    ts = None
    visible = True
    for f, _w, v in _fields(buf):
        if f == 1:
            wid = int(v)  # type: ignore[arg-type]
        elif f == 2:
            keys = _packed(v)  # type: ignore[arg-type]
        elif f == 3:
            vals = _packed(v)  # type: ignore[arg-type]
        elif f == 4:
            version, ts, visible = _info(blk, v)  # type: ignore[arg-type]
        elif f == 8:
            refs = _delta(_packed_signed(v))  # type: ignore[arg-type]
    return Way(wid, version, ts, blk.tags(keys, vals), tuple(refs), visible)


_MEMBER_TYPES = {0: "n", 1: "w", 2: "r"}


def _relation(blk: _Block, buf: bytes) -> Relation:
    rid = 0
    keys: list[int] = []
    vals: list[int] = []
    roles: list[int] = []
    mids: list[int] = []
    types: list[int] = []
    version = None
    ts = None
    visible = True
    for f, _w, v in _fields(buf):
        if f == 1:
            rid = int(v)  # type: ignore[arg-type]
        elif f == 2:
            keys = _packed(v)  # type: ignore[arg-type]
        elif f == 3:
            vals = _packed(v)  # type: ignore[arg-type]
        elif f == 4:
            version, ts, visible = _info(blk, v)  # type: ignore[arg-type]
        elif f == 8:
            roles = _packed(v)  # type: ignore[arg-type]
        elif f == 9:
            mids = _delta(_packed_signed(v))  # type: ignore[arg-type]
        elif f == 10:
            types = _packed(v)  # type: ignore[arg-type]
    s = blk.strings
    members = tuple(
        Member(_MEMBER_TYPES.get(t, "?"), m, s[r] if r < len(s) else "")
        for m, t, r in zip(mids, types, roles, strict=False)
    )
    return Relation(rid, version, ts, blk.tags(keys, vals), members, visible)


def iter_elements(
    path: str | Path,
    *,
    nodes: bool = True,
    ways: bool = True,
    relations: bool = True,
) -> Iterator[Node | Way | Relation]:
    """Every requested element, in file order (nodes, then ways, then relations)."""
    for btype, block in _records(Path(path)):
        if btype != "OSMData":
            continue
        blk = _Block(block)
        for group in blk.groups:
            for f, _w, v in _fields(group):
                if f == 1 and nodes:
                    yield _node(blk, v)  # type: ignore[arg-type]
                elif f == 2 and nodes:
                    yield from _dense(blk, v)  # type: ignore[arg-type]
                elif f == 3 and ways:
                    yield _way(blk, v)  # type: ignore[arg-type]
                elif f == 4 and relations:
                    yield _relation(blk, v)  # type: ignore[arg-type]
