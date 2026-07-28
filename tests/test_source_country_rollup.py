"""In-memory serve for the ``/api/database/countries`` per-country breakdown.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

2026-07-26 hardware diagnostics: this endpoint's live query was a bare ``SCAN
sources`` (the ``tags`` column isn't index-covered), the dominant server-cost item
on all 7 field instances. Proves the rollup is SAFE and FAITHFUL: cold-before-first-
refresh falls back to live; a warm rollup serves a payload BYTE-IDENTICAL to the
live compute (including ``top_tags`` truncation/ordering ties) plus a ``basis``
disclosure; BIND-AWARE (never answers for a database it wasn't built over) AND
CORPUS-EPOCH-AWARE (never answers across a restore/re-index/prune that reused the
same Engine object -- a mandatory skeptic fan-out found the bind check alone is
defeated by ``dispose_engine()``'s pool-dispose-then-reuse pattern); a warm serve
never touches ``sources`` at all; the whole ``served()`` body degrades to ``None``
on any internal error, matching its own documented contract.
"""

from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from src.analytics import source_country_rollup
from src.database.models import Base, Source


def _new_session():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _seed_sources_across_countries(db):
    """A country with only disabled sources; a mixed enabled/disabled country; a
    no-country source (the "(none)" bucket); overlapping vs. disjoint tags; and
    >8 distinct tags in one country (exercises Counter.most_common(8) truncation)."""
    db.add_all(
        [
            Source(name="A1", domain="a1.test", country="fr", enabled=True, tags="news,world"),
            Source(name="A2", domain="a2.test", country="fr", enabled=False, tags="news,sport"),
            Source(name="B1", domain="b1.test", country="de", enabled=False, tags="finance"),
            Source(name="B2", domain="b2.test", country="de", enabled=False, tags="finance,tech"),
            Source(name="N1", domain="n1.test", country=None, enabled=True, tags=""),
        ]
    )
    # A country with many distinct tags -- exercises most_common(8) truncation.
    for i in range(10):
        db.add(
            Source(
                name=f"US{i}", domain=f"us{i}.test", country="us", enabled=True, tags=f"tag{i}"
            )
        )
    db.commit()


def test_cold_before_first_refresh_falls_back_to_live():
    db = _new_session()
    _seed_sources_across_countries(db)
    assert source_country_rollup.served(db) is None


def test_served_payload_is_byte_identical_to_live_with_a_basis():
    db = _new_session()
    _seed_sources_across_countries(db)
    live = source_country_rollup._live_sources_by_country(db)
    source_country_rollup.refresh(db)
    served = source_country_rollup.served(db)
    assert served is not None
    served_no_basis = {k: v for k, v in served.items() if k != "basis"}
    assert served_no_basis == live
    assert served["basis"]["source"] == "rollup"
    assert served["basis"]["as_of"]
    assert served["basis"]["refresh_interval_s"] == 300


def test_a_caller_mutating_its_served_payload_never_corrupts_the_singleton():
    """Skeptic finding (2026-07-26, byte-parity lens): served() used to return a
    SHALLOW dict(payload), sharing the nested countries/missing/missing_names
    containers with the process-global singleton across every caller until the
    next refresh -- a future in-place mutation by ANY caller would silently
    poison every OTHER caller's response for up to 5 minutes."""
    db = _new_session()
    _seed_sources_across_countries(db)
    source_country_rollup.refresh(db)

    first = source_country_rollup.served(db)
    assert first is not None
    first["countries"].clear()  # an aggressive in-place mutation
    first["countries"].append({"code": "zz", "name": "poisoned", "sources": 999})
    first["missing"].append("poisoned")
    first["missing_names"]["poisoned"] = "poisoned"

    second = source_country_rollup.served(db)
    assert second is not None
    assert second["countries"] != first["countries"]
    assert "poisoned" not in second["missing"]
    assert "poisoned" not in second["missing_names"]


def test_bind_aware_never_answers_for_another_database():
    a = _new_session()
    _seed_sources_across_countries(a)
    source_country_rollup.refresh(a)

    b = _new_session()
    b.add(Source(name="Z", domain="z.test", country="jp", enabled=True, tags=""))
    b.commit()

    assert source_country_rollup.served(b) is None  # a's rollup reflects a, not b
    assert source_country_rollup.served(a) is not None


def test_no_sources_query_issued_when_rollup_is_warm():
    db = _new_session()
    _seed_sources_across_countries(db)
    source_country_rollup.refresh(db)

    queries: list[str] = []
    conn = db.get_bind().connect()

    def _capture(conn_, cursor, statement, *a):
        queries.append(statement)

    event.listen(conn.engine, "before_cursor_execute", _capture)
    try:
        result = source_country_rollup.served(db)
    finally:
        event.remove(conn.engine, "before_cursor_execute", _capture)
    assert result is not None
    assert not any("sources" in q.lower() for q in queries)


def test_unlocated_none_country_bucket_survives_the_rollup():
    db = _new_session()
    db.add(Source(name="Only", domain="only.test", country=None, enabled=True, tags=""))
    db.commit()
    source_country_rollup.refresh(db)
    served = source_country_rollup.served(db)
    assert served is not None
    codes = {c["code"] for c in served["countries"]}
    assert "(none)" in codes
    assert served["covered"] == 0  # the (none) bucket is excluded from "covered"


