"""The full-history planet's download: sized, consented, shown before it starts (S05-04 S4).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q814 = b makes the lane's history one planet-wide file, larger than any continent. The brief asks
for "the consented, sized download shown before it starts": the exact size is read from the mirror
(one HEAD, behind the one online consent, invariant #14e) and the Download button does not exist
until it has been. A size that could not be read says WHY by name -- the kill switch above all,
because "airplane mode is on" and "the mirror is down" send an operator to opposite places.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.js_source_helper import function_source

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "static"


class _Resp:
    def __init__(self, headers):
        self.headers = headers


def _mgr(tmp_path, head):
    from src.geo.osm_downloads import OsmDownloadManager

    return OsmDownloadManager(base_dir=tmp_path / "osm_regions", http_head=head)


def test_the_history_file_is_a_download_but_not_a_region():
    from src.geo.osm_downloads import HISTORY_URL, osm_download_url
    from src.geo.osm_regions import HISTORY_REGION, get_region, list_regions

    assert "planet-history" not in {r.code for r in list_regions()}, "the region list would offer it as a continent"
    assert get_region("planet-history") is HISTORY_REGION
    assert osm_download_url("planet-history") == HISTORY_URL
    assert HISTORY_URL.startswith("https://planet.openstreetmap.org/pbf/full-history/")


def test_the_host_is_named_in_security_md_and_the_consent_hover():
    doc = (ROOT / "docs" / "SECURITY.md").read_text(encoding="utf-8")
    assert "/pbf/full-history/" in doc and "HISTORY_URL" in doc
    import re

    table = (STATIC / "net-hosts.js").read_text(encoding="utf-8")
    hosts = [h for block in re.findall(r'"hosts":\s*\[([^\]]*)\]', table) for h in re.findall(r'"([^"]+)"', block)]
    assert hosts.count("planet.openstreetmap.org") >= 1, "the consent hover no longer names the history file's host"


def test_the_size_estimate_date_is_registered():
    reg = (ROOT / "configs" / "external_artifacts.yml").read_text(encoding="utf-8")
    assert "const: OSM_HISTORY_SIZE_AS_OF" in reg


def test_a_read_size_comes_with_the_free_space_beside_it(tmp_path):
    seen = []
    r = _mgr(tmp_path, lambda url: (seen.append(url), _Resp({"Content-Length": "123456789"}))[1]).size_reading("planet-history")
    assert seen == [r["url"]] and r["size_bytes"] == 123456789 and r["reason"] is None
    assert isinstance(r["free_bytes"], int) and r["free_bytes"] > 0, "the parent that exists is measured"
    assert r["estimate_bytes"] > 0


def test_a_kill_switch_refusal_is_named_airplane(tmp_path):
    from src.safety.fetcher import NetworkBlocked

    def refuse(url):
        raise NetworkBlocked("kill switch")

    r = _mgr(tmp_path, refuse).size_reading("planet-history")
    assert r["size_bytes"] is None and r["reason"] == "airplane"


@pytest.mark.parametrize(
    ("head", "reason"),
    [
        (lambda url: (_ for _ in ()).throw(OSError("reset")), "unreachable"),
        (lambda url: _Resp({}), "no-content-length"),
        (lambda url: _Resp({"Content-Length": "lots"}), "no-content-length"),
    ],
)
def test_a_size_not_read_is_never_a_zero(tmp_path, head, reason):
    r = _mgr(tmp_path, head).size_reading("planet-history")
    assert r["size_bytes"] is None and r["reason"] == reason


def test_the_size_route(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.geo import router
    from src.geo import osm_downloads as mod

    mgr = _mgr(tmp_path, lambda url: _Resp({"Content-Length": "42"}))
    monkeypatch.setattr(mod, "get_manager", lambda: mgr)
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    assert c.get("/api/geo/downloads/size", params={"code": "planet-history"}).json()["size_bytes"] == 42
    assert c.get("/api/geo/downloads/size", params={"code": "atlantis"}).status_code == 404


def test_the_history_route_says_when_the_lane_could_not_be_read(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.osm_lane import router
    from src.osm import history

    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    monkeypatch.setattr(history, "history_state", lambda: [])
    body = c.get("/api/osm/history").json()
    assert body["cuts"] == [] and body["download"]["code"] == "planet-history"
    assert body["gap"] == history.GAP and body["method"] == history.METHOD

    def locked():
        raise RuntimeError("the store is locked")

    monkeypatch.setattr(history, "history_state", locked)
    assert c.get("/api/osm/history").json()["cuts"] is None, "a locked lane read as 'no country cut yet'"


# --------------------------------------------------------------------------- #
#  The UI                                                                      #
# --------------------------------------------------------------------------- #


def _js() -> str:
    return (STATIC / "app-map.js").read_text(encoding="utf-8")


def test_the_panel_sits_in_settings_openstreetmap_after_the_picker():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    view = html.partition('id="set-offlinemap"')[2]
    assert view.index('id="osm-lane-picker"') < view.index('id="osm-history"') < view.index('id="osm-region-list"')


def test_reading_the_size_passes_the_one_online_consent_first():
    body = function_source(_js(), "osmHistoryReadSize")
    assert body.index("ensureOnline(") < body.index("/api/geo/downloads/size")
    dl = function_source(_js(), "osmHistoryDownload")
    assert dl.index("ensureOnline(") < dl.index("/api/geo/downloads/start")


def test_there_is_no_download_button_until_the_exact_size_is_shown():
    cell = function_source(_js(), "_osmHistDownloadCell")
    before, _sep, after = cell.partition("r.size_bytes == null")
    assert "osmHistoryDownload" not in before, "a Download button before the size check"
    assert "osmHistoryDownload" in after
    assert "The download starts only once its exact size is shown." in cell


def test_every_size_refusal_is_named():
    line = function_source(_js(), "_osmHistSizeLine")
    for text in ("airplane mode is on", "the mirror did not answer", "the mirror did not state it",
                 "Not enough free space here for this file."):
        assert text in line


def test_the_gap_is_visible_by_default_not_behind_a_toggle():
    render = function_source(_js(), "_renderOsmHistory")
    assert 'class="card-caveat">${esc(t(h.gap' in render


def test_the_actions_are_allowlisted():
    on = (STATIC / "oo-on.js").read_text(encoding="utf-8")
    assert '"osmHistoryDownload"' in on and '"osmHistoryReadSize"' in on


def test_every_history_string_ships_in_twelve_languages():
    from src.osm.history import GAP, METHOD

    strings = [GAP, METHOD, "Full history", "Whole planet, full history", "Read the exact size",
               "Exact size on the mirror: {size}. Free space here: {free}.", "Download ({size})",
               "The size could not be read: airplane mode is on.", "history as of {date}",
               "{objects} objects, {versions} versions ({created} created, {deleted} deleted), read in {seconds} s"]
    for path in sorted((STATIC / "locales").glob("*.json")):
        loc = json.loads(path.read_text("utf-8"))
        for s in strings:
            assert s in loc, (path.name, s)
