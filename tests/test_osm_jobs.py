"""
OSM offline-map downloads surface in the task-manager /api/jobs view (Group M).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Mirrors the wiki-dump aggregation: an OSM region download is a visible job with a
real queue position, cancellable + reorderable through the owning manager. No
shadow state; network-free (injected fake HTTP).
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient


class _SlowResp:
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


@pytest.fixture()
def osm_client(tmp_path, monkeypatch):
    from src.api.main import app
    from src.geo import osm_downloads as mod
    from src.geo.osm_downloads import OsmDownloadManager

    gate = threading.Event()
    # capacity 1 so the second region QUEUES (queue_position + reorder coverage)
    mgr = OsmDownloadManager(
        base_dir=tmp_path, http_get=lambda url, headers: _SlowResp(gate), max_concurrent=1
    )
    monkeypatch.setattr(mod, "_manager", mgr, raising=False)
    monkeypatch.setattr(mod, "get_manager", lambda: mgr)
    with TestClient(app) as c:
        yield c, mgr, gate
    gate.set()


def test_jobs_view_aggregates_osm_downloads(osm_client):
    client, mgr, gate = osm_client
    mgr.start("europe")
    for _ in range(50):
        if mgr.list() and mgr.list()[0]["status"] == "downloading":
            break
        time.sleep(0.02)
    mgr.start("asia")  # queues (capacity 1)

    body = client.get("/api/jobs").json()
    assert body["network_busy"] is True
    # A downloading OSM extract writes a FILE — never the DB — so it must NOT
    # trigger the DB-writer arbitration ask (parallel-across-kinds).
    assert body["db_writers_busy"] is False
    by_id = {j["id"]: j for j in body["jobs"]}
    eu = by_id["osm:europe"]
    assert eu["kind"] == "osm-map" and eu["state"] == "running"
    assert eu["label"] == "Europe"
    asia = by_id["osm:asia"]
    assert asia["state"] == "queued" and asia["queue_position"] == 1
    assert "reorder" in asia["actions"]


def test_osm_reorder_and_cancel_through_the_jobs_routes(osm_client):
    client, mgr, gate = osm_client
    mgr.start("europe")
    for _ in range(50):
        if mgr.list() and mgr.list()[0]["status"] == "downloading":
            break
        time.sleep(0.02)
    mgr.start("asia")
    mgr.start("africa")

    r = client.post("/api/jobs/osm/reorder", json={"keys": ["africa", "asia"]})
    assert r.status_code == 200 and r.json()["queue_order"] == ["africa", "asia"]

    # Cancel (pause) the queued africa via the generic jobs cancel route.
    r = client.post("/api/jobs/osm:africa/cancel")
    assert r.status_code == 200 and "resumable" in r.json()["detail"]
    assert "africa" not in mgr.queue_order()

    # An unknown OSM job is a clean 404.
    r = client.post("/api/jobs/osm:atlantis/cancel")
    assert r.status_code == 404