def test_empty_sources_table_serves_an_honest_empty_rollup():
    db = _new_session()
    source_country_rollup.refresh(db)
    served = source_country_rollup.served(db)
    assert served is not None
    assert served["countries"] == []
    assert served["covered"] == 0


# --------------------------------------------------------------------------- #
# Endpoint-level parity: GET /api/database/countries matches the live compute
# before a refresh, and carries a basis disclosure after one.
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
        _seed_sources_across_countries(s)

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    import src.api.database as database_mod

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as client:
            live = client.get("/api/database/countries").json()
            with TestSession() as s:
                source_country_rollup.refresh(s)
            # Bust the endpoint's own 30s write-probed cache: refreshing the rollup
            # writes only to the in-process rollup state, not the DB, so
            # PRAGMA data_version is unchanged and the cache would otherwise still
            # serve the pre-refresh live payload it already computed above.
            database_mod._cache.clear()
            served = client.get("/api/database/countries").json()
    finally:
        app.dependency_overrides.pop(get_db, None)

    for k in ("countries", "covered", "total_countries", "missing", "missing_names", "missing_count"):
        assert served[k] == live[k]
    assert served["basis"]["source"] == "rollup"
    assert "basis" not in live or live.get("basis") is None


# --------------------------------------------------------------------------- #
# Cross-test isolation: a rollup warmed against the real app engine by one
# test must never leak into a LATER, unrelated test that expects a fresh live
# compute (the same order-dependent-pollution class the write-gate/memory-
# guard/dedup-front fixtures in tests/conftest.py already guard against).
# --------------------------------------------------------------------------- #


def test_reset_for_tests_clears_a_warm_rollup():
    db = _new_session()
    _seed_sources_across_countries(db)
    source_country_rollup.refresh(db)
    assert source_country_rollup.served(db) is not None  # warm

    source_country_rollup._reset_for_tests()

    assert source_country_rollup.served(db) is None  # cold again -- live fallback


def test_warming_the_real_app_engine_rollup_never_survives_this_test():
    """The exact live regression (2026-07-26): a test that calls ``refresh()``
    against the REAL app engine (mirroring test_offpeak_maintenance.py's
    off-peak-maintenance wiring tests) must never leave the rollup warm for a
    LATER, unrelated test on that same engine -- test_database_api.py's
    countries-breakdown test failed exactly this way (StopIteration: freshly
    added ZZ-country sources missing from a rollup snapshot taken before they
    existed) only when it ran after this kind of test, never alone. Warms the
    rollup here; the conftest.py autouse fixture's teardown is what a LATER
    test in the suite relies on -- pinned end-to-end by leaving the rollup warm
    at the end of THIS test body and trusting the fixture to clean it up (the
    next test file that touches the real engine is the actual witness)."""
    from src.database.session import engine as _app_engine
    from src.database.session import init_db, session_scope

    init_db()
    with session_scope() as app_session:
        assert app_session.get_bind() is _app_engine
        source_country_rollup.refresh(app_session)
        assert source_country_rollup.served(app_session) is not None  # warm, real engine


# --------------------------------------------------------------------------- #
# Skeptic-found fixes (2026-07-26 mandatory fan-out): corpus-epoch invalidation
# (restore/re-index/prune can reuse the same Engine object, defeating a pure
# bind-identity check) and served()'s own exception safety.
# --------------------------------------------------------------------------- #


def test_a_corpus_epoch_bump_invalidates_the_rollup_even_on_the_same_bind():
    """Skeptic finding (2026-07-26, fallback-safety lens, live-reproduced):
    ``src.backup.merge.run_restore``'s commit stage calls ``dispose_engine()``
    then atomically swaps the on-disk file then ``init_db()`` -- all against the
    SAME module-level Engine object, so a pure bind-identity check cannot detect
    a restore. Restore-merge already bumps the canonical corpus epoch
    (``src.analytics.corpus_epoch.bump_corpus_epoch``, reason="restore_merge");
    the rollup must fall back to live the moment that epoch changes, on the
    IDENTICAL bind, mirroring how the DuckDB rollups (rollup_serve/columnar.py)
    already use this same guard against exactly this class of swap."""
    from src.analytics.corpus_epoch import bump_corpus_epoch

    db = _new_session()
    _seed_sources_across_countries(db)
    source_country_rollup.refresh(db)
    assert source_country_rollup.served(db) is not None  # warm, same bind

    bump_corpus_epoch(db, reason="test-restore-merge")

    # Still the SAME bind -- only the epoch changed -- yet must now fall back.
    assert source_country_rollup.served(db) is None


def test_served_never_raises_on_a_malformed_singleton_payload():
    """Skeptic finding (2026-07-26, fallback-safety lens): served()'s docstring
    claims "any exception -> None", but only _same_bind() was actually guarded --
    a fault reconstructing the payload (a future bug elsewhere leaving _STATE
    malformed) propagated as an uncaught exception all the way to the client
    (neither _compute() nor _cached() in src/api/database.py guards this call),
    turning a documented safe-fallback into a 500. Simulates exactly that: a
    payload that is not a dict, so copy.deepcopy()+basis-assembly cannot succeed."""
    db = _new_session()
    _seed_sources_across_countries(db)
    source_country_rollup.refresh(db)
    assert source_country_rollup.served(db) is not None  # warm, sane

    with source_country_rollup._LOCK:
        source_country_rollup._STATE["payload"] = "not-a-dict"

    assert source_country_rollup.served(db) is None  # never raises; falls back
    source_country_rollup._reset_for_tests()
