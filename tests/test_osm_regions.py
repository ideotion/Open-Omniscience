"""
The bundled, dated OSM region catalog (Group M — offline mapping). Mirrors the
Wikipedia dump-size discipline: dated estimates, a freshness test, zero network.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import re
from datetime import date

from fastapi.testclient import TestClient

from src.geo.osm_regions import (
    OSM_SIZES_AS_OF,
    estimate_bytes,
    get_region,
    is_valid_code,
    list_regions,
)


def test_osm_sizes_freshness():
    """Fails once OSM_SIZES_AS_OF is older than the window — forcing a re-review
    against https://download.geofabrik.de or a knowing date bump."""
    m = re.fullmatch(r"(\d{4})-(\d{2})", OSM_SIZES_AS_OF)
    assert m, f"OSM_SIZES_AS_OF must be 'YYYY-MM', got {OSM_SIZES_AS_OF!r}"
    y, mo = int(m.group(1)), int(m.group(2))
    today = date.today()
    age = (today.year - y) * 12 + (today.month - mo)
    assert age >= 0, f"OSM_SIZES_AS_OF {OSM_SIZES_AS_OF} is in the future"
    assert age <= 12, (
        f"OSM region size estimates are {age} months old (OSM_SIZES_AS_OF="
        f"{OSM_SIZES_AS_OF}). Re-verify src/geo/osm_regions.py and bump the date."
    )


def test_catalog_is_sane_and_planet_is_largest():
    regions = list_regions()
    assert len(regions) >= 5
    codes = [r.code for r in regions]
    assert len(codes) == len(set(codes))  # unique region codes
    for r in regions:
        assert is_valid_code(r.code), f"{r.code} must be a path-safe code"
        assert r.approx_bytes > 0 and r.name and r.continent
    # Largest-first ordering; the planet file dwarfs the continents.
    assert regions[0].code == "planet"
    assert [r.approx_bytes for r in regions] == sorted(
        (r.approx_bytes for r in regions), reverse=True
    )
    assert get_region("europe") is not None and estimate_bytes("europe") > 0


def test_code_validation_blocks_traversal():
    # Case-insensitive (normalizes like get_region), but path-unsafe shapes are out.
    assert is_valid_code("europe") and is_valid_code("north-america")
    assert is_valid_code("EUROPE")  # normalizes to a valid lowercase code
    for bad in ("../etc/passwd", "..", "", "a/b", "a\\b", "a--b", "-x", "x-", "a.b", "a b"):
        assert not is_valid_code(bad), f"{bad!r} must be rejected"
    assert estimate_bytes("nope") is None


def test_geo_regions_endpoint():
    from src.api.main import app

    with TestClient(app) as client:
        r = client.get("/api/geo/regions")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["size_estimate_as_of"] == OSM_SIZES_AS_OF and data["caveat"]
    regions = data["regions"]
    assert regions and regions[0]["code"] == "planet"
    assert all("size_estimate_bytes" in x for x in regions)
    # Descriptive catalog only — no score/ranking field.
    assert all("score" not in x for x in regions)
