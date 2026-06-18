"""Tests for the offline country-polygons coarsening (the choropleth base map).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.timemap.countries_geo import coarsen_admin0, iso2_of

_ASSET = Path(__file__).resolve().parents[1] / "src" / "static" / "world_countries.json"


def _square(cx, cy, half):
    return [
        [cx - half, cy - half], [cx + half, cy - half],
        [cx + half, cy + half], [cx - half, cy + half], [cx - half, cy - half],
    ]


def _feat(iso, geom, name="X", **extra):
    props = {"ISO_A2": iso, "NAME": name, **extra}
    return {"type": "Feature", "properties": props, "geometry": geom}


# ----------------------------- iso2_of ---------------------------------- #


def test_iso2_prefers_iso_a2_then_eh_fallback():
    assert iso2_of({"ISO_A2": "FR"}) == "fr"
    # Natural Earth stamps "-99" for some sovereigns; the real code lives in ISO_A2_EH.
    assert iso2_of({"ISO_A2": "-99", "ISO_A2_EH": "NO"}) == "no"
    assert iso2_of({"ISO_A2": "-99"}) is None
    assert iso2_of({"ISO_A2": "XX1"}) is None
    assert iso2_of({}) is None


# --------------------------- coarsen_admin0 ----------------------------- #


def test_keys_by_iso_and_rounds():
    gj = {"features": [_feat("DE", {"type": "Polygon",
          "coordinates": [[[10.123, 50.456], [12.0, 50.0], [12.0, 52.0], [10.0, 52.0], [10.123, 50.456]]]})]}
    out = coarsen_admin0(gj, precision=1, min_span=0.5)
    assert set(out["countries"]) == {"de"}
    de = out["countries"]["de"]
    assert de["name"] == "X" and len(de["rings"]) == 1
    assert de["rings"][0][0] == [10.1, 50.5]  # rounded to 1 dp
    assert out["precision"] == 1


def test_multipolygon_yields_multiple_rings_per_country():
    gj = {"features": [_feat("JP", {"type": "MultiPolygon", "coordinates": [
        [_square(135, 35, 4)], [_square(140, 40, 3)]]})]}
    out = coarsen_admin0(gj, precision=1, min_span=0.5)
    assert len(out["countries"]["jp"]["rings"]) == 2


def test_microstate_keeps_its_largest_ring_even_below_min_span():
    # A tiny island nation (span 0.4) must NOT vanish — every country with a ring renders.
    gj = {"features": [_feat("TV", {"type": "Polygon", "coordinates": [_square(179, -8, 0.2)]})]}
    out = coarsen_admin0(gj, precision=2, min_span=1.0)
    assert "tv" in out["countries"] and len(out["countries"]["tv"]["rings"]) == 1


def test_iso_eh_fallback_country_is_kept():
    gj = {"features": [_feat("-99", {"type": "Polygon", "coordinates": [_square(8, 60, 5)]},
                             name="Norway", ISO_A2_EH="NO")]}
    out = coarsen_admin0(gj, min_span=0.5)
    assert out["countries"]["no"]["name"] == "Norway"


def test_feature_without_iso_is_dropped():
    gj = {"features": [_feat("-99", {"type": "Polygon", "coordinates": [_square(0, -80, 10)]})]}
    assert coarsen_admin0(gj)["countries"] == {}


def test_empty_input_is_safe():
    assert coarsen_admin0({})["countries"] == {}
    assert coarsen_admin0({"features": []})["countries"] == {}


# ------------------------- the committed asset -------------------------- #


def test_bundled_asset_shape_and_coverage():
    """The generated world_countries.json covers the major countries and is honest
    about its shape (ISO-keyed, precision recorded). Microstates the 110m source is too
    coarse to include are handled by the renderer's centroid fallback, not invented here.
    """
    if not _ASSET.exists():
        return  # built once on a networked machine (like world_outline.json)
    data = json.loads(_ASSET.read_text(encoding="utf-8"))
    countries = data["countries"]
    assert len(countries) >= 150
    assert data.get("precision") == 1
    # a spread of large countries across every inhabited continent must be present
    for iso in ("us", "br", "gb", "de", "fr", "ru", "cn", "in", "jp", "za", "ng", "au", "eg"):
        assert iso in countries, f"{iso} missing from the choropleth asset"
        assert countries[iso]["rings"] and len(countries[iso]["rings"][0]) >= 4
