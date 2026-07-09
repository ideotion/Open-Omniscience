"""The heavy sync handlers are now background jobs (field test 2026-07-08, Item 8 P1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

governments/load-standard, enrich-source-types and keyword-tags/backfill used to run their
whole multi-minute body synchronously in the request handler (the FastAPI single-worker
freeze). They now START a background job and return immediately; /api/jobs surfaces the
writer job (arbitration) and routes cancel. The workers are faked here so no network/DB is
touched — the point is the JOB WIRING, not the underlying fetch.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.ingest import activate_kill_switch, clear_kill_switch


def _jobs():
    from src.api import diagnostics, governments, insights

    return governments._GOV_JOB, diagnostics._ENRICH_JOB, insights._TAGS_BACKFILL_JOB


@pytest.fixture(autouse=True)
def _idle_jobs():
    """Ensure the singleton jobs start + end each test idle (never a lingering worker)."""
    for j in _jobs():
        j.cancel()
        if j._thread is not None:
            j._thread.join(2)
    yield
    for j in _jobs():
        j.cancel()
        if j._thread is not None:
            j._thread.join(2)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    clear_kill_switch()


def test_load_standard_starts_a_background_job(client, monkeypatch):
    from src.api import governments

    monkeypatch.setattr(governments._GOV_JOB, "_worker", lambda ctx, **kw: {"faked": True, **kw})
    clear_kill_switch()  # online
    r = client.post("/api/governments/load-standard", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["started"] is True and body["job"]["kind"] == "governments"

    governments._GOV_JOB._thread.join(3)
    st = client.get("/api/governments/load-standard/status").json()
    assert st["state"] == "done" and st["result"]["faked"] is True


def test_load_standard_still_refuses_under_airplane(client):
    activate_kill_switch()
    try:
        r = client.post("/api/governments/load-standard", json={})
        assert r.status_code == 409 and "airplane" in r.json()["detail"].lower()
    finally:
        clear_kill_switch()


def test_enrich_source_types_refused_under_airplane(client):
    activate_kill_switch()
    try:
        r = client.post("/api/diagnostics/enrich-source-types")
        assert r.status_code == 409 and "airplane" in r.json()["detail"].lower()
    finally:
        clear_kill_switch()


def test_enrich_source_types_starts_a_job(client, monkeypatch):
    from src.api import diagnostics

    clear_kill_switch()
    monkeypatch.setattr(
        diagnostics._ENRICH_JOB, "_worker", lambda ctx, **kw: {"scanned": 0, "sources_typed": 0}
    )
    r = client.post("/api/diagnostics/enrich-source-types")
    assert r.status_code == 200
    body = r.json()
    assert body["started"] is True and body["mode"] == "wikidata"
    diagnostics._ENRICH_JOB._thread.join(3)
    assert client.get("/api/diagnostics/enrich-source-types/status").json()["state"] == "done"


def test_keyword_tags_backfill_starts_a_job(client, monkeypatch):
    from src.api import insights

    monkeypatch.setattr(
        insights._TAGS_BACKFILL_JOB, "_worker", lambda ctx, **kw: {"tagged_keywords": 0, "tags_added": 0}
    )
    r = client.post("/api/insights/keyword-tags/backfill")
    assert r.status_code == 200 and r.json()["started"] is True
    insights._TAGS_BACKFILL_JOB._thread.join(3)
    assert client.get("/api/insights/keyword-tags/backfill/status").json()["state"] == "done"


def test_jobs_surfaces_a_running_writer_and_cancel_routes(client, monkeypatch):
    from src.api import governments

    started = threading.Event()

    def blocking(ctx, **kw):
        ctx.set_progress(done=0, total=3, detail="working")
        started.set()
        while not ctx.stopping:  # cooperative — cancel makes this return
            time.sleep(0.005)
        return {"stopped": True}

    monkeypatch.setattr(governments._GOV_JOB, "_worker", blocking)
    clear_kill_switch()
    client.post("/api/governments/load-standard", json={})
    assert started.wait(2)

    j = client.get("/api/jobs").json()
    gov = [x for x in j["jobs"] if x["kind"] == "governments"]
    assert gov and gov[0]["state"] == "running", "a running background writer must be visible"
    assert j["db_writers_busy"] is True, "a DB-writer job must join the arbitration set"
    assert any("governments" in b for b in j["busy_with"])

    c = client.post("/api/jobs/governments/cancel").json()
    assert c["cancelled"] == "governments"
    governments._GOV_JOB._thread.join(3)
    assert governments._GOV_JOB.status()["state"] == "cancelled"
