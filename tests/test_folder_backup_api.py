"""Folder-backup API endpoints + /api/jobs surfacing (brief §2.A).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A minimal app (just the two routers) so the test never needs the full app's
Prometheus/crypto wiring — the endpoints are what we assert.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.backup.folder_backup as fb
from src.api.backup_v2 import router as backup_router
from src.api.jobs import router as jobs_router


@pytest.fixture()
def client(monkeypatch):
    # Fresh singleton per test (the manager is process-wide) + collect nothing so the
    # job runs with no real wiki/osm/model store on this machine.
    fb._FOLDER_MANAGER = None
    monkeypatch.setattr(fb, "collect_items", lambda **k: [])
    app = FastAPI()
    app.include_router(backup_router)
    app.include_router(jobs_router)
    return TestClient(app)


def test_status_is_idle_initially(client):
    assert client.get("/api/backup/folder/status").json()["state"] == "idle"


def test_plan_rejects_a_bad_destination(client):
    assert client.post("/api/backup/folder/plan", json={"dest": ""}).status_code == 400


def test_plan_reports_preflight(client, tmp_path):
    r = client.post("/api/backup/folder/plan", json={"dest": str(tmp_path), "categories": ["wiki_dumps"]})
    assert r.status_code == 200
    d = r.json()
    assert d["categories"] == ["wiki_dumps"] and d["needed_bytes"] == 0
    assert d["enough_space"] is True and "free_human" in d


def test_start_runs_and_completes(client, tmp_path):
    r = client.post("/api/backup/folder/start", json={"dest": str(tmp_path)})
    assert r.status_code == 200
    th = fb.get_folder_manager()._thread
    if th is not None:
        th.join(5)
    assert client.get("/api/backup/folder/status").json()["state"] == "done"


def test_unknown_action_is_404(client):
    assert client.post("/api/backup/folder/wat").status_code == 404


def test_paused_job_surfaces_in_api_jobs(client):
    mgr = fb.get_folder_manager()
    mgr._state = "paused"
    mgr._dest = "/mnt/drive"
    mgr._mode = "backup"
    mgr._progress = {"bytes_total": 1000, "bytes_copied": 400}
    jobs = client.get("/api/jobs").json()["jobs"]
    fbj = [j for j in jobs if j["kind"] == "folder-backup"]
    assert fbj and fbj[0]["state"] == "paused"
    assert fbj[0]["progress"]["percent"] == 40.0
    assert "resume" in fbj[0]["actions"]


def test_jobs_cancel_pauses_the_folder_backup(client):
    mgr = fb.get_folder_manager()
    mgr._state = "running"
    mgr._dest = "/mnt/drive"
    r = client.post("/api/jobs/folder-backup/cancel")
    assert r.status_code == 200 and "paused" in r.json()["detail"]
