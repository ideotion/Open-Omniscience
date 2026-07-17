"""
End-to-end API tests for search + export (Action Plan Phase 1.5/1.6).

Drives the real FastAPI app through TestClient, with the get_db dependency
overridden onto an isolated temp database, proving the whole flow:
Boolean full-text search, structured filters, pagination, and CSV/JSON export.
"""

from __future__ import annotations

import csv
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.database.fts import ensure_fts
from src.database.models import Article, Base, Source
from src.database.session import get_db


@pytest.fixture()
def client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'api.db'}",
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

    with TestSession() as s:
        src1 = Source(name="Alpha News", domain="alpha.example", tags="politics,world")
        src2 = Source(name="Beta Wire", domain="beta.example", tags="markets")
        s.add_all([src1, src2])
        s.flush()
        s.add_all(
            [
                Article(
                    url="https://alpha.example/1",
                    canonical_url="https://alpha.example/1",
                    source_id=src1.id,
                    title="Quantum leap",
                    content="scientists report a quantum breakthrough",
                    hash="1".ljust(64, "0"),
                    language="en",
                ),
                Article(
                    url="https://alpha.example/2",
                    canonical_url="https://alpha.example/2",
                    source_id=src1.id,
                    title="Market jitters",
                    content="oil prices DROP amid quantum computing hype",
                    hash="2".ljust(64, "0"),
                    language="en",
                ),
                Article(
                    url="https://beta.example/3",
                    canonical_url="https://beta.example/3",
                    source_id=src2.id,
                    title="Telecom",
                    content="AT&T announces a merger",
                    hash="3".ljust(64, "0"),
                    language="fr",
                ),
            ]
        )
        s.commit()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_health_reports_real_version(client):
    # Assert against the package metadata (the single source of truth) rather than a
    # hardcoded literal, so the version can never silently drift between pyproject and
    # the running app (see docs/CONTRIBUTING.md).
    from importlib.metadata import version as _pkg_version

    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["version"] == _pkg_version("open-omniscience")


def test_boolean_search_and(client):
    r = client.get("/api/articles", params={"query": "quantum AND oil"})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["results"][0]["title"] == "Market jitters"


def test_fts_id_resolve_is_chunked_and_byte_identical(client, monkeypatch):
    """Audit finding 2026-07-17: _query_articles's fts_ids -> Article.id.in_(fts_ids)
    resolve query was unchunked, but search_ids's own cap (_MAX_CANDIDATES=20000,
    src/database/fts.py) is far past SQLite's historical ~999 bound-variable
    ceiling used everywhere else in this codebase. This is the core GET
    /api/articles search/browse endpoint. Forces chunking with a tiny
    _FTS_ID_CHUNK (2 matches needing 2 chunks of 1) and asserts the result is
    BYTE-IDENTICAL to the unchunked default -- chunking must be a pure
    implementation detail, never change the answer or its order."""
    import src.api.main as main_mod

    unchunked = client.get("/api/articles", params={"query": "quantum"}).json()
    assert unchunked["total"] == 2  # both quantum articles match -- a non-vacuous test

    monkeypatch.setattr(main_mod, "_FTS_ID_CHUNK", 1, raising=True)
    chunked = client.get("/api/articles", params={"query": "quantum"}).json()
    assert chunked == unchunked


def test_boolean_search_or(client):
    r = client.get("/api/articles", params={"query": "breakthrough OR merger"})
    titles = {row["title"] for row in r.json()["results"]}
    assert titles == {"Quantum leap", "Telecom"}


def test_search_does_not_strip_keywords(client):
    # "DROP" must be searchable; "AT&T" must not be mangled.
    assert client.get("/api/articles", params={"query": "oil prices DROP"}).json()["total"] == 1
    assert client.get("/api/articles", params={"query": "AT&T"}).json()["total"] == 1


def test_invalid_query_returns_400(client):
    r = client.get("/api/articles", params={"query": "(unbalanced OR"})
    assert r.status_code == 400


def test_structured_filters(client):
    # language filter
    assert client.get("/api/articles", params={"language": "fr"}).json()["total"] == 1
    # source filter
    assert client.get("/api/articles", params={"source": "Beta Wire"}).json()["total"] == 1
    # unknown source -> 404
    assert client.get("/api/articles", params={"source": "Nope"}).status_code == 404
    # tag filter (source tags)
    assert client.get("/api/articles", params={"tags": "markets"}).json()["total"] == 1


def test_pagination(client):
    r = client.get("/api/articles", params={"limit": 1, "offset": 0})
    body = r.json()
    assert body["total"] == 3
    assert len(body["results"]) == 1


def test_ids_param_returns_explicit_set_in_order(client):
    # A card-seeded analysis corpus passes an explicit id set; the endpoint must
    # return exactly those, in the requested order (synthesis selection relies on it).
    all_ids = [row["id"] for row in client.get("/api/articles").json()["results"]]
    assert len(all_ids) == 3
    want = [all_ids[2], all_ids[0]]  # a deliberate out-of-natural order subset
    body = client.get("/api/articles", params={"ids": ",".join(map(str, want))}).json()
    assert body["total"] == 2
    assert [r["id"] for r in body["results"]] == want
    # a non-existent id is silently dropped, never fabricated
    body2 = client.get("/api/articles", params={"ids": f"{all_ids[0]},999999"}).json()
    assert [r["id"] for r in body2["results"]] == [all_ids[0]]


def test_export_csv_matches_filter(client):
    r = client.get("/api/articles/export", params={"format": "csv", "query": "quantum"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    # header + 2 quantum articles; columns unchanged (the envelope is in headers)
    assert rows[0][0] == "ID"
    assert len(rows) == 1 + 2
    assert r.headers["X-OO-Export-Schema"] == "oo-export-1"
    assert "query=quantum" in r.headers["X-OO-Query"]


def test_export_json_matches_filter(client):
    r = client.get("/api/articles/export", params={"format": "json", "source": "Beta Wire"})
    assert r.status_code == 200
    body = r.json()
    # envelope (WP2/RM-15): provenance travels with the data
    assert body["export_schema"] == "oo-export-1"
    assert body["query"] == {"source": "Beta Wire"}
    assert body["count"] == 1
    assert body["articles"][0]["title"] == "Telecom"


def test_export_rejects_bad_format(client):
    assert client.get("/api/articles/export", params={"format": "xml"}).status_code == 400
