"""The OpenStreetMap lane's remaining exception texts: the API's refusal details and the region download manager's stored
error and log lines. A route's detail echoes a value the caller typed (a country code), the download manager stores the
engine's own words in a state file the page shows, and both can hold a passphrase this process holds: they are written
through the shared scrub, with a UnicodeError by class alone.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.osm_lane import router
from src.geo.osm_downloads import OsmDownloadManager

HELD = "held-by-the-process-for-an-osm-text-4417"


def _unicode_error() -> UnicodeEncodeError:
    return UnicodeEncodeError("ascii", "pässword-0123456789", 1, 2, "ordinal not in range(128)")


def _by_class_alone(text: str) -> None:
    assert "UnicodeEncodeError" in text, text
    for leaked in ("ä", "xe4", "ordinal", "position", "range(128)"):
        assert leaked not in text, (leaked, text)


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


# (the route, the dotted name of what it calls, the exception type that call raises for a refusal)
_ROUTES = [
    ("get", "/api/osm/countries/ZZ/completeness", "src.osm.ingest.country_codes", ValueError, None),
    ("post", "/api/osm/countries/ZZ/admin1", "src.osm.ingest.country_codes", ValueError, None),
    ("post", "/api/osm/countries/ZZ/admin1", "src.osm.completeness.start_count", "Admin1Error", None),
    ("get", "/api/osm/view", "src.osm.view.view", "ViewError", {"w": 0, "s": 0, "e": 1, "n": 1}),
    ("get", "/api/osm/objects/node/1", "src.osm.places.object_card", ValueError, None),
    ("put", "/api/osm/countries", "src.osm.picker.save_selection", "PickerError", None),
]


def _exception_type(spec):
    if not isinstance(spec, str):
        return spec
    module = {"Admin1Error": "src.osm.completeness", "ViewError": "src.osm.view", "PickerError": "src.osm.picker"}[spec]
    return getattr(__import__(module, fromlist=[spec]), spec)


@pytest.mark.parametrize("verb,path,target,exc_type,params", _ROUTES)
def test_a_routes_refusal_detail_takes_out_a_held_passphrase_and_writes_a_unicode_error_by_class(
    client, monkeypatch, verb, path, target, exc_type, params
):
    # MUTATION TARGET: any `detail=` back to `str(exc)` in src/api/osm_lane.py.
    monkeypatch.setenv("OO_DB_PASSPHRASE", HELD)
    kind = _exception_type(exc_type)
    module, attr = target.rsplit(".", 1)
    mod = __import__(module, fromlist=[attr])

    def _call(**kw):
        return client.request(verb.upper(), path, params=params if verb == "get" else None,
                              json={"countries": ["fr"]} if verb == "put" else None)

    monkeypatch.setattr(mod, attr, lambda *a, **kw: (_ for _ in ()).throw(kind(f"refused because of {HELD}")))
    got = _call()
    assert got.status_code in (400, 409), got.text
    assert HELD not in got.text and "refused because of" in got.text
    monkeypatch.setattr(mod, attr, lambda *a, **kw: (_ for _ in ()).throw(_unicode_error()))
    if kind is ValueError:  # the routes that catch a bare ValueError also catch a UnicodeError (a subclass of it)
        _by_class_alone(_call().json()["detail"])


def test_a_passphrase_typed_as_the_country_is_not_echoed_by_the_completeness_route(client, monkeypatch):
    monkeypatch.setenv("OO_DB_PASSPHRASE", HELD)
    got = client.get(f"/api/osm/countries/{HELD}/completeness")
    assert got.status_code == 400 and "not an ISO 3166-1" in got.json()["detail"]
    assert HELD not in got.text and HELD.upper() not in got.text


class _Resp:
    status_code = 200
    headers = {"Content-Length": "10"}

    def raise_for_status(self):
        return None

    def iter_content(self, _chunk):
        raise RuntimeError(f"the transfer said {HELD}")
        yield b""  # pragma: no cover


def test_a_download_failure_is_stored_and_logged_without_the_held_passphrase(tmp_path, monkeypatch, caplog):
    # MUTATION TARGET: `entry.error` back to `str(exc)`, or the warning back to `exc_info=True`.
    monkeypatch.setenv("OO_DB_PASSPHRASE", HELD)
    caplog.set_level(logging.WARNING)
    m = OsmDownloadManager(base_dir=tmp_path, http_get=lambda url, headers: _Resp())
    entry = m._entry_for("europe")
    res = m._download(entry)
    assert res.status == "error" and "the transfer said" in res.error and HELD not in res.error
    assert HELD not in m.state_path.read_text("utf-8")
    assert "OSM region download failed for europe" in caplog.text and HELD not in caplog.text


def test_a_download_failure_that_is_a_unicode_error_is_stored_by_class_alone(tmp_path, monkeypatch):
    def _http_get(url, headers):
        raise _unicode_error()

    m = OsmDownloadManager(base_dir=tmp_path, http_get=_http_get)
    res = m._download(m._entry_for("europe"))
    assert res.status == "error"
    _by_class_alone(res.error)
    _by_class_alone(json.loads(m.state_path.read_text("utf-8"))["entries"]["europe"]["error"])


def test_an_unreadable_state_file_is_logged_without_the_held_passphrase(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("OO_DB_PASSPHRASE", HELD)
    caplog.set_level(logging.WARNING)
    probe = OsmDownloadManager(base_dir=tmp_path, http_get=None)
    probe.state_path.write_text("{}", "utf-8")
    import src.geo.osm_downloads as downloads

    monkeypatch.setattr(downloads.json, "loads", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError(f"state said {HELD}")))
    OsmDownloadManager(base_dir=tmp_path, http_get=None)
    assert "state unreadable" in caplog.text and "RuntimeError" in caplog.text and HELD not in caplog.text
