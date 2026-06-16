"""
Resume a paused download from the task-manager jobs view (Item 2, Groups C/M).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A paused/failed download cannot be "cancelled" again (it is not queued and has
no live stop event), so the task manager offers RESUME instead. Resume re-enters
the owner's queue / starts a slot via start() — never a new shadow path. Tests
cover the manager method (both kinds) + the /api/jobs/{id}/resume route, with
injected fake HTTP (network-free).
"""

from __future__ import annotations

import threading
import time

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


def _wait_until(predicate, tries=200, delay=0.02):
    for _ in range(tries):
        if predicate():
            return True
        time.sleep(delay)
    return False


# --------------------------- the action set --------------------------------- #


def test_dl_actions_offers_resume_for_paused_and_failed():
    from src.api.jobs import _dl_actions

    assert _dl_actions("running") == ["pause", "cancel"]
    assert _dl_actions("queued") == ["reorder", "cancel"]
    # Paused/failed offer RESUME, never a cancel that would 404 on the owner.
    assert _dl_actions("paused") == ["resume"]
    assert _dl_actions("failed") == ["resume"]
    assert _dl_actions("done") == []


# --------------------------- dump manager ----------------------------------- #


def test_dump_resume_reenters_the_queue(tmp_path):
    from src.wiki.dumps import DumpDownloadManager

    gate = threading.Event()
    mgr = DumpDownloadManager(
        base_dir=tmp_path, http_get=lambda u, h: _SlowResp(gate), max_concurrent=1
    )
    try:
        mgr.start("en")  # claims the one slot, downloads
        assert _wait_until(lambda: mgr.list() and mgr.list()[0]["status"] == "downloading")
        mgr.start("fr")  # queues (capacity 1)
        fr_key = next(e["key"] for e in mgr.list() if e["wiki"] == "fr")
        assert mgr.pause(fr_key) is True  # queued -> paused, leaves the order
        assert fr_key not in mgr.queue_order()
        # Resume re-enters the queue (en still holds the slot) via start().
        out = mgr.resume(fr_key)
        assert out is not None
        assert _wait_until(lambda: fr_key in mgr.queue_order())
        assert mgr.resume("no-such-key") is None  # unknown -> None, never a crash
    finally:
        gate.set()


# --------------------------- OSM manager + route ---------------------------- #


def test_jobs_resume_route_resumes_paused_osm(tmp_path, monkeypatch):
    from src.api.main import app
    from src.geo import osm_downloads as mod
    from src.geo.osm_downloads import OsmDownloadManager

    gate = threading.Event()
    mgr = OsmDownloadManager(
        base_dir=tmp_path, http_get=lambda url, headers: _SlowResp(gate), max_concurrent=1
    )
    monkeypatch.setattr(mod, "_manager", mgr, raising=False)
    monkeypatch.setattr(mod, "get_manager", lambda: mgr)
    with TestClient(app) as client:
        try:
            mgr.start("europe")  # downloads
            assert _wait_until(lambda: mgr.list() and mgr.list()[0]["status"] == "downloading")
            mgr.start("asia")  # queues
            assert mgr.pause("asia") is True  # queued -> paused
            # The jobs view now offers RESUME for the paused job (not cancel).
            jobs = {j["id"]: j for j in client.get("/api/jobs").json()["jobs"]}
            assert jobs["osm:asia"]["state"] == "paused"
            assert jobs["osm:asia"]["actions"] == ["resume"]
            # Resume through the generic jobs route re-enters the queue.
            r = client.post("/api/jobs/osm:asia/resume")
            assert r.status_code == 200 and r.json()["resumed"] == "osm:asia"
            assert _wait_until(lambda: "asia" in mgr.queue_order())
            # Unknown / unresumable jobs are clean 404s.
            assert client.post("/api/jobs/osm:atlantis/resume").status_code == 404
            assert client.post("/api/jobs/collect:current/resume").status_code == 404
        finally:
            gate.set()
