"""
Tests for the database overview API (/api/database/stats).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Verifies the Database management tab gets HONEST figures: real row counts that
move when rows are added, and that only present tables are reported.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from src.api.main import app
from src.database.models import Source
from src.database.session import init_db, session_scope


def setup_module(_module):
    init_db()


def test_stats_shape_and_backend():
    with TestClient(app) as client:
        r = client.get("/api/database/stats")
    assert r.status_code == 200
    body = r.json()
    assert "backend" in body
    assert isinstance(body["counts"], dict)
    # Core tables always present after init_db().
    assert "articles" in body["counts"]
    assert "sources" in body["counts"]
    # table_count reflects a real introspection, not a guess.
    assert body["table_count"] >= len(body["counts"])


def test_source_count_increments_with_real_rows():
    # Unique domain so the test is idempotent against the persistent dev DB
    # (domain is UNIQUE); cleaned up afterwards to leave no trace.
    domain = f"stat-probe-{uuid.uuid4().hex}.test"
    with TestClient(app) as client:
        before = client.get("/api/database/stats").json()["counts"]["sources"]
        with session_scope() as s:
            s.add(Source(name="Stat Probe", domain=domain))
        after = client.get("/api/database/stats").json()["counts"]["sources"]
        assert after == before + 1
        with session_scope() as s:
            s.query(Source).filter_by(domain=domain).delete()
