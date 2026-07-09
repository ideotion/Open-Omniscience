"""In-memory serve for the per-country map-coverage aggregation (D4, scaling 5A-bis).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Proves the map serve is SAFE and FAITHFUL: AUTO-ON when duckdb is available (P1.11 —
flipped 2026-07-09 on the 12:14 field logs' #1 slow query, the map country GROUP BY at
~150 s/call) with the rollup_serve tri-state (``OO_COLUMNAR_MAP_SERVE=0`` forces off,
``=1`` forces on, unset = auto); forced-off is the untouched live path even with a built
rollup; enabled-but-not-built falls back to live; built serves a payload BYTE-IDENTICAL to
the live source_country_counts (by_country + unlocated incl. the per-language donut +
totals) plus a ``basis`` disclosure; and it is BIND-AWARE — it never answers for a
database it was not built over (#572).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import columnar
from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.models import Article, Base, Source

pytestmark = pytest.mark.skipif(
    not columnar.duckdb_available(), reason="duckdb not installed (optional [columnar] extra)"
)


def _new_session():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _source(db, sid, domain, country):
    db.add(Source(id=sid, name=f"S{sid}", domain=domain, country=country))
    db.commit()


def _article(db, sid, hash_, text, *, tone=None, lang="en"):
    country = db.get(Source, sid).country
    a = Article(
        url=f"https://x.test/{hash_}", canonical_url=f"https://x.test/{hash_}", source_id=sid,
        title="T", content=text, hash=hash_, language=lang, sentiment_score=tone,
        published_at=datetime(2024, 3, 1, tzinfo=UTC), created_at=datetime.now(UTC),
    )
    db.add(a)
    db.commit()
    index_article(db, a, extractor=BaselineExtractor(), country=country)
    return a


def _seed(db):
    _source(db, 1, "fr.test", "fr")
    _source(db, 2, "us.test", "us")
    _source(db, 3, "unl.test", None)  # unlocated -> the '' bucket + a by-language donut
    _article(db, 1, "a1", "Climate policy and trade dominated the summit.", tone=0.4)
    _article(db, 2, "a2", "Climate policy again and elections everywhere.", tone=-0.2)
    _article(db, 2, "a3", "Elections and the economy in focus.", tone=None, lang="fr")
    _article(db, 3, "a4", "Trade and climate in the newsletter.", tone=0.1, lang="es")


@pytest.fixture()
def db():
    s = _new_session()
    _seed(s)
    return s


@pytest.fixture(autouse=True)
def _reset_serve_state():
    from src.analytics import map_serve

    yield
    con = map_serve._STATE.get("con")
    if con is not None:
        try:
            con.close()
        except Exception:  # noqa: BLE001
            pass
    map_serve._STATE.update({"con": None, "built_at": 0.0, "rows": 0, "bind": None})


def _build_over(session):
    """Build the process-lifetime rollup from ``session`` (bypassing the background thread)."""
    from src.analytics import map_serve

    con = columnar.connect(passphrase=None)
    columnar.build_source_coverage(con, session)
    map_serve._STATE["con"] = con
    map_serve._STATE["bind"] = session.get_bind()
    map_serve._STATE["built_at"] = time.time()
    return con


def test_default_is_auto_on_and_zero_forces_off_even_with_a_built_rollup(db, monkeypatch):
    """P1.11: unset = AUTO-ON when duckdb is available (this file already skips without
    it); '0' forces off — even a built rollup must then never answer; '1' forces on."""
    from src.analytics import map_serve

    monkeypatch.delenv("OO_COLUMNAR_MAP_SERVE", raising=False)
    assert map_serve.serve_mode() == "auto"
    assert map_serve.serve_enabled() is True

    monkeypatch.setenv("OO_COLUMNAR_MAP_SERVE", "0")
    assert map_serve.serve_mode() == "forced-off"
    assert map_serve.serve_enabled() is False
    _build_over(db)  # even with a built rollup, forced-off keeps the live path untouched
    assert map_serve.map_coverage(db) is None

    monkeypatch.setenv("OO_COLUMNAR_MAP_SERVE", "1")
    assert map_serve.serve_mode() == "forced-on"
    assert map_serve.serve_enabled() is True


def test_enabled_but_not_built_falls_back_to_live(db, monkeypatch):
    from src.analytics import map_serve

    monkeypatch.setenv("OO_COLUMNAR_MAP_SERVE", "1")
    assert map_serve.serve_enabled() is True
    assert map_serve.map_coverage(db) is None  # nothing built yet -> live fallback


def test_served_payload_is_byte_identical_to_live_with_a_basis(db, monkeypatch):
    from src.analytics import map_serve
    from src.analytics.queries import source_country_counts

    live = source_country_counts(db)
    _build_over(db)
    monkeypatch.setenv("OO_COLUMNAR_MAP_SERVE", "1")

    served = map_serve.map_coverage(db)
    assert served is not None
    assert served["basis"]["source"] == "columnar-rollup"
    assert served["basis"]["as_of"], "the served response discloses its as-of build time"

    # Strip the disclosure -> the rest must equal the live query EXACTLY (by_country order,
    # unlocated incl. the per-language donut, and both totals).
    served_no_basis = {k: v for k, v in served.items() if k != "basis"}
    assert served_no_basis == live
    # The unlocated donut is present and non-trivial (fr + es articles from source 3... here
    # only es a4 is unlocated; fr a3 is from source 2 = 'us').
    assert served["unlocated"]["by_language"] == live["unlocated"]["by_language"]
    assert served["unlocated"]["by_language"]  # not empty


def test_bind_aware_never_answers_for_another_database(db, monkeypatch):
    from src.analytics import map_serve

    _build_over(db)  # rollup built over db's engine
    monkeypatch.setenv("OO_COLUMNAR_MAP_SERVE", "1")

    other = _new_session()  # a DIFFERENT engine, same seed
    _seed(other)
    # Even though a rollup is built and we are opted in, a session on another engine must
    # fall back to live (it would otherwise return db's numbers for other's corpus).
    assert map_serve.map_coverage(other) is None
    # ...while the matching session still serves.
    assert map_serve.map_coverage(db) is not None


def test_endpoint_serves_basis_and_matches_the_live_endpoint(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import src.api.insights as insights
    from src.api.main import app
    from src.database.session import get_db

    # Disable the read cache so on/off both recompute (no cache pollution between requests).
    monkeypatch.setattr(insights, "_CACHE_TTL_S", 0)

    # A FILE-backed SQLite so every session/thread (TestClient request, the build) shares the
    # same DB — an in-memory engine gives each connection its own empty database.
    engine = create_engine(
        f"sqlite:///{tmp_path / 'map.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    seed = Sess()
    _seed(seed)
    seed.close()

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    try:
        client = TestClient(app)

        # Live (serve forced off — unset is now AUTO-ON, which would kick a background
        # build against the process store and race this test's fixture engine).
        monkeypatch.setenv("OO_COLUMNAR_MAP_SERVE", "0")
        live = client.get("/api/insights/map-coverage").json()
        assert "basis" not in live

        # Served (rollup built over the SAME engine + opted in).
        _build_over(Sess())
        monkeypatch.setenv("OO_COLUMNAR_MAP_SERVE", "1")
        served = client.get("/api/insights/map-coverage").json()

        assert served["basis"]["source"] == "columnar-rollup"
        # The enriched map data (name/continent/lat-lon added by the endpoint) is identical.
        assert served["by_country"] == live["by_country"]
        assert served["unlocated"] == live["unlocated"]
        assert served["total_sources"] == live["total_sources"]
        assert served["total_articles"] == live["total_articles"]
    finally:
        app.dependency_overrides.clear()
