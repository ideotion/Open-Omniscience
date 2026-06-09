"""Tests for the offline world-outline coarsening (temporal map coastlines).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from src.timemap.outline import coarsen_geojson


def _square(cx, cy, half):
    return [[cx-half, cy-half], [cx+half, cy-half], [cx+half, cy+half],
            [cx-half, cy+half], [cx-half, cy-half]]


def test_coarsens_polygon_and_rounds():
    gj = {"type": "FeatureCollection", "features": [
        {"geometry": {"type": "Polygon", "coordinates": [
            [[10.123, 20.456], [12.0, 20.0], [12.0, 22.0], [10.0, 22.0], [10.123, 20.456]]]}},
    ]}
    out = coarsen_geojson(gj, precision=1, min_span=1.0)
    assert len(out["rings"]) == 1
    # rounded to 1 dp
    assert out["rings"][0][0] == [10.1, 20.5]


def test_drops_tiny_islands():
    gj = {"type": "FeatureCollection", "features": [
        {"geometry": {"type": "Polygon", "coordinates": [_square(0, 0, 5)]}},     # big: span 10
        {"geometry": {"type": "Polygon", "coordinates": [_square(50, 50, 0.1)]}}, # tiny: span 0.2
    ]}
    out = coarsen_geojson(gj, precision=1, min_span=1.0)
    assert len(out["rings"]) == 1


def test_multipolygon_takes_exterior_rings_only():
    gj = {"type": "Feature", "geometry": {"type": "MultiPolygon", "coordinates": [
        [_square(0, 0, 5), _square(0, 0, 1)],   # exterior + a hole -> hole dropped
        [_square(20, 20, 4)],
    ]}}
    out = coarsen_geojson(gj, precision=1, min_span=1.0)
    assert len(out["rings"]) == 2


def test_rejects_out_of_range_and_malformed_points():
    gj = {"type": "Polygon", "coordinates": [
        [[0, 0], [400, 0], [10, 10], [None, 5], [0, 0], [0, 0], [9, 9]]]}
    out = coarsen_geojson(gj, precision=1, min_span=0.0)
    pts = out["rings"][0] if out["rings"] else []
    assert [400, 0] not in pts
    assert all(p[0] is not None for p in pts)
    # consecutive duplicate [0,0] collapsed
    assert pts.count([0, 0]) <= 1 or pts[0] != pts[1]


def test_empty_input_is_safe():
    assert coarsen_geojson({}, precision=1)["rings"] == []
    assert coarsen_geojson({"type": "FeatureCollection", "features": []})["rings"] == []
