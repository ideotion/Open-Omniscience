"""D1/D2/D3: the PERSISTED rollup serve path (S3.2).

The serve prefers the persisted encrypted DuckDB store when the secure backend is available
(D1) and refreshes it EPOCH-GATED INCREMENTALLY (D2/D3), holding a SINGLE connection (the
ATTACH store rejects a second in-process handle). Encryption itself needs the per-OS httpfs
binary (CI/operator-only), but the serve CONCURRENCY / INCREMENTAL / DURABILITY logic is
crypto-independent, so it is proven here with an UNENCRYPTED file-backed DuckDB standing in
for the persisted store. Values must match the live query; the mode is disclosed in `basis`.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import columnar, rollup_serve
from src.analytics import queries as q
from src.analytics.corpus_epoch import get_corpus_epoch
from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.models import Article, Base, Source

pytestmark = pytest.mark.skipif(
    not columnar.duckdb_available(), reason="duckdb not installed (optional [columnar] extra)"
)

_WIDE = 100_000


def _seed(s, texts, start_day=1):
    ex = BaselineExtractor()
    n = s.query(Article).count()
    for i, t in enumerate(texts):
        a = Article(
            url=f"https://x.test/{n + i}", canonical_url=f"https://x.test/{n + i}", source_id=1,
            title="T", content=t, hash=f"h{n + i}", country="fr", language="en",
            published_at=datetime(2024, 3, start_day + i, tzinfo=UTC), created_at=datetime.now(UTC),
        )
        s.add(a)
        s.commit()
        index_article(s, a, extractor=ex)


@pytest.fixture()
def session():
    e = create_engine("sqlite:///:memory:", future=True,
                      connect_args={"check_same_thread": False})
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    _seed(s, [
        "The federal budget dominated the Senate; sanctions on Russia loomed.",
        "Russia and sanctions returned as the federal budget debate widened.",
        "Climate policy and drought reached the Senate committee on the budget.",
        "A pandemic vaccine plan and the federal budget met resistance.",
    ])
    return s


@pytest.fixture(autouse=True)
def _reset_serve_state():
    def _clear():
        if rollup_serve._BUILD_LOCK.acquire(timeout=30):
            rollup_serve._BUILD_LOCK.release()
        con = rollup_serve._STATE.get("con")
        if con is not None:
            try:
                con.close()
            except Exception:  # noqa: BLE001
                pass
        rollup_serve._STATE.update(
            {"con": None, "built_at": 0.0, "rows": 0, "bind": None, "persisted": False,
             "token": None, "pending": False, "checked_at": 0.0}
        )

    _clear()
    yield
    _clear()


def _persisted_stub(store_path):
    """A columnar.connect stand-in: passphrase -> a file-backed (UNENCRYPTED) duckdb standing
    in for the persisted store; no passphrase -> in-memory. Encryption is CI/operator-only; the
    serve concurrency/incremental/durability logic under test is crypto-independent."""
    import duckdb

    def _connect(passphrase=None):
        if passphrase:
            return duckdb.connect(str(store_path))
        return duckdb.connect(":memory:")

    return _connect


def _canon(res):
    return sorted((t["normalized"], t["mentions"], t["articles"]) for t in res["terms"])


# ----------------------------- the mode DECISION --------------------------------------- #

def test_persisted_serve_active_gates_on_secure_backend_and_passphrase(monkeypatch):
    # today: secure backend absent -> in-memory serve (byte-unchanged behaviour)
    monkeypatch.setattr(columnar, "secure_crypto_available", lambda: False)
    monkeypatch.setattr(rollup_serve, "_persist_passphrase", lambda: "pw")
    assert rollup_serve._persisted_serve_active() is False
    # both present -> persisted
    monkeypatch.setattr(columnar, "secure_crypto_available", lambda: True)
    assert rollup_serve._persisted_serve_active() is True
    # no passphrase -> in-memory even with the backend
    monkeypatch.setattr(rollup_serve, "_persist_passphrase", lambda: None)
    assert rollup_serve._persisted_serve_active() is False


def test_persist_env_override_forces_in_memory(monkeypatch):
    monkeypatch.setenv("OO_COLUMNAR_SERVE_PERSIST", "0")
    monkeypatch.setattr("src.database.connect.get_passphrase", lambda: "pw")
    assert rollup_serve._persist_passphrase() is None  # forced off
    monkeypatch.setattr(columnar, "secure_crypto_available", lambda: True)
    assert rollup_serve._persisted_serve_active() is False


def test_dispatcher_routes_to_persisted_when_active(monkeypatch):
    calls = {"persisted": 0, "memory": 0}
    monkeypatch.setattr(rollup_serve, "_refresh_persisted_build",
                        lambda: calls.__setitem__("persisted", calls["persisted"] + 1))
    monkeypatch.setattr(rollup_serve, "_build_inmemory_and_swap",
                        lambda: calls.__setitem__("memory", calls["memory"] + 1))
    for active, key in [(True, "persisted"), (False, "memory")]:
        monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda a=active: a)
        rollup_serve._BUILD_LOCK.acquire()  # the dispatcher releases it in finally
        rollup_serve._build_and_swap()
        assert calls[key] >= 1


# ----------------------------- serve + incremental + durability ------------------------ #

def test_persisted_serve_matches_live_and_discloses_the_store(session, tmp_path, monkeypatch):
    store = tmp_path / "analytics.duckdb"
    monkeypatch.setattr(columnar, "connect", _persisted_stub(store))
    live = q.top_terms(session, days=_WIDE, group=False, limit=100)

    con = columnar.connect(passphrase="pw")  # the persisted stub
    columnar.refresh_keyword_daily(con, session, corpus_epoch=get_corpus_epoch(session))
    rollup_serve._STATE.update(
        {"con": con, "persisted": True, "bind": session.get_bind(), "built_at": time.time()}
    )
    monkeypatch.setenv("OO_COLUMNAR_SERVE", "1")

    served = q.top_terms(session, days=_WIDE, group=False, limit=100)
    assert served["basis"]["source"] == "columnar-rollup"
    assert served["basis"]["store"] == "persisted"
    assert "persisted encrypted" in served["basis"]["note"]
    assert _canon(served) == _canon(live)
    assert rollup_serve.status()["store"] == "persisted"


def test_persisted_refresh_is_incremental_and_stays_correct(session, tmp_path, monkeypatch):
    store = tmp_path / "analytics.duckdb"
    monkeypatch.setattr(columnar, "connect", _persisted_stub(store))
    full_builds = {"n": 0}
    _orig_full = columnar.build_keyword_daily
    monkeypatch.setattr(
        columnar, "build_keyword_daily",
        lambda *a, **k: (full_builds.__setitem__("n", full_builds["n"] + 1), _orig_full(*a, **k))[1],
    )

    con = columnar.connect(passphrase="pw")
    epoch = get_corpus_epoch(session)
    columnar.refresh_keyword_daily(con, session, corpus_epoch=epoch)  # first -> FULL
    assert full_builds["n"] == 1
    rollup_serve._STATE.update(
        {"con": con, "persisted": True, "bind": session.get_bind(), "built_at": time.time()}
    )

    # append new articles (advance the mention tail; epoch unchanged -> INCREMENTAL)
    _seed(session, ["The federal budget faced a new drought and pandemic warning."], start_day=20)
    res = columnar.refresh_keyword_daily(con, session, corpus_epoch=get_corpus_epoch(session))
    assert res["mode"] == "incremental"
    assert full_builds["n"] == 1, "an incremental refresh must NOT full-rebuild"

    monkeypatch.setenv("OO_COLUMNAR_SERVE", "1")
    live = q.top_terms(session, days=_WIDE, group=False, limit=100)  # over the expanded corpus
    served = q.top_terms(session, days=_WIDE, group=False, limit=100)
    assert _canon(served) == _canon(live), "the incrementally-merged rollup matches live"


def test_persisted_store_survives_a_restart_without_a_full_rebuild(session, tmp_path, monkeypatch):
    store = tmp_path / "analytics.duckdb"
    monkeypatch.setattr(columnar, "connect", _persisted_stub(store))
    full_builds = {"n": 0}
    _orig_full = columnar.build_keyword_daily
    monkeypatch.setattr(
        columnar, "build_keyword_daily",
        lambda *a, **k: (full_builds.__setitem__("n", full_builds["n"] + 1), _orig_full(*a, **k))[1],
    )

    # process 1: first build persists keyword_daily + built_epoch + watermark to the file
    con1 = columnar.connect(passphrase="pw")
    columnar.refresh_keyword_daily(con1, session, corpus_epoch=get_corpus_epoch(session))
    rows1 = con1.execute("SELECT COUNT(*) FROM keyword_daily").fetchone()[0]
    con1.close()  # simulate process exit
    assert full_builds["n"] == 1 and rows1 > 0

    # process 2: reopen the SAME file -> the rollup is already there, epoch unchanged ->
    # INCREMENTAL (no per-boot full rebuild = the D1 durability win)
    con2 = columnar.connect(passphrase="pw")
    res = columnar.refresh_keyword_daily(con2, session, corpus_epoch=get_corpus_epoch(session))
    assert res["mode"] == "incremental", "a restart reopens the persisted store, never a full rebuild"
    assert full_builds["n"] == 1, "the reopen must not full-rebuild"
    assert con2.execute("SELECT COUNT(*) FROM keyword_daily").fetchone()[0] == rows1
    con2.close()


def test_basis_store_field_defaults_to_memory():
    b = rollup_serve.basis(7)
    assert b["store"] == "memory"
    assert "in-memory" in b["note"]
