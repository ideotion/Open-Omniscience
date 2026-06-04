"""
Tests for source seeding (Action Plan Phase 6.2) -- immediate out-of-box utility.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.database.models import Base, Source
from src.database.session import get_db
from src.ingest.seed_sources import (
    DEFAULT_SOURCES_PATH,
    load_sources_from_yaml,
    seed_default_sources,
    seed_sources,
)

_YAML = """
sources:
  - name: Example One
    domain: one.example
    rss_url: https://one.example/feed.xml
    tags: a,b
  - name: Example Two
    domain: two.example
  - {}                       # malformed -> skipped
  - name: No Domain          # missing domain -> skipped
"""


def _session():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_loader_skips_malformed(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text(_YAML)
    rows = load_sources_from_yaml(p)
    assert [r["name"] for r in rows] == ["Example One", "Example Two"]


def test_seed_is_idempotent(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text(_YAML)
    rows = load_sources_from_yaml(p)
    s = _session()
    first = seed_sources(s, rows)
    assert first["created"] == 2 and first["skipped"] == 0
    second = seed_sources(s, rows)
    assert second["created"] == 0 and second["skipped"] == 2
    assert s.query(Source).count() == 2
    s.close()


def test_default_yaml_is_valid_and_nonempty():
    # The shipped curated file must parse and contain usable entries.
    rows = load_sources_from_yaml(DEFAULT_SOURCES_PATH)
    assert len(rows) >= 3
    assert all(r.get("name") and r.get("domain") for r in rows)


def test_seed_default_sources_helper():
    s = _session()
    result = seed_default_sources(s)
    assert result["created"] >= 3
    assert s.query(Source).count() == result["created"]
    s.close()


@pytest.fixture()
def client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'seed.db'}", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
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


def test_seed_defaults_endpoint(client):
    r = client.post("/api/sources/seed-defaults")
    assert r.status_code == 200, r.text
    assert r.json()["seeded"]["created"] >= 3
    # they now appear in the source list
    sources = client.get("/api/sources").json()
    assert len(sources) >= 3
    # idempotent
    r2 = client.post("/api/sources/seed-defaults")
    assert r2.json()["seeded"]["created"] == 0
