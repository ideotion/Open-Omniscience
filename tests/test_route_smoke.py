"""
Route smoke test: no exposed endpoint should 5xx on a trivial request.

Boots the real app (all routers) against an isolated DB and probes every
parameterless GET route, asserting none returns a 5xx. This is a cheap, durable
guard against import-time breakage and obvious endpoint regressions across the
whole surface (including the legacy routers not individually unit-tested).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.database.fts import ensure_fts
from src.database.models import Base
from src.database.session import get_db


@pytest.fixture()
def client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'smoke.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    ensure_fts(engine)
    Sess = sessionmaker(bind=engine, future=True)

    def _db():
        db = Sess()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _parameterless_get_paths() -> list[str]:
    paths = []
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", "")
        if "GET" in methods and "{" not in path and path.startswith("/api"):
            paths.append(path)
    return sorted(set(paths))


def test_no_get_endpoint_returns_5xx(client):
    failures = []
    for path in _parameterless_get_paths():
        resp = client.get(path)
        if resp.status_code >= 500:
            failures.append((path, resp.status_code))
    assert not failures, f"endpoints returned 5xx: {failures}"


def test_health_and_docs_available(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/openapi.json").status_code == 200
