"""
Behavioral tests for the source_management router (Audit P2 DI refactor).

These are now possible because every endpoint takes Depends(get_db) and binds the
SourceManager to the request session (previously they opened their own real-engine
session and ignored the test override). Covers the CRUD + group flow over HTTP and
the refresh endpoint that used to 500 (the get_group AttributeError, Audit P0).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.database.models import Base
from src.database.session import get_db


@pytest.fixture()
def client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 's.db'}", future=True, connect_args={"check_same_thread": False}
    )
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


def test_source_crud_via_router(client):
    # create
    r = client.post(
        "/api/sources/",
        json={
            "name": "Alpha",
            "domain": "alpha.example",
            "rss_url": "https://alpha.example/feed",
            "tags": "news",
        },
    )
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    # the override DB sees it (proves request-scoped session)
    assert any(s["domain"] == "alpha.example" for s in client.get("/api/sources/").json())
    # get
    assert client.get(f"/api/sources/{sid}").json()["name"] == "Alpha"
    # update
    client.put(f"/api/sources/{sid}", json={"priority": 1})
    assert client.get(f"/api/sources/{sid}").json()["priority"] == 1
    # delete
    assert client.delete(f"/api/sources/{sid}").status_code == 200
    assert client.get(f"/api/sources/{sid}").status_code == 404


def test_source_observed_ips_endpoint_shape(client):
    """SOURCE IPs ruling (2026-07-20), ask 2: per-source aggregated observed-IP
    view accessible in source management."""
    r = client.post("/api/sources/", json={"name": "Alpha", "domain": "alpha.example"})
    sid = r.json()["id"]

    out = client.get(f"/api/sources/{sid}/observed-ips").json()
    assert out["source_id"] == sid
    assert out["ips"] == []
    assert out["distinct_ips"] == 0
    assert "caveat" in out and "method" in out

    assert client.get("/api/sources/999999/observed-ips").status_code == 404


def test_missing_required_field_400(client):
    assert client.post("/api/sources/", json={"name": "NoDomain"}).status_code == 400


def test_blank_required_field_400(client):
    # Present-but-empty / whitespace-only values must be rejected, not stored as a
    # junk source (regression guard ported from the abandoned 0.03 debug branch).
    assert (
        client.post("/api/sources/", json={"name": "  ", "domain": "x.example"}).status_code == 400
    )
    assert client.post("/api/sources/", json={"name": "X", "domain": ""}).status_code == 400
    assert client.post("/api/sources/", json={"name": "X", "domain": 123}).status_code == 400


def test_update_source_id_in_body_never_changes_primary_key(client):
    """Mass-assignment fix (audit P2): a PUT body carrying an "id" key must never
    move the row's actual primary key, and must not corrupt a sibling row either."""
    a = client.post("/api/sources/", json={"name": "Alpha", "domain": "alpha2.example"}).json()
    b = client.post("/api/sources/", json={"name": "Beta", "domain": "beta2.example"}).json()

    r = client.put(f"/api/sources/{a['id']}", json={"id": b["id"], "name": "Alpha Renamed"})
    assert r.status_code == 200, r.text
    assert r.json()["id"] == a["id"]  # never moved to b's id

    # both rows still exist, independently, at their original ids
    assert client.get(f"/api/sources/{a['id']}").json()["name"] == "Alpha Renamed"
    assert client.get(f"/api/sources/{b['id']}").json()["name"] == "Beta"


def test_update_source_every_supported_field_still_works(client):
    """Existing legitimate PUT behavior for every currently-supported field must
    keep working exactly as before the allowlist was added."""
    sid = client.post(
        "/api/sources/", json={"name": "Gamma", "domain": "gamma2.example"}
    ).json()["id"]

    body = {
        "name": "Gamma Renamed",
        "domain": "gamma2-renamed.example",
        "rss_url": "https://gamma2-renamed.example/feed",
        "rate_limit_ms": 3000,
        "enabled": False,
        "priority": 3,
        "tags": "renamed,gamma",
    }
    r = client.put(f"/api/sources/{sid}", json=body)
    assert r.status_code == 200, r.text

    got = client.get(f"/api/sources/{sid}").json()
    assert got["name"] == "Gamma Renamed"
    assert got["domain"] == "gamma2-renamed.example"
    assert got["priority"] == 3


def test_update_source_malformed_allowlisted_field_400_not_500(client):
    sid = client.post(
        "/api/sources/", json={"name": "Delta", "domain": "delta2.example"}
    ).json()["id"]

    r = client.put(f"/api/sources/{sid}", json={"rate_limit_ms": "not-a-number"})
    assert r.status_code == 400, r.text

    r = client.put(f"/api/sources/{sid}", json={"enabled": "yes"})
    assert r.status_code == 400, r.text

    # the source is untouched by the rejected update
    assert client.get(f"/api/sources/{sid}").json()["name"] == "Delta"


def test_update_source_unrecognized_field_dropped_not_500(client):
    sid = client.post(
        "/api/sources/", json={"name": "Epsilon", "domain": "epsilon2.example"}
    ).json()["id"]

    r = client.put(
        f"/api/sources/{sid}",
        json={"priority": 1, "not_a_real_column": "whatever"},
    )
    assert r.status_code == 200, r.text

    got = client.get(f"/api/sources/{sid}").json()
    assert got["priority"] == 1


def test_group_flow_and_refresh_endpoint(client):
    # create a tag-based group, then refresh it (this endpoint used to 500 on a
    # nonexistent manager.get_group()).
    g = client.post(
        "/api/sources/groups/tag-based", params={"name": "World", "tag_pattern": "world"}
    )
    assert g.status_code == 200, g.text
    gid = g.json().get("id") or g.json().get("group", {}).get("id")
    r = client.post(f"/api/sources/groups/{gid}/refresh")
    assert r.status_code == 200, r.text


def test_refresh_unknown_group_404(client):
    assert client.post("/api/sources/groups/99999/refresh").status_code == 404
