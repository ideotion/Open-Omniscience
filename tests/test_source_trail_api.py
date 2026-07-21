"""API wiring for the discovery-trail / citation-tally endpoints (L5).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Confirms /api/sources/{id}/provenance and /api/sources/{id}/citation-tally are
wired to src.discovery.source_trail and 404 honestly on an unknown id. The
aggregation logic itself is covered exhaustively in test_source_trail.py.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _mem_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from src.database.models import Base

    eng = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, future=True)()


def test_provenance_and_tally_endpoints_wired():
    from src.api.main import app
    from src.database.models import Source
    from src.database.session import get_db

    s = _mem_session()
    src = Source(name="Reporter", domain="reporter.example", tags="via:catalog")
    s.add(src)
    s.commit()

    def _db():
        try:
            yield s
        finally:
            pass

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as c:
            r = c.get(f"/api/sources/{src.id}/provenance")
            assert r.status_code == 200
            body = r.json()
            assert body["found"] is True
            assert body["channel"] == "catalog"
            assert body["qualification_status"] == "unqualified"

            t = c.get(f"/api/sources/{src.id}/citation-tally")
            assert t.status_code == 200
            tb = t.json()
            assert tb["found"] is True
            assert "caveat" in tb
            assert set(tb["counts"]) == {
                "qualified", "disqualified", "pending", "never_registered",
                "filtered_commerce", "filtered_social", "filtered_infrastructure",
            }

            assert c.get("/api/sources/999999/provenance").status_code == 404
            assert c.get("/api/sources/999999/citation-tally").status_code == 404
    finally:
        app.dependency_overrides.clear()
