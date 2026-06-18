"""Pure helpers for the bundled offline country polygons (the choropleth base map).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The universal map (``ooMap``) colours each country by a measured quantity (sources,
articles, keywords, sentiment, …). To FILL a country we need its boundary polygon, not
just a coastline — so this module coarsens the public-domain Natural Earth admin-0
countries GeoJSON into a compact ``{iso2: {"name", "rings"}}`` shape keyed by ISO-3166-1
alpha-2 code. We never fabricate geography: the asset is generated once (with network) by
``scripts/build_country_polygons.py`` into ``src/static/world_countries.json``; until then
the choropleth has no fills (it degrades to the graticule/points, never invented borders).
This module holds only the pure, testable transform — no I/O, no network.
"""

from __future__ import annotations

# Reuse the exact ring helpers the coastline builder already uses (rounding, dup-drop,
# bbox span) so both assets coarsen identically.
from src.timemap.outline import _bbox_span, _coarsen_ring, _iter_rings


def iso2_of(props: dict) -> str | None:
    """Resolve a usable ISO-3166-1 alpha-2 code from a Natural Earth feature.

    Natural Earth stamps ``ISO_A2 = "-99"`` for some sovereign entities (France,
    Norway, …) whose code lives in ``ISO_A2_EH`` instead; we honour that fallback so
    those countries are not silently dropped. Returns a lowercase 2-letter code or None.
    """
    for key in ("ISO_A2", "ISO_A2_EH"):
        v = str(props.get(key) or "").strip()
        if len(v) == 2 and v.isalpha():
            return v.lower()
    return None


def coarsen_admin0(geojson: dict, *, precision: int = 1, min_span: float = 0.8) -> dict:
    """Reduce an admin-0 countries GeoJSON to compact per-country fill rings.

    ``precision`` = decimal places kept (1 ≈ 11 km, plenty for a world choropleth);
    ``min_span`` drops tiny islands UNLESS a country would otherwise vanish — every
    country with any usable ring keeps at least its largest, so microstates still render
    and are clickable. Exterior rings only (holes dropped — like the coastline asset; a
    minor over-fill at enclaves is acceptable at world scale and keeps the file small).
    Returns ``{"countries": {iso2: {"name", "rings"}}, "precision", "source"}``; pure.
    """
    out: dict[str, dict] = {}
    for feat in geojson.get("features", []) or []:
        props = feat.get("properties") or {}
        iso = iso2_of(props)
        if not iso:
            continue
        rings: list[list] = []
        for ring in _iter_rings(feat.get("geometry") or {}):
            cr = _coarsen_ring(ring, precision)
            if len(cr) >= 4:
                rings.append(cr)
        if not rings:
            continue
        big = [r for r in rings if _bbox_span(r) >= min_span]
        kept = big if big else [max(rings, key=_bbox_span)]
        name = str(props.get("NAME") or props.get("ADMIN") or iso.upper())
        entry = out.setdefault(iso, {"name": name, "rings": []})
        entry["rings"].extend(kept)
    return {
        "countries": out,
        "precision": precision,
        "source": geojson.get("source", "natural-earth-110m-admin-0"),
    }
