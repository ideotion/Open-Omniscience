"""
Quarantine exclusion at the /api/articles chokepoint (S3.2, 2026-07-23 field-feedback
workflow).

A quarantined article (Article.quarantined=True) must never surface through the ONE
search/browse surface every other consumer (omnibar, search, export, card-seeded
analysis) ultimately funnels through: src.api.main._query_articles /
_structured_filters / _browse_total_cached. This mirrors the fixture pattern in
tests/test_api_search.py (an isolated temp SQLite DB, get_db overridden onto it, a
real TestClient) rather than reusing that file's fixture directly, so a quarantined
row can be stamped AFTER seeding via the same session factory the override uses.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
import pytest

from src.api.main import app
from src.database.fts import ensure_fts
from src.database.models import Article, Base, Source
from src.database.session import get_db


@pytest.fixture()
def qclient(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'quarantine_api.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _rec):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    ensure_fts(engine)
    TestSession = sessionmaker(bind=engine, future=True)

    ids: dict[str, int] = {}
    with TestSession() as s:
        src = Source(name="Gamma Times", domain="gamma.example", tags="world")
        s.add(src)
        s.flush()
        clean = Article(
            url="https://gamma.example/clean",
            canonical_url="https://gamma.example/clean",
            source_id=src.id,
            title="Real reporting",
            content="a genuine article about renewable energy policy",
            hash="c".ljust(64, "0"),
            language="en",
        )
        dirty = Article(
            url="https://gamma.example/junk",
            canonical_url="https://gamma.example/junk",
            source_id=src.id,
            title="Newsletter preference centre",
            content="renewable energy policy manage your preferences unsubscribe",
            hash="d".ljust(64, "0"),
            language="en",
            quarantined=True,
            quarantine_reason="nav_soup",
            quarantine_criteria_version="nav-soup-v1",
        )
        unset = Article(
            url="https://gamma.example/unset",
            canonical_url="https://gamma.example/unset",
            source_id=src.id,
            title="Older pre-migration row",
            content="renewable energy policy discussion piece from before the column existed",
            hash="e".ljust(64, "0"),
            language="en",
            quarantined=None,
        )
        s.add_all([clean, dirty, unset])
        s.commit()
        ids["clean"] = clean.id
        ids["dirty"] = dirty.id
        ids["unset"] = unset.id

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c, ids
    app.dependency_overrides.clear()


def test_quarantined_article_excluded_from_text_search(qclient):
    client, ids = qclient
    body = client.get("/api/articles", params={"query": "renewable energy policy"}).json()
    returned_ids = {row["id"] for row in body["results"]}
    assert ids["dirty"] not in returned_ids
    # the clean and NULL-quarantined (pre-migration) rows both still match
    assert ids["clean"] in returned_ids
    assert ids["unset"] in returned_ids
    assert body["total"] == 2


def test_quarantined_article_excluded_from_browse_and_total(qclient):
    client, ids = qclient
    body = client.get("/api/articles").json()
    returned_ids = {row["id"] for row in body["results"]}
    assert ids["dirty"] not in returned_ids
    assert ids["clean"] in returned_ids
    assert ids["unset"] in returned_ids
    assert body["total"] == 2


def test_quarantined_article_excluded_even_via_explicit_ids_param(qclient):
    client, ids = qclient
    want = [ids["dirty"], ids["clean"], ids["unset"]]
    body = client.get("/api/articles", params={"ids": ",".join(map(str, want))}).json()
    returned_ids = [row["id"] for row in body["results"]]
    assert ids["dirty"] not in returned_ids
    assert returned_ids == [ids["clean"], ids["unset"]]
    assert body["total"] == 2


def test_quarantined_article_excluded_from_structured_filter_browse(qclient):
    client, ids = qclient
    # a source-scoped browse (no text query, but a structured filter) must still
    # exclude the quarantined row -- proving the always-on condition applies on
    # BOTH sides of the `if filters:` cache-branch in _query_articles.
    body = client.get("/api/articles", params={"source": "Gamma Times"}).json()
    returned_ids = {row["id"] for row in body["results"]}
    assert ids["dirty"] not in returned_ids
    assert body["total"] == 2
