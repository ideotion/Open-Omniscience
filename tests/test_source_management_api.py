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


def test_list_and_get_source_article_count_avoid_full_article_load(tmp_path):
    """P1 fix: list_sources/get_source's article_count must read the maintained
    Source.article_count counter (source_io.py's already-shipped pattern, migration
    d2f8a9df7168) rather than ``len(s.articles)``, which used to force SQLAlchemy to
    fully load -- and, on the real SQLCipher-encrypted store, decrypt -- every one of
    a source's Article rows (including the Text/LargeBinary content columns) just to
    produce an integer count.

    Two sources: one with a fresh reconciled counter (article_count set + reconciled
    within 24h -- must trigger ZERO queries against the articles table at all) and one
    with a NULL counter (never reconciled -- must fall back to exactly ONE batched
    ``COUNT(*) ... GROUP BY source_id`` query, never one query per source and never a
    query that selects the content columns).
    """
    import hashlib
    from datetime import UTC, datetime

    from sqlalchemy import event

    from src.database.models import Article, Source

    engine = create_engine(
        f"sqlite:///{tmp_path / 'article_count.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)

    with Sess() as db:
        reconciled = Source(
            name="Reconciled",
            domain="reconciled.example",
            article_count=2,
            counter_reconciled_at=datetime.now(UTC),
        )
        unreconciled = Source(name="Unreconciled", domain="unreconciled.example", article_count=None)
        db.add_all([reconciled, unreconciled])
        db.commit()
        db.refresh(reconciled)
        db.refresh(unreconciled)
        for src, n in ((reconciled, 2), (unreconciled, 3)):
            for i in range(n):
                digest = hashlib.sha256(f"{src.domain}-{i}".encode()).hexdigest()
                db.add(
                    Article(
                        url=f"https://{src.domain}/a{i}",
                        canonical_url=f"https://{src.domain}/a{i}",
                        source_id=src.id,
                        content="x" * 5000,  # stand-in for a real (decrypted) article body
                        hash=digest,
                    )
                )
        db.commit()
        reconciled_id, unreconciled_id = reconciled.id, unreconciled.id

    def _db():
        db = Sess()
        try:
            yield db
        finally:
            db.close()

    statements: list[str] = []

    def _capture(conn, cursor, statement, params, ctx, many):  # noqa: ANN001
        if "from articles" in statement.lower():
            statements.append(statement)

    app.dependency_overrides[get_db] = _db
    event.listen(engine, "before_cursor_execute", _capture)
    try:
        with TestClient(app) as c:
            statements.clear()
            r = c.get("/api/sources/?limit=1000")
            assert r.status_code == 200, r.text
            by_domain = {s["domain"]: s for s in r.json()}
            assert by_domain["reconciled.example"]["article_count"] == 2
            assert by_domain["reconciled.example"]["count_basis"] == "exact"
            assert by_domain["unreconciled.example"]["article_count"] == 3
            assert by_domain["unreconciled.example"]["count_basis"] == "live"

            # Exactly one batched fallback query for the whole page (only the
            # NULL-counter source needs it) -- never one query per source, and it
            # must be a plain COUNT, never a row/content SELECT.
            assert len(statements) == 1, f"expected exactly one batched query, got: {statements}"
            assert "count(" in statements[0].lower()
            assert "content" not in statements[0].lower()

            statements.clear()
            r2 = c.get(f"/api/sources/{reconciled_id}")
            assert r2.status_code == 200, r2.text
            assert r2.json()["article_count"] == 2
            assert r2.json()["count_basis"] == "exact"
            assert statements == [], f"a fresh reconciled counter must not query articles: {statements}"

            statements.clear()
            r3 = c.get(f"/api/sources/{unreconciled_id}")
            assert r3.status_code == 200, r3.text
            assert r3.json()["article_count"] == 3
            assert r3.json()["count_basis"] == "live"
            assert len(statements) == 1, f"expected exactly one live-fallback query, got: {statements}"
            assert "count(" in statements[0].lower()
            assert "content" not in statements[0].lower()
    finally:
        event.remove(engine, "before_cursor_execute", _capture)
        app.dependency_overrides.clear()
