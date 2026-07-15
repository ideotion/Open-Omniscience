"""P1.5 storage-composition diagnostic — per-table/per-index bytes via SQLite dbstat.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 2026-07-09 field event grew the data folder to ~130 GB with an 11.7 GB database;
session forensics names the FILES, this names the INSIDE of the database file. Proves:
real per-table/per-index byte totals over a seeded store (indexes grouped under their
table); the honest degrade blocks (dbstat not compiled in — the sqlcipher3 build's
production reality; a deadline abort; a non-SQLite backend) — degrade, NEVER 500; no
score-shaped keys anywhere; and the endpoint + all-diagnostics wiring.

DBSTAT AVAILABILITY IS PROBED, NOT ASSUMED (macOS lane failure at #606's head SHA):
SQLITE_ENABLE_DBSTAT_VTAB is a per-BUILD flag — Linux stdlib sqlite3 has it, the macOS
runner's Python build does NOT (and the sqlcipher3 build never does). The two tests that
need the full per-table split skip where dbstat is absent; the degrade tests run
everywhere (on macOS the degrade path is exercised natively — it IS the behavior there).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.monitoring import storage as storage_mod
from src.monitoring.storage import storage_composition
from src.database.models import Article, Base, Keyword, KeywordMention, Source


def _dbstat_available() -> bool:
    """Does THIS interpreter's SQLite build compile in the dbstat vtab? (SQLAlchemy's
    sqlite dialect rides the same stdlib sqlite3 library, so this probe matches the
    engine the tests use.)"""
    try:
        con = sqlite3.connect(":memory:")
        try:
            con.execute("SELECT COUNT(*) FROM dbstat").fetchone()
            return True
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - any failure = the build lacks the vtab
        return False


_HAS_DBSTAT = _dbstat_available()


@pytest.fixture()
def db(tmp_path):
    # FILE-backed (dbstat pages are real on-disk pages).
    engine = create_engine(
        f"sqlite:///{tmp_path / 'store.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.flush()
    for i in range(30):
        a = Article(
            url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=1,
            title="T" * 40, content="body " * 500, hash=f"h{i}", language="en",
            published_at=datetime(2024, 3, 1, tzinfo=UTC), created_at=datetime.now(UTC),
        )
        s.add(a)
        s.flush()
        kw = Keyword(term=f"kw{i}", normalized_term=f"kw{i}", language="en")
        s.add(kw)
        s.flush()
        s.add(KeywordMention(keyword_id=kw.id, article_id=a.id, count=1))
    s.commit()
    yield s
    s.close()


def _walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_keys(v)


@pytest.mark.skipif(
    not _HAS_DBSTAT,
    reason="dbstat not compiled into this SQLite build (e.g. the macOS runner's Python)",
)
def test_reports_real_per_table_and_per_index_bytes(db):
    out = storage_composition(db)
    assert out["available"] is True
    assert out["db_bytes"] and out["db_bytes"] > 0
    tables = {t["name"]: t for t in out["tables"]}
    for name in ("articles", "keywords", "keyword_mentions"):
        assert name in tables, f"{name} missing from the composition"
        assert tables[name]["bytes"] > 0 and tables[name]["pages"] > 0
    # The article bodies dominate this fixture — the ordering is by real size.
    assert out["tables"][0]["name"] == "articles"
    # Indexes are grouped UNDER their parent table, with real bytes.
    km = tables["keyword_mentions"]
    assert km["indexes"], "keyword_mentions' covering indexes appear under the table"
    assert all(i["bytes"] > 0 for i in km["indexes"])
    assert km["total_bytes"] == km["bytes"] + km["index_bytes"]
    # The measured btree total can never exceed the file's page total.
    assert out["measured_bytes"] <= out["db_bytes"]
    assert out["method"] and out["caveat"], "method + caveat stay visible"


def test_no_score_shaped_keys_anywhere(db):
    out = storage_composition(db)
    for k in _walk_keys(out):
        assert not any(
            bad in k.lower() for bad in ("score", "trust", "rank", "rating", "verdict")
        ), f"score-shaped key leaked: {k}"


def test_degrades_honestly_when_dbstat_is_not_compiled_in(db, monkeypatch):
    """The PRODUCTION reality on the encrypted store: the sqlcipher3 build ships WITHOUT
    SQLITE_ENABLE_DBSTAT_VTAB (probed 2026-07-09), so the walk must degrade to an honest
    {available: false, reason} block — with the PRAGMA-level totals still reported."""
    real_rows = storage_mod._rows

    def fake_rows(session, sql):
        if "dbstat" in sql:
            raise Exception("no such table: dbstat")  # noqa: TRY002 - mimics OperationalError
        return real_rows(session, sql)

    monkeypatch.setattr(storage_mod, "_rows", fake_rows)
    out = storage_composition(db)
    assert out["available"] is False
    assert "dbstat" in out["reason"]
    assert out["db_bytes"] > 0, "the cheap PRAGMA totals still stand"
    assert "tables" not in out, "never a fabricated per-table split"
    assert out["method"] and out["caveat"]


def test_degrades_honestly_on_a_deadline_abort(db, monkeypatch):
    from contextlib import contextmanager

    from src.database.maintenance import StatementTimeout

    @contextmanager
    def instant_deadline(session, seconds=None):
        raise StatementTimeout("aborted after 60s")
        yield  # pragma: no cover

    monkeypatch.setattr(storage_mod, "statement_deadline", instant_deadline)
    out = storage_composition(db)
    assert out["available"] is False
    assert "deadline" in out["reason"]
    assert out["db_bytes"] > 0


def test_non_sqlite_backend_reports_unsupported():
    class _Dialect:
        name = "postgresql"

    class _Bind:
        dialect = _Dialect()

    class _Sess:
        def get_bind(self):
            return _Bind()

    out = storage_composition(_Sess())
    assert out["available"] is False
    assert out["dialect"] == "postgresql"


@pytest.mark.skipif(
    not _HAS_DBSTAT,
    reason="dbstat not compiled into this SQLite build (e.g. the macOS runner's Python)",
)
def test_endpoint_serves_and_downloads(tmp_path):
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'api.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            r = client.get("/api/diagnostics/storage-composition")
            assert r.status_code == 200
            body = r.json()
            assert body["kind"] == "storage-composition"
            assert body["data"]["available"] is True
            assert any(t["name"] == "articles" for t in body["data"]["tables"])

            r2 = client.get("/api/diagnostics/storage-composition?download=1")
            assert r2.status_code == 200
            assert "oo-storage-composition-" in r2.headers.get("content-disposition", "")
    finally:
        app.dependency_overrides.clear()


def test_rides_the_debug_bundle_and_the_all_diagnostics_zip(db):
    """The member must reach the operator's export channels: the /all zip member list
    (behavioral) and the debug bundle's _safe(...) set (source-pinned — the bundle
    itself needs the full app runtime)."""
    from pathlib import Path

    import src.api.diagnostics as diag

    names = [n for n, _fn in diag._all_diagnostics_members(db)]
    assert "storage-composition.json" in names

    src_text = Path(diag.__file__).read_text(encoding="utf-8")
    # S8: the bundle member is individually guarded + budgeted via _member (db_bound so a
    # runaway dbstat scan is deadline-interrupted, never stalls the bundle).
    assert '"storage_composition": _member(' in src_text
    assert "lambda: _storage_composition(db)" in src_text
