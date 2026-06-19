"""The bounded region-PREVIEW endpoint (GET /api/geo/regions/{code}/preview) feeds
the in-browser offline-map renderer (THEME-2 .pbf parser). It serves only a BOUNDED
byte prefix of a DOWNLOADED region's local .osm.pbf — never the whole multi-GB file
— LOOPBACK + zero-network (it reads a file already on disk), path-safe (only
catalogued region codes), and 404 when the region is not downloaded.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def geo_client(tmp_path, monkeypatch):
    from src.api.main import app
    from src.geo import osm_downloads as mod
    from src.geo.osm_downloads import OsmDownloadManager

    mgr = OsmDownloadManager(base_dir=tmp_path)
    monkeypatch.setattr(mod, "_manager", mgr, raising=False)
    monkeypatch.setattr(mod, "get_manager", lambda: mgr)
    with TestClient(app) as c:
        yield c, mgr, tmp_path


def _valid_code():
    from src.geo.osm_regions import list_regions

    # a small, real catalogued code (skip 'planet' — the first entry is the whole world)
    for r in list_regions():
        if r.code != "planet":
            return r.code
    return list_regions()[0].code


def test_preview_serves_a_bounded_prefix_of_a_downloaded_region(geo_client):
    c, mgr, tmp_path = geo_client
    from src.geo.osm_downloads import osm_filename

    code = _valid_code()
    payload = bytes(range(256)) * 200  # 51,200 bytes of arbitrary content
    (tmp_path / osm_filename(code)).write_bytes(payload)

    r = c.get(f"/api/geo/regions/{code}/preview", params={"max_bytes": 4096})
    assert r.status_code == 200
    assert r.content == payload[:4096], "must serve exactly the requested prefix"
    assert r.headers["X-OO-Region-Total-Bytes"] == str(len(payload))
    assert r.headers["X-OO-Region-Preview-Bytes"] == "4096"
    assert r.headers["X-OO-Region-Truncated"] == "1", "a prefix of a larger file is truncated"


def test_preview_full_when_file_smaller_than_cap(geo_client):
    c, mgr, tmp_path = geo_client
    from src.geo.osm_downloads import osm_filename

    code = _valid_code()
    payload = b"\x01\x02\x03\x04" * 10  # 40 bytes, well under the cap
    (tmp_path / osm_filename(code)).write_bytes(payload)

    r = c.get(f"/api/geo/regions/{code}/preview", params={"max_bytes": 1048576})
    assert r.status_code == 200
    assert r.content == payload
    assert r.headers["X-OO-Region-Truncated"] == "0"


def test_preview_404_when_not_downloaded(geo_client):
    c, _mgr, _tmp = geo_client
    r = c.get(f"/api/geo/regions/{_valid_code()}/preview")
    assert r.status_code == 404


def test_preview_400_on_malformed_code(geo_client):
    c, _mgr, _tmp = geo_client
    r = c.get("/api/geo/regions/..%2f..%2fetc/preview")
    assert r.status_code in (400, 404)  # path-rejected (400) or route-miss (404); never serves


def test_preview_caps_max_bytes(geo_client):
    c, mgr, tmp_path = geo_client
    from src.geo.osm_downloads import osm_filename

    code = _valid_code()
    (tmp_path / osm_filename(code)).write_bytes(b"x" * 1024)
    # over the hard ceiling -> rejected by the query bound (422), never serves a huge slice
    r = c.get(f"/api/geo/regions/{code}/preview", params={"max_bytes": 999999999})
    assert r.status_code == 422
