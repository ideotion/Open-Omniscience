"""Pure helpers for the bundled offline world outline (coastlines on the temporal map).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The temporal map projects lat/lon onto an equirectangular grid; a graticule always
renders, but a real land outline makes it legible. We don't fabricate geography — the
outline is generated once (with network) from public-domain Natural Earth data by
``scripts/build_world_outline.py`` into ``src/static/world_outline.json``. This module
holds only the pure, testable transform that coarsens that GeoJSON into the compact
``{"rings": [[[lon, lat], ...], ...]}`` shape the renderer consumes — no I/O, no network.
"""

from __future__ import annotations


def _iter_rings(geometry: dict):
    """Yield exterior rings (lists of [lon, lat]) from a Polygon/MultiPolygon geometry."""
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if gtype == "Polygon":
        if coords:
            yield coords[0]  # exterior ring only (drop holes — coastline is enough)
    elif gtype == "MultiPolygon":
        for poly in coords:
            if poly:
                yield poly[0]


def _coarsen_ring(ring: list, precision: int) -> list:
    """Round coordinates and drop consecutive duplicates after rounding."""
    out: list[list[float]] = []
    for pt in ring:
        try:
            lon, lat = round(float(pt[0]), precision), round(float(pt[1]), precision)
        except (TypeError, ValueError, IndexError):
            continue
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            continue
        if out and out[-1] == [lon, lat]:
            continue
        out.append([lon, lat])
    return out


def _bbox_span(ring: list) -> float:
    """A cheap size proxy: the larger of the lon/lat extents (degrees)."""
    if not ring:
        return 0.0
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return max(max(lons) - min(lons), max(lats) - min(lats))


def coarsen_geojson(geojson: dict, *, precision: int = 1, min_span: float = 1.0) -> dict:
    """Reduce a land GeoJSON to compact exterior rings for offline rendering.

    ``precision`` is decimal places kept (1 ≈ 11 km — plenty for a world map);
    ``min_span`` drops islands smaller than that many degrees so the file stays small.
    Returns ``{"rings": [...], "source": ...}``; pure and order-preserving.
    """
    features = geojson.get("features")
    geometries = []
    if features:
        geometries = [f.get("geometry") or {} for f in features]
    elif geojson.get("type") in ("Polygon", "MultiPolygon"):
        geometries = [geojson]
    elif geojson.get("geometry"):
        geometries = [geojson["geometry"]]

    rings: list[list] = []
    for geom in geometries:
        for ring in _iter_rings(geom):
            cr = _coarsen_ring(ring, precision)
            if len(cr) >= 4 and _bbox_span(cr) >= min_span:
                rings.append(cr)
    return {"rings": rings, "source": geojson.get("source", "natural-earth-110m-land")}
