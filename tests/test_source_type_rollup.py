"""In-memory serve for the ``/api/insights/source-types`` channel facet.

D3 (2026-09-11): field diagnostics measured this endpoint's live aggregate at
48,471.9 ms worst-case / 7,181.9 ms p50 -- the single slowest query in the bundle.
Proves the rollup is SAFE and FAITHFUL, mirroring test_source_country_rollup.py's own
structure for its sibling rollup: cold-before-first-refresh falls back to live; a
warm rollup serves a payload BYTE-IDENTICAL to the live compute plus a ``basis``
disclosure; the QUARANTINED-article exclusion (the equality with /api/articles that
source_type_facets' own docstring states as a property) survives being served from
the rollup; the rebuild is CHANGE-TOKEN GATED (unlike source_country_rollup's
unconditional refresh) so an idle corpus does not rescan articles; BIND-AWARE and
CORPUS-EPOCH-AWARE; ``served()`` degrades to ``None`` on any internal error.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from src.analytics import source_type_rollup
from src.database.models import Article, Base, Source


def _new_session():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _add_source(db, name, *, source_type=None):
    # A genuine NULL source_type cannot be passed through the constructor -- the
    # ORM's column-level Python default ("news") fires on INSERT even for an
    # explicit None, exactly as tests/test_source_type_facet.py's own
    # test_untyped_bucket_facet_matches_filter documents. A real NULL comes from a
    # bulk UPDATE after the row exists (mirroring non-ORM paths -- the raw-SQL
    # restore-merge insert, wikidata_apply).
    src = Source(name=name, domain=f"{name.lower()}.test", source_type=source_type or "news")
    db.add(src)
    db.commit()
    if source_type is None:
        db.query(Source).filter_by(id=src.id).update({Source.source_type: None})
        db.commit()
        db.refresh(src)
    return src


def _add_article(db, src, i, *, quarantined=False):
    db.add(
        Article(
            url=f"https://{src.domain}/{i}",
            canonical_url=f"https://{src.domain}/{i}",
            source_id=src.id,
            title=f"article {i}",
            content=f"content {i}",
            # Padded with a non-digit so e.g. "h1-1" and "h1-100" (which share a
            # zero-heavy suffix once padded with "0") can never collide.
            hash=f"h{src.id}-{i}".ljust(64, "x"),
            language="en",
            quarantined=quarantined,
        )
    )
    db.commit()


def _seed_mixed_corpus(db):
    """Two typed channels, an UNTYPED source (NULL source_type), and a quarantined
    article that must be excluded from both the live compute and the served one."""
    news = _add_source(db, "News", source_type="news")
    nl = _add_source(db, "Newsletter", source_type="newsletter")
    untyped = _add_source(db, "Untyped", source_type=None)
    for i in range(3):
        _add_article(db, news, i)
    _add_article(db, nl, 0)
    _add_article(db, untyped, 0)
    _add_article(db, news, 99, quarantined=True)  # excluded everywhere
    return news, nl, untyped


# --------------------------------------------------------------------------- #
# Cold / warm parity, faithfulness.
# --------------------------------------------------------------------------- #


def test_cold_before_first_refresh_falls_back_to_live():
    db = _new_session()
    _seed_mixed_corpus(db)
    assert source_type_rollup.served(db) is None


def test_served_payload_is_byte_identical_to_live_with_a_basis():
    db = _new_session()
    _seed_mixed_corpus(db)
    live = source_type_rollup._live_source_type_facets(db)
    source_type_rollup.refresh(db)
    served = source_type_rollup.served(db)
    assert served is not None
    served_no_basis = {k: v for k, v in served.items() if k != "basis"}
    assert served_no_basis == live
    assert served["basis"]["source"] == "rollup"
    assert served["basis"]["as_of"]
    assert served["basis"]["refresh_interval_s"] == 300


def test_quarantined_articles_stay_excluded_through_the_rollup():
    """source_type_facets' own docstring states, as a property found by adversarial
    review, that the facet count EQUALS what clicking it returns from /api/articles
    -- which excludes quarantined articles. The rollup must not break that."""
    db = _new_session()
    _seed_mixed_corpus(db)
    source_type_rollup.refresh(db)
    served = source_type_rollup.served(db)
    assert served is not None
    by = {f["source_type"]: f["articles"] for f in served["facets"]}
    assert by == {"news": 3, "newsletter": 1, "untyped": 1}
    assert served["total"] == 5  # NOT 6 -- the quarantined article never counts


def test_not_served_from_source_article_count():
    """The stated trap: Source.article_count does not carry the quarantine
    exclusion, so a rollup sourced from it would silently disagree with the live
    query. Corrupt article_count on every source and prove the served payload is
    unaffected -- it can only be reading real article rows, not the counter."""
    db = _new_session()
    news, nl, untyped = _seed_mixed_corpus(db)
    for src in (news, nl, untyped):
        src.article_count = 999999
    db.commit()
    source_type_rollup.refresh(db)
    served = source_type_rollup.served(db)
    assert served is not None
    by = {f["source_type"]: f["articles"] for f in served["facets"]}
    assert by == {"news": 3, "newsletter": 1, "untyped": 1}
    assert served["total"] == 5


def test_a_caller_mutating_its_served_payload_never_corrupts_the_singleton():
    db = _new_session()
    _seed_mixed_corpus(db)
    source_type_rollup.refresh(db)

    first = source_type_rollup.served(db)
    assert first is not None
    first["facets"].clear()
    first["facets"].append({"source_type": "poisoned", "articles": 999})

    second = source_type_rollup.served(db)
    assert second is not None
    assert second["facets"] != first["facets"]
    assert all(f["source_type"] != "poisoned" for f in second["facets"])


def test_bind_aware_never_answers_for_another_database():
    a = _new_session()
    _seed_mixed_corpus(a)
    source_type_rollup.refresh(a)

    b = _new_session()
    src = _add_source(b, "Other", source_type="market")
    _add_article(b, src, 0)

    assert source_type_rollup.served(b) is None  # a's rollup reflects a, not b
    assert source_type_rollup.served(a) is not None


def test_no_articles_or_sources_query_issued_when_rollup_is_warm():
    db = _new_session()
    _seed_mixed_corpus(db)
    source_type_rollup.refresh(db)

    queries: list[str] = []
    conn = db.get_bind().connect()

    def _capture(conn_, cursor, statement, *a):
        queries.append(statement)

    event.listen(conn.engine, "before_cursor_execute", _capture)
    try:
        result = source_type_rollup.served(db)
    finally:
        event.remove(conn.engine, "before_cursor_execute", _capture)
    assert result is not None
    assert not any(
        "join articles" in q.lower() or "from articles" in q.lower() for q in queries
    )


def test_empty_corpus_serves_an_honest_empty_rollup():
    db = _new_session()
    source_type_rollup.refresh(db)
    served = source_type_rollup.served(db)
    assert served is not None
    assert served["facets"] == []
    assert served["total"] == 0


# --------------------------------------------------------------------------- #
# D3's own trap: the rebuild is change-token gated, unlike source_country_rollup.
# --------------------------------------------------------------------------- #


def test_refresh_is_a_no_op_when_nothing_changed():
    db = _new_session()
    _seed_mixed_corpus(db)
    first = source_type_rollup.refresh(db)
    assert first == {"rebuilt": True}

    second = source_type_rollup.refresh(db)
    assert second == {"rebuilt": False}, "an unchanged watermark must not re-scan articles"


def test_refresh_rebuilds_when_new_articles_land():
    db = _new_session()
    news, _nl, _untyped = _seed_mixed_corpus(db)
    assert source_type_rollup.refresh(db) == {"rebuilt": True}
    assert source_type_rollup.refresh(db) == {"rebuilt": False}

    _add_article(db, news, 100)
    assert source_type_rollup.refresh(db) == {"rebuilt": True}
    served = source_type_rollup.served(db)
    assert served is not None
    by = {f["source_type"]: f["articles"] for f in served["facets"]}
    assert by["news"] == 4


def test_refresh_does_not_touch_articles_or_sources_when_nothing_changed():
    """The cost this gate exists to avoid: a no-op refresh must issue only the
    cheap watermark read (a MAX(id) lookup), never the expensive articles<->sources
    JOIN + GROUP BY the live compute runs."""
    db = _new_session()
    _seed_mixed_corpus(db)
    source_type_rollup.refresh(db)  # first build, real scan

    queries: list[str] = []
    conn = db.get_bind().connect()

    def _capture(conn_, cursor, statement, *a):
        queries.append(statement)

    event.listen(conn.engine, "before_cursor_execute", _capture)
    try:
        out = source_type_rollup.refresh(db)
    finally:
        event.remove(conn.engine, "before_cursor_execute", _capture)
    assert out == {"rebuilt": False}
    assert not any("join" in q.lower() and "sources" in q.lower() for q in queries), queries
    assert not any("group by" in q.lower() for q in queries), queries


def test_refresh_rebuilds_on_a_corpus_epoch_bump_even_with_no_new_articles():
    from src.analytics.corpus_epoch import bump_corpus_epoch

    db = _new_session()
    _seed_mixed_corpus(db)
    assert source_type_rollup.refresh(db) == {"rebuilt": True}
    assert source_type_rollup.refresh(db) == {"rebuilt": False}

    bump_corpus_epoch(db, reason="test-restore-merge")
    assert source_type_rollup.refresh(db) == {"rebuilt": True}


# --------------------------------------------------------------------------- #
# Endpoint-level parity.
# --------------------------------------------------------------------------- #


def test_endpoint_serves_basis_and_matches_the_live_endpoint(tmp_path):
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'api.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, future=True)
    with TestSession() as s:
        _seed_mixed_corpus(s)

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as client:
            live = client.get("/api/insights/source-types").json()
            with TestSession() as s:
                source_type_rollup.refresh(s)
            served = client.get("/api/insights/source-types").json()
    finally:
        app.dependency_overrides.pop(get_db, None)

    for k in ("facets", "total", "method", "caveat"):
        assert served[k] == live[k]
    assert served["basis"]["source"] == "rollup"
    assert live.get("basis") is None


# --------------------------------------------------------------------------- #
# Cross-test isolation.
# --------------------------------------------------------------------------- #


def test_reset_for_tests_clears_a_warm_rollup():
    db = _new_session()
    _seed_mixed_corpus(db)
    source_type_rollup.refresh(db)
    assert source_type_rollup.served(db) is not None

    source_type_rollup._reset_for_tests()

    assert source_type_rollup.served(db) is None


def test_warming_the_real_app_engine_rollup_never_survives_this_test():
    """Mirrors test_source_country_rollup.py's identical regression guard: a test
    that refreshes against the REAL app engine must not leave the rollup warm for
    a later, unrelated test on that same engine -- the conftest.py autouse fixture
    is what a later test in the suite relies on."""
    from src.database.session import engine as _app_engine
    from src.database.session import init_db, session_scope

    init_db()
    with session_scope() as app_session:
        assert app_session.get_bind() is _app_engine
        source_type_rollup.refresh(app_session)
        assert source_type_rollup.served(app_session) is not None


# --------------------------------------------------------------------------- #
# Corpus-epoch invalidation + served()'s exception safety.
# --------------------------------------------------------------------------- #


def test_a_corpus_epoch_bump_invalidates_the_rollup_even_on_the_same_bind():
    from src.analytics.corpus_epoch import bump_corpus_epoch

    db = _new_session()
    _seed_mixed_corpus(db)
    source_type_rollup.refresh(db)
    assert source_type_rollup.served(db) is not None

    bump_corpus_epoch(db, reason="test-restore-merge")

    assert source_type_rollup.served(db) is None


def test_served_never_raises_on_a_malformed_singleton_payload():
    db = _new_session()
    _seed_mixed_corpus(db)
    source_type_rollup.refresh(db)
    assert source_type_rollup.served(db) is not None

    with source_type_rollup._LOCK:
        source_type_rollup._STATE["payload"] = "not-a-dict"

    assert source_type_rollup.served(db) is None
    source_type_rollup._reset_for_tests()
