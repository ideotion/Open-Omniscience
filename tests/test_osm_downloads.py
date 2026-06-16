"""
Tests for the offline OSM region download manager (Group M, no network).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Mirrors the Wikipedia dump downloader's guarantees: resumable downloads, a
persisted reorderable queue, parallel up to capacity, and a kill-switch-guarded
fetch path. Everything here is network-free (injected fake HTTP).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.geo.osm_downloads import (
    GEOFABRIK_BASE,
    PLANET_URL,
    OsmDownloadManager,
    osm_download_url,
    osm_filename,
)


# ------------------------------- URL builder -------------------------------- #


def test_osm_download_url_geofabrik_and_planet():
    assert osm_download_url("europe") == f"{GEOFABRIK_BASE}/europe-latest.osm.pbf"
    assert osm_download_url("north-america") == f"{GEOFABRIK_BASE}/north-america-latest.osm.pbf"
    # The whole-planet file is NOT a Geofabrik product — it lives on the planet mirror.
    assert osm_download_url("planet") == PLANET_URL
    assert osm_download_url("EUROPE") == f"{GEOFABRIK_BASE}/europe-latest.osm.pbf"  # normalises
    assert osm_filename("europe") == "europe-latest.osm.pbf"


def test_osm_download_url_rejects_path_traversal():
    for bad in ("../etc/passwd", "..", "", "a/b", "a\\b", "europe/france", "a.b", "a b", "-x"):
        with pytest.raises(ValueError):
            osm_download_url(bad)


# ----------------------------- download loop -------------------------------- #


class FakeResp:
    def __init__(self, *, status_code=200, length=0, chunks=(), headers=None):
        self.status_code = status_code
        self._chunks = list(chunks)
        self.headers = headers or {"Content-Length": str(length)}

    def raise_for_status(self):
        return None

    def iter_content(self, _chunk):
        yield from self._chunks


def test_full_download(tmp_path):
    payload = [b"abc", b"defgh", b"ij"]  # 10 bytes

    def http_get(url, headers):
        assert url == f"{GEOFABRIK_BASE}/europe-latest.osm.pbf"
        assert "Range" not in headers  # first run: no resume
        return FakeResp(status_code=200, length=10, chunks=payload)

    m = OsmDownloadManager(base_dir=tmp_path, http_get=http_get)
    entry = m._entry_for("europe")
    res = m._download(entry)
    assert res.status == "done"
    assert res.downloaded_bytes == 10 and res.total_bytes == 10
    assert Path(res.dest).read_bytes() == b"abcdefghij"
    # the entry carries the catalog display name + a zero-network size estimate
    shown = next(e for e in m.list() if e["key"] == "europe")
    assert shown["name"] == "Europe"
    assert shown["size_estimate_bytes"] and shown["size_estimate_bytes"] > 0
    assert shown["percent"] == 100.0


def test_resume_appends(tmp_path):
    m = OsmDownloadManager(base_dir=tmp_path, http_get=None)
    entry = m._entry_for("africa")
    Path(entry.dest).write_bytes(b"HEAD")  # 4 bytes already on disk

    def http_get(url, headers):
        assert headers.get("Range") == "bytes=4-"  # resumes from offset
        return FakeResp(status_code=206, length=3, chunks=[b"TAI", b"L"])

    m._http_get = http_get
    res = m._download(entry)
    assert res.status == "done"
    assert Path(res.dest).read_bytes() == b"HEADTAIL"
    assert res.total_bytes == 4 + 3


def test_pause_via_stop_event(tmp_path):
    def http_get(url, headers):
        return FakeResp(status_code=200, length=100, chunks=[b"x" * 10 for _ in range(10)])

    m = OsmDownloadManager(base_dir=tmp_path, http_get=http_get)
    entry = m._entry_for("asia")
    stop = threading.Event()
    stop.set()  # already requested -> stop immediately
    res = m._download(entry, stop_event=stop)
    assert res.status == "paused"


def test_probe_and_delete(tmp_path):
    def http_head(url):
        assert url == f"{GEOFABRIK_BASE}/south-america-latest.osm.pbf"
        return FakeResp(headers={"Content-Length": "999000"})

    m = OsmDownloadManager(base_dir=tmp_path, http_head=http_head)
    assert m.probe_size("south-america") == 999000
    entry = m._entry_for("south-america")
    Path(entry.dest).write_bytes(b"data")
    assert m.delete(entry.key) is True
    assert not Path(entry.dest).exists()
    assert m.list() == []


# ------------------------------- parallelism -------------------------------- #


class _SlowResp:
    """A response whose body only advances when the gate is released, so several
    downloads can be observed 'downloading' at once."""

    status_code = 200
    headers = {"Content-Length": "30"}

    def __init__(self, gate: threading.Event):
        self._gate = gate

    def raise_for_status(self):
        pass

    def iter_content(self, _chunk):
        for _ in range(3):
            self._gate.wait(5)
            yield b"0123456789"


def _wait_until(predicate, tries=200, delay=0.02):
    for _ in range(tries):
        if predicate():
            return True
        time.sleep(delay)
    return False


def _downloading(mgr) -> int:
    return sum(1 for e in mgr.list() if e["status"] == "downloading")


def test_downloads_run_in_parallel_up_to_capacity(tmp_path):
    gate = threading.Event()
    mgr = OsmDownloadManager(
        base_dir=tmp_path, http_get=lambda u, h: _SlowResp(gate), max_concurrent=3
    )
    mgr.start("europe")
    mgr.start("asia")
    mgr.start("africa")
    try:
        assert _wait_until(lambda: _downloading(mgr) == 3), "all three should run at once"
        assert mgr.queue_order() == []  # nothing queued -- true parallelism
    finally:
        gate.set()


def test_excess_over_capacity_queues_and_stays_reorderable(tmp_path):
    gate = threading.Event()
    mgr = OsmDownloadManager(
        base_dir=tmp_path, http_get=lambda u, h: _SlowResp(gate), max_concurrent=2
    )
    for code in ("europe", "asia", "africa", "south-america"):
        mgr.start(code)
    try:
        assert _wait_until(lambda: _downloading(mgr) == 2), "capacity = 2 download at once"
        q = mgr.queue_order()
        assert len(q) == 2, "the excess two queue (prioritisation preserved)"
        reversed_q = [q[1], q[0]]
        assert mgr.reorder(reversed_q) == reversed_q
        assert mgr.queue_order() == reversed_q
    finally:
        gate.set()


def test_stale_downloading_status_is_reset_on_reload(tmp_path):
    gate = threading.Event()
    mgr = OsmDownloadManager(
        base_dir=tmp_path, http_get=lambda u, h: _SlowResp(gate), max_concurrent=1
    )
    mgr.start("europe")
    try:
        assert _wait_until(lambda: _downloading(mgr) == 1)
    finally:
        gate.set()
    worker = mgr._threads.get("europe")
    if worker is not None:
        worker.join(timeout=5)
    # Simulate a restart from a persisted mid-download state.
    mgr._entries["europe"].status = "downloading"
    mgr._save()
    reloaded = OsmDownloadManager(base_dir=tmp_path, max_concurrent=1)
    assert reloaded._entries["europe"].status == "paused"
    assert reloaded._downloading_now() == 0  # the slot is free again


def test_queue_order_survives_a_reload(tmp_path):
    gate = threading.Event()
    mgr = OsmDownloadManager(
        base_dir=tmp_path, http_get=lambda u, h: _SlowResp(gate), max_concurrent=1
    )
    for code in ("europe", "asia", "africa"):
        mgr.start(code)
    try:
        assert _wait_until(lambda: _downloading(mgr) == 1)
        assert mgr.queue_order() == ["asia", "africa"]
    finally:
        gate.set()
    reloaded = OsmDownloadManager(base_dir=tmp_path, max_concurrent=1)
    # The two queued codes persist their order (the running one demoted to paused).
    assert reloaded._order[:2] == ["asia", "africa"]


# --------------------------- guarded transport ------------------------------ #


def test_default_get_passes_url_as_isolation_token(monkeypatch):
    """Each region's URL is its isolation token, so parallel downloads of different
    regions ride different Tor circuits — and the fetch goes through the guarded
    factory (kill switch / proxy), never a raw socket."""
    from src.safety import fetcher as fetcher_mod

    seen = {}

    class _FakeSession:
        def get(self, url, **kw):
            seen["get_url"] = url
            seen["stream"] = kw.get("stream")
            return _SlowResp(threading.Event())

        def head(self, url, **kw):
            return _SlowResp(threading.Event())

    def _fake_guarded(*, user_agent=None, isolation_token=None):
        seen["token"] = isolation_token
        return _FakeSession()

    monkeypatch.setattr(fetcher_mod, "guarded_session", _fake_guarded)
    from src.geo.osm_downloads import _default_get

    _default_get(f"{GEOFABRIK_BASE}/europe-latest.osm.pbf", {})
    assert seen["token"] == f"{GEOFABRIK_BASE}/europe-latest.osm.pbf"
    assert seen["stream"] is True


# -------------------------------- the API ----------------------------------- #


@pytest.fixture()
def geo_client(tmp_path, monkeypatch):
    """A TestClient whose OSM manager is a network-free fake (injected HTTP)."""
    from src.api.main import app
    from src.geo import osm_downloads as mod

    mgr = OsmDownloadManager(
        base_dir=tmp_path, http_get=lambda u, h: FakeResp(length=4, chunks=[b"data"])
    )
    monkeypatch.setattr(mod, "get_manager", lambda: mgr)
    return TestClient(app), mgr


def test_api_downloads_list_empty(geo_client):
    client, _ = geo_client
    r = client.get("/api/geo/downloads")
    assert r.status_code == 200
    assert r.json() == {"downloads": []}


def test_api_start_unknown_region_is_404(geo_client):
    client, mgr = geo_client
    r = client.post("/api/geo/downloads/start", json={"code": "atlantis"})
    assert r.status_code == 404
    # nothing was queued/created for an unknown region
    assert mgr.list() == []


def test_api_start_known_region_routes_to_manager(geo_client):
    client, mgr = geo_client
    r = client.post("/api/geo/downloads/start", json={"code": "europe"})
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == "europe" and body["name"] == "Europe"
    assert body["status"] in ("downloading", "queued", "done")
    # let the (fake, instant) worker settle, then it must be listed
    worker = mgr._threads.get("europe")
    if worker is not None:
        worker.join(timeout=5)
    assert any(e["key"] == "europe" for e in mgr.list())


def test_api_pause_resume_delete_and_reorder(geo_client):
    client, mgr = geo_client
    # seed two queued entries directly (no threads) to exercise the queue endpoints
    mgr._entry_for("europe").status = "queued"
    mgr._entry_for("asia").status = "queued"
    mgr._order = ["europe", "asia"]
    mgr._save()

    r = client.post("/api/geo/downloads/reorder", json={"keys": ["asia", "europe"]})
    assert r.status_code == 200 and r.json()["queue_order"] == ["asia", "europe"]

    r = client.post("/api/geo/downloads/pause", params={"key": "asia"})
    assert r.status_code == 200 and r.json()["paused"] is True

    r = client.delete("/api/geo/downloads", params={"key": "asia"})
    assert r.status_code == 200 and r.json()["deleted"] is True

    r = client.post("/api/geo/downloads/resume", params={"key": "atlantis"})
    assert r.status_code == 404
