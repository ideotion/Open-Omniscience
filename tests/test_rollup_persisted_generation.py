"""The persisted rollup refresh compares the library generation at its boundaries (the stated limit of #1551, R303).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``refresh_keyword_daily`` is the persisted store's maintainer: a full build on an epoch change, otherwise a merge of the mention tail. It took no
hook, so a corpus swap during it was not compared, and a tail read from the NEW file could be merged into a store built from the old one. It now
takes the build's ``on_batch(stage, rows_done)`` hook: after every batch of the tail (``"mentions"``) and once before the merge begins
(``"aggregate"``). The merge is not transactional (an UPDATE and an INSERT, then the watermark), so the stop is made BEFORE it: a stop after the
first statement and before the watermark moves would be added twice by the next refresh. These tests use a REAL swap through ``swap_window`` on a
guarded engine and the real refresh over an in-memory store.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import columnar, rollup_serve
from src.analytics.extract import BaselineExtractor
from src.database import library_generation as gen
from src.database.models import Base, Source
from tests.test_keyword_daily_refresh import _fresh_full, _index
from tests.test_rollup_generation_check import _World

pytestmark = pytest.mark.skipif(
    not columnar.duckdb_available(), reason="duckdb not installed (optional [columnar] extra)"
)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    # a real swap moves the process-wide generation: put it back, so the tests after this file meet the generation they began with
    for name in ("_GENERATION", "_VALID", "_WINDOW_STAMP", "_DISK_CHANGED"):
        monkeypatch.setattr(gen, name, getattr(gen, name))


@pytest.fixture()
def world(tmp_path):
    w = _World(tmp_path)
    yield w
    w.close()


@pytest.fixture()
def ctx():
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    yield s, BaselineExtractor()
    s.close()


def _counts(con):
    return columnar.windowed_term_counts(con)


def _tables(con) -> set[str]:
    return {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}


def _built(ctx):
    session, ex = ctx
    _index(session, ex, "2024-03-01", "The federal budget gripped the Senate chamber.")
    _index(session, ex, "2024-03-02", "Senate leaders argued the federal budget tonight.")
    con = columnar.connect(passphrase=None)
    assert columnar.refresh_keyword_daily(con, session, corpus_epoch=1)["mode"] == "full"
    _index(session, ex, "2024-03-03", "The budget debate reached the Senate committee.")
    _index(session, ex, "2024-03-20", "Climate policy and drought dominated the summit.")
    return session, con


@pytest.mark.parametrize("swap_at", ["mentions", "aggregate"])
def test_a_swap_during_the_incremental_tail_stops_the_refresh_before_anything_is_merged(ctx, world, swap_at):
    session, con = _built(ctx)
    before = _counts(con)
    marker = columnar._get_meta(con, "keyword_daily.last_mention_id")
    stamp = gen.current()
    calls: list[str] = []

    def hook(stage: str, rows: int) -> None:
        calls.append(stage)
        if stage == swap_at and calls.count(stage) == 1:
            world.swap()  # the real swap lands just before this boundary's comparison
        rollup_serve._require_library_unchanged(stamp)

    with pytest.raises(gen.StaleLibraryError):
        columnar.refresh_keyword_daily(con, session, corpus_epoch=1, on_batch=hook)

    assert _counts(con) == before, "the stopped refresh merged part of the tail"
    assert columnar._get_meta(con, "keyword_daily.last_mention_id") == marker, "the watermark moved"
    assert "keyword_daily_stage" not in _tables(con), "the stage table of a stopped refresh was left behind"

    # a later refresh (no swap in its way) merges the tail ONCE: equal to a full rebuild, nothing added twice
    columnar.refresh_keyword_daily(con, session, corpus_epoch=1)
    assert _counts(con) == _counts(_fresh_full(session))


def test_no_swap_means_the_hook_changes_nothing_and_sees_each_boundary(ctx, world):
    session, con = _built(ctx)
    stamp = gen.current()
    seen: list[tuple[str, int]] = []

    def hook(stage: str, rows: int) -> None:
        seen.append((stage, rows))
        rollup_serve._require_library_unchanged(stamp)

    res = columnar.refresh_keyword_daily(con, session, corpus_epoch=1, on_batch=hook)
    assert res["mode"] == "incremental" and res["merged_days"] > 0
    assert [s for s, _ in seen] == ["mentions", "aggregate"] and seen[-1][1] > 0
    assert _counts(con) == _counts(_fresh_full(session))


def test_the_full_path_passes_the_hook_to_the_build(ctx, world):
    session, ex = ctx
    _index(session, ex, "2024-03-01", "The federal budget gripped the Senate chamber.")
    con = columnar.connect(passphrase=None)
    stamp = gen.current()
    world.swap()
    with pytest.raises(gen.StaleLibraryError):
        columnar.refresh_keyword_daily(
            con, session, corpus_epoch=1, on_batch=lambda _s, _r: rollup_serve._require_library_unchanged(stamp)
        )
    assert columnar._get_meta(con, "keyword_daily.built_epoch") is None, "a refused full build was recorded as built"


def _persisted(monkeypatch, refresh):
    """``_refresh_persisted_build`` with the store, the session and the epoch stubbed; ``refresh`` stands in for the refresh."""
    from contextlib import contextmanager

    from src.analytics import corpus_epoch, serve_gate
    from src.database import session as app_session

    class _Con:
        def execute(self, *_a, **_k):
            return self

        def fetchone(self):
            return (3,)

        def close(self):
            pass

    class _S:
        def get_bind(self):
            return "bind"

    @contextmanager
    def scope():
        yield _S()

    con = _Con()
    state = dict(rollup_serve._STATE, con=con, persisted=True, token=None, rows=None, built_at=None, bind=None, pending=True)
    monkeypatch.setattr(rollup_serve, "_STATE", state)
    monkeypatch.setattr(columnar, "refresh_keyword_daily", refresh)
    monkeypatch.setattr(serve_gate, "change_token", lambda _s: (7, 1000))
    monkeypatch.setattr(corpus_epoch, "get_corpus_epoch", lambda _s: 1)
    monkeypatch.setattr(app_session, "session_scope", scope)
    return state


@pytest.mark.parametrize("where", ["in-the-hook", "after-the-refresh"])
def test_the_persisted_dispatcher_path_stops_and_records_nothing_when_the_swap_lands(monkeypatch, world, where):
    def refresh(con, s, *, corpus_epoch, on_batch=None, **_k):
        if where == "in-the-hook":
            on_batch("mentions", 10)  # before the swap: passes
            world.swap()
            on_batch("mentions", 20)
        else:
            world.swap()  # lands after the last boundary the refresh calls the hook at
        return {"mode": "incremental"}

    state = _persisted(monkeypatch, refresh)
    with pytest.raises(gen.StaleLibraryError):
        rollup_serve._refresh_persisted_build()
    assert state["token"] is None and state["rows"] is None and state["pending"] is True, "a store no corpus produced was recorded as serving"


def test_the_persisted_dispatcher_path_without_a_swap_records_the_store(monkeypatch, world):
    def refresh(con, s, *, corpus_epoch, on_batch=None, **_k):
        on_batch("mentions", 10)
        on_batch("aggregate", 10)
        return {"mode": "incremental"}

    state = _persisted(monkeypatch, refresh)
    assert rollup_serve._refresh_persisted_build() is True
    assert state["token"] == (7, 1000) and state["pending"] is False
