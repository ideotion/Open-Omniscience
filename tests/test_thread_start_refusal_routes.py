"""A download start whose worker thread cannot start is a 409 with a named detail, never a 500 (R393/R398).

The managers raise ``RuntimeError`` when the worker thread cannot be started; the wiki dump start and the OSM start/resume routes mapped only
``ValueError``, so that error reached the caller as an unhandled 500. These tests stand a manager that raises in for the real one.
"""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

_REASON = "worker thread could not start: can't start new thread"


class _RefusingManager:
    def start(self, *args, **kwargs):
        raise RuntimeError(_REASON)


@pytest.fixture()
def client():
    from src.api.main import app

    return TestClient(app, raise_server_exceptions=False)


def test_wiki_dump_start_refused_thread_is_409(client, monkeypatch):
    from src.wiki import dumps

    monkeypatch.setattr(dumps, "get_manager", lambda: _RefusingManager())
    r = client.post("/api/wiki/dumps/start", json={"wiki": "fr", "kind": "pages-articles-multistream"})
    assert r.status_code == 409
    assert "could not start" in r.json()["detail"]


def test_osm_start_refused_thread_is_409(client, monkeypatch):
    from src.geo import osm_downloads

    monkeypatch.setattr(osm_downloads, "get_manager", lambda: _RefusingManager())
    r = client.post("/api/geo/downloads/start", json={"code": "europe"})
    assert r.status_code == 409
    assert "could not start" in r.json()["detail"]


def test_osm_resume_refused_thread_is_409(client, monkeypatch):
    from src.geo import osm_downloads

    monkeypatch.setattr(osm_downloads, "get_manager", lambda: _RefusingManager())
    r = client.post("/api/geo/downloads/resume", params={"key": "europe"})
    assert r.status_code == 409
    assert "could not start" in r.json()["detail"]


def _refuse_download_workers(monkeypatch):
    """The OS refusing a new thread, only for the download workers (named oo-dump-* / oo-osm-*)."""
    real = threading.Thread.start

    def start(self):
        if self.name.startswith(("oo-dump-", "oo-osm-")):
            raise RuntimeError("can't start new thread")
        return real(self)

    monkeypatch.setattr(threading.Thread, "start", start)


def test_real_osm_manager_thread_refusal_reaches_the_caller_as_409(client, monkeypatch, tmp_path):
    from src.geo import osm_downloads

    mgr = osm_downloads.OsmDownloadManager(base_dir=tmp_path, http_get=lambda u, h: None)
    monkeypatch.setattr(osm_downloads, "get_manager", lambda: mgr)
    _refuse_download_workers(monkeypatch)
    r = client.post("/api/geo/downloads/start", json={"code": "europe"})
    assert r.status_code == 409
    assert "start new thread" in r.json()["detail"]
    assert [e["status"] for e in mgr.list()] == ["error"]


def test_real_dump_manager_thread_refusal_reaches_the_caller_as_409(client, monkeypatch, tmp_path):
    from src.wiki import dumps

    mgr = dumps.DumpDownloadManager(base_dir=tmp_path, http_get=lambda u, h: None)
    monkeypatch.setattr(dumps, "get_manager", lambda: mgr)
    _refuse_download_workers(monkeypatch)
    r = client.post("/api/wiki/dumps/start", json={"wiki": "fr", "kind": "pages-articles-multistream"})
    assert r.status_code == 409
    assert "start new thread" in r.json()["detail"]
    assert "error" in [e["status"] for e in mgr.list()]
