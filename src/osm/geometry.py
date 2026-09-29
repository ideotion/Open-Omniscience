"""A country's border, a fast inside test, and the compact encoding a way's shape is stored in.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

HOW A COUNTRY IS CUT FROM A CONTINENT EXTRACT (the design point S05-04 §6 leaves to the PR).
Q806 = b keeps continent-level extracts, so the lane must cut one country out of, say, the
28 GB Europe file. The cut uses the country's OWN border as the extract carries it: the
``boundary=administrative`` + ``admin_level=2`` relation whose ``ISO3166-1:alpha2`` (or
``ISO3166-1``) tag names the country. Its outer and inner member ways are stitched into
closed rings (:func:`assemble_rings`), and an object belongs to the country when its
representative point is inside them (:class:`Border`).

The alternative S05-04 names, S05-05's admin-0 artifact, is row E's and does not exist yet;
the relation is in every Geofabrik extract today. Its cost is stated rather than hidden: three
extra passes over the extract before the main one (relations; the border's ways; their
nodes), each a full decode of the file.

WHAT "INSIDE" MEANS FOR A WAY. A road that crosses the border belongs to ONE country: the one
holding the mean of its vertices. That is a rule, stated in the method the API returns, never
a claim that the whole road lies inside.

WHY A GRID. A national border has tens of thousands of vertices, and a country holds millions
of objects; a plain ray-cast of every object against every edge is quadratic in practice. The
border's bounding box is cut into a ``GRID`` x ``GRID`` lattice once. A cell no edge touches is
wholly inside or wholly outside, decided once from its centre; only a point in a cell an edge
DOES touch pays for an exact test, and that test reads only the edges of its own row band.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

#: Cells per side of the lookup lattice. 512 x 512 = 262,144 cells, built once per ingest.
GRID = 512

_IN, _OUT, _EDGE = 1, 0, 2


class BorderError(ValueError):
    """The extract has no usable border for the requested country."""


def stitch(segments: Iterable[Sequence[int]]) -> tuple[list[list[int]], int]:
    """Join open node-id segments into closed rings.

    Returns ``(rings, dropped)``: each ring's first and last ids are equal, and ``dropped`` is
    how many segments could not be closed into any ring. A dropped segment is REPORTED (the
    country row records it), never silently bridged with a straight line, which would invent a
    border the source never drew.
    """
    pending = [list(s) for s in segments if len(s) >= 2]
    rings: list[list[int]] = []
    dropped = 0
    while pending:
        ring = pending.pop(0)
        progressed = True
        while ring[0] != ring[-1] and progressed:
            progressed = False
            for i, seg in enumerate(pending):
                if seg[0] == ring[-1]:
                    ring.extend(seg[1:])
                elif seg[-1] == ring[-1]:
                    ring.extend(reversed(seg[:-1]))
                elif seg[-1] == ring[0]:
                    ring[:0] = seg[:-1]
                elif seg[0] == ring[0]:
                    ring[:0] = list(reversed(seg[1:]))
                else:
                    continue
                pending.pop(i)
                progressed = True
                break
        if ring[0] == ring[-1] and len(ring) >= 4:
            rings.append(ring)
        else:
            dropped += 1
    return rings, dropped


class Border:
    """Closed rings (lat, lon) and an even-odd inside test over all of them.

    Even-odd across every ring at once handles holes (an enclave's inner ring) and several
    outers (islands) without telling them apart, provided the rings do not overlap -- which
    an administrative border's rings do not.
    """

    def __init__(self, rings: Sequence[Sequence[tuple[float, float]]], *, grid: int = GRID) -> None:
        if not rings:
            raise BorderError("no closed ring")
        self.rings = [list(r) for r in rings]
        lats = [p[0] for r in self.rings for p in r]
        lons = [p[1] for r in self.rings for p in r]
        self.min_lat, self.max_lat = min(lats), max(lats)
        self.min_lon, self.max_lon = min(lons), max(lons)
        self.vertices = sum(len(r) for r in self.rings)
        self._g = grid
        self._ch = (self.max_lat - self.min_lat) / grid or 1e-12
        self._cw = (self.max_lon - self.min_lon) / grid or 1e-12
        # Edges as (lat1, lon1, lat2, lon2), bucketed by the row bands their latitude spans.
        self._bands: list[list[tuple[float, float, float, float]]] = [[] for _ in range(grid)]
        cells = bytearray(grid * grid)  # 0 = not yet an edge cell
        for ring in self.rings:
            for (a_lat, a_lon), (b_lat, b_lon) in zip(ring, ring[1:], strict=False):
                edge = (a_lat, a_lon, b_lat, b_lon)
                r0 = self._row(min(a_lat, b_lat))
                r1 = self._row(max(a_lat, b_lat))
                for r in range(r0, r1 + 1):
                    self._bands[r].append(edge)
                    # The edge's longitude span within this band, conservatively widened to
                    # the whole segment's span: marking one cell too many as an edge cell costs
                    # an exact test, marking one too few would misclassify a whole cell.
                    band_lo = self.min_lat + r * self._ch
                    band_hi = band_lo + self._ch
                    lo_lon, hi_lon = _lon_span(a_lat, a_lon, b_lat, b_lon, band_lo, band_hi)
                    c0 = self._col(lo_lon)
                    c1 = self._col(hi_lon)
                    for c in range(c0, c1 + 1):
                        cells[r * grid + c] = _EDGE
        # Classify the untouched cells. Status can only change across an edge cell, so a run of
        # untouched cells shares one exact test at its first cell's centre.
        for r in range(grid):
            prev = None
            for c in range(grid):
                i = r * grid + c
                if cells[i] == _EDGE:
                    prev = None
                    continue
                if prev is None:
                    lat = self.min_lat + (r + 0.5) * self._ch
                    lon = self.min_lon + (c + 0.5) * self._cw
                    prev = _IN if self._exact(lat, lon) else _OUT
                cells[i] = prev
        self._cells = cells

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """``(min_lat, min_lon, max_lat, max_lon)``."""
        return (self.min_lat, self.min_lon, self.max_lat, self.max_lon)

    def _row(self, lat: float) -> int:
        return min(self._g - 1, max(0, int((lat - self.min_lat) / self._ch)))

    def _col(self, lon: float) -> int:
        return min(self._g - 1, max(0, int((lon - self.min_lon) / self._cw)))

    def in_bbox(self, lat: float, lon: float) -> bool:
        return self.min_lat <= lat <= self.max_lat and self.min_lon <= lon <= self.max_lon

    def _exact(self, lat: float, lon: float) -> bool:
        inside = False
        for a_lat, a_lon, b_lat, b_lon in self._bands[self._row(lat)]:
            if (a_lat > lat) != (b_lat > lat):
                x = a_lon + (lat - a_lat) * (b_lon - a_lon) / (b_lat - a_lat)
                if lon < x:
                    inside = not inside
        return inside

    def contains(self, lat: float, lon: float) -> bool:
        if not self.in_bbox(lat, lon):
            return False
        state = self._cells[self._row(lat) * self._g + self._col(lon)]
        if state == _EDGE:
            return self._exact(lat, lon)
        return state == _IN


def _lon_span(a_lat, a_lon, b_lat, b_lon, lo, hi) -> tuple[float, float]:
    """The longitudes a segment takes while its latitude is within ``[lo, hi]``."""
    if a_lat == b_lat:
        return min(a_lon, b_lon), max(a_lon, b_lon)
    pts = []
    for lat in (lo, hi):
        t = (lat - a_lat) / (b_lat - a_lat)
        if 0.0 <= t <= 1.0:
            pts.append(a_lon + t * (b_lon - a_lon))
    for lat, lon in ((a_lat, a_lon), (b_lat, b_lon)):
        if lo <= lat <= hi:
            pts.append(lon)
    if not pts:
        return min(a_lon, b_lon), max(a_lon, b_lon)
    return min(pts), max(pts)


def representative_point(coords: Sequence[tuple[float, float]]) -> tuple[float, float] | None:
    """The mean of a way's vertices (a closed way's repeated last vertex counted once)."""
    pts = list(coords)
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if not pts:
        return None
    return (
        round(sum(p[0] for p in pts) / len(pts), 7),
        round(sum(p[1] for p in pts) / len(pts), 7),
    )


# --- the stored shape of a way ------------------------------------------- #
# Vertices as 1e-7 degree integers (OSM's own precision), delta-coded and zigzag varints:
# a building's five vertices take about 20 bytes instead of the 80 two floats each would.
def _uvarint(n: int, out: bytearray) -> None:
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return


def encode_coords(coords: Sequence[tuple[float, float]]) -> bytes:
    out = bytearray()
    _uvarint(len(coords), out)
    plat = plon = 0
    for lat, lon in coords:
        ilat, ilon = round(lat * 1e7), round(lon * 1e7)
        for d in (ilat - plat, ilon - plon):
            _uvarint((d << 1) ^ (d >> 63), out)
        plat, plon = ilat, ilon
    return bytes(out)


def decode_coords(data: bytes) -> list[tuple[float, float]]:
    pos = 0

    def rd() -> int:
        nonlocal pos
        result = shift = 0
        while True:
            b = data[pos]
            pos += 1
            result |= (b & 0x7F) << shift
            if not b & 0x80:
                return result
            shift += 7

    n = rd()
    out = []
    lat = lon = 0
    for _ in range(n):
        dl = rd()
        dn = rd()
        lat += (dl >> 1) ^ -(dl & 1)
        lon += (dn >> 1) ^ -(dn & 1)
        out.append((lat / 1e7, lon / 1e7))
    return out
