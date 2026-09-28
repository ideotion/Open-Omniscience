"""The country cut's geometry: stitching, the grid inside-test, the stored shape (S05-04 S1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The grid is an optimisation, so the property it must keep is EXACTNESS: for every point, its
answer equals a plain ray-cast against every edge. Checked on shapes the square fixture cannot
express -- a concave border, a hole (an enclave), two islands -- over thousands of points,
deliberately including points on the grid's own cell lines.
"""

from __future__ import annotations

import math
import random

import pytest

from src.osm.geometry import (
    Border,
    BorderError,
    decode_coords,
    encode_coords,
    representative_point,
    stitch,
)


def _brute(rings, lat, lon):
    inside = False
    for ring in rings:
        for (a_lat, a_lon), (b_lat, b_lon) in zip(ring, ring[1:], strict=False):
            if (a_lat > lat) != (b_lat > lat):
                x = a_lon + (lat - a_lat) * (b_lon - a_lon) / (b_lat - a_lat)
                if lon < x:
                    inside = not inside
    return inside


L_SHAPE = [[(0, 0), (0, 4), (1, 4), (1, 1), (4, 1), (4, 0), (0, 0)]]
WITH_HOLE = [
    [(0, 0), (0, 10), (10, 10), (10, 0), (0, 0)],
    [(3, 3), (3, 6), (6, 6), (6, 3), (3, 3)],
]
ISLANDS = [
    [(0, 0), (0, 1), (1, 1), (1, 0), (0, 0)],
    [(5, 5), (5, 7), (7, 6), (5, 5)],
]
# A jagged border with many vertices, like a real coastline.
_rng = random.Random(7)
JAGGED = [[(round(10 + (4 + _rng.random()) * math.sin(t / 50 * 6.283), 5),
            round(20 + (4 + _rng.random()) * math.cos(t / 50 * 6.283), 5)) for t in range(50)]]
JAGGED[0].append(JAGGED[0][0])


@pytest.mark.parametrize("rings", [L_SHAPE, WITH_HOLE, ISLANDS, JAGGED], ids=["L", "hole", "islands", "jagged"])
@pytest.mark.parametrize("grid", [1, 7, 64])
def test_the_grid_answers_exactly_what_a_full_ray_cast_answers(rings, grid):
    b = Border(rings, grid=grid)
    rng = random.Random(grid)
    pts = [(rng.uniform(b.min_lat - 1, b.max_lat + 1), rng.uniform(b.min_lon - 1, b.max_lon + 1)) for _ in range(3000)]
    # Points on the lattice's own lines, where an off-by-one in the cell index would show.
    for i in range(grid + 1):
        for j in range(0, grid + 1, max(1, grid // 7)):
            pts.append((b.min_lat + i * b._ch, b.min_lon + j * b._cw))
    wrong = [(la, lo) for la, lo in pts if b.contains(la, lo) != _brute(b.rings, la, lo)]
    assert wrong == [], f"{len(wrong)} of {len(pts)} points disagree, e.g. {wrong[:3]}"


def test_a_hole_is_outside():
    b = Border(WITH_HOLE)
    assert b.contains(1, 1)
    assert not b.contains(4.5, 4.5), "the enclave was counted as the country"


def test_stitch_joins_open_segments_in_any_direction_into_one_closed_ring():
    rings, dropped = stitch([[1, 2, 3], [5, 4, 3], [5, 6, 1]])
    assert dropped == 0
    assert len(rings) == 1
    r = rings[0]
    assert r[0] == r[-1]
    assert sorted(set(r)) == [1, 2, 3, 4, 5, 6]


def test_a_segment_that_cannot_close_is_DROPPED_and_counted_never_bridged():
    rings, dropped = stitch([[1, 2, 3], [3, 4, 1], [7, 8, 9]])
    assert len(rings) == 1
    assert dropped == 1


def test_no_ring_is_a_refusal_not_an_empty_country():
    with pytest.raises(BorderError):
        Border([])


def test_coords_round_trip_at_osm_precision():
    pts = [(0.1, 0.1), (-33.8688197, 151.2092955), (89.9999999, -179.9999999), (0.0, 0.0)]
    assert decode_coords(encode_coords(pts)) == pts
    # Five vertices of a building near the fixture: a handful of bytes, not 80.
    assert len(encode_coords([(0.16, 0.16), (0.16, 0.17), (0.17, 0.17), (0.17, 0.16), (0.16, 0.16)])) < 40


def test_representative_point_counts_a_closed_ways_repeated_vertex_once():
    assert representative_point([(0, 0), (0, 2), (2, 2), (2, 0), (0, 0)]) == (1.0, 1.0)
    assert representative_point([]) is None
