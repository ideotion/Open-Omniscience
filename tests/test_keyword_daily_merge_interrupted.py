"""A merge of the mention tail that stops half-way is followed by a full rebuild, never by a second addition (the double-count window).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``refresh_keyword_daily``'s incremental merge is an UPDATE of the days the tail shares with the store, an INSERT of the days it adds, the
``keyword_meta`` upsert and, last, the ``last_mention_id`` watermark. Each statement autocommits, so a failure after the UPDATE and before the
watermark leaves the tail's counts ADDED while the watermark still points before it, and the next refresh at an equal epoch adds the same tail
again. The merge now voids ``built_epoch`` before its first write and restores it after the watermark; whatever stops it in between leaves the
store voided, so the next refresh is a full rebuild.

THE FAULTS ARE INDUCED, NOT OBSERVED, and each test names its cause. The proxy raises on one chosen statement of the real refresh over a real
in-memory store; what raised in the field would be a DuckDB error (out of memory or disk), MemoryError, a SQLAlchemy error reading the
keyword rows, or a kill, and those causes are inferred, not reproduced. What the tests prove is the property that does not depend on the cause:
after a stop at that statement, the partial merge IS in the store (the premise, asserted where a statement changes counts; the kill-at-watermark test asserts instead that the watermark did not advance) and the next refresh does not add it again.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from src.analytics import columnar
from src.analytics.extract import BaselineExtractor
from src.database.models import Base, Source
from tests.test_keyword_daily_refresh import _fresh_full, _index

pytestmark = pytest.mark.skipif(
    not columnar.duckdb_available(), reason="duckdb not installed (optional [columnar] extra)"
)

BUILT = "keyword_daily.built_epoch"
WATERMARK = "keyword_daily.last_mention_id"


@pytest.fixture()
def ctx():
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    yield s, BaselineExtractor()
    s.close()


class _Faulty:
    """A store handle that raises ``exc`` ONCE on the first statement ``when(sql, params)`` accepts and passes everything else through."""

    def __init__(self, con, when, exc):
        self._con, self._when, self._exc = con, when, exc
        self.fired = False
        self.seen: list[str] = []  # every statement that reached the store, for "no UPDATE ran"

    def execute(self, sql, params=None):
        if not self.fired and self._when(str(sql), params):
            self.fired = True
            raise self._exc
        self.seen.append(str(sql).lstrip())
        return self._con.execute(sql) if params is None else self._con.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._con, name)


def _on_the_insert(sql, _params):
    return sql.lstrip().startswith("INSERT INTO keyword_daily SELECT")


def _on_the_watermark(sql, params):
    return sql.lstrip().startswith("INSERT INTO oo_meta") and bool(params) and params[0] == WATERMARK


def _on_the_voiding_write(sql, params):
    return sql.lstrip().startswith("INSERT INTO oo_meta") and bool(params) and params[0] == BUILT and params[1] == str(columnar.VOIDED_BUILT_EPOCH)


def _world(ctx):
    """A built store plus a tail that shares a day with it (so the UPDATE changes counts) and adds a day (so the INSERT has work)."""
    session, ex = ctx
    _index(session, ex, "2024-03-01", "The federal budget gripped the Senate chamber.")
    _index(session, ex, "2024-03-02", "Senate leaders argued the federal budget tonight.")
    con = columnar.connect(passphrase=None)
    assert columnar.refresh_keyword_daily(con, session, corpus_epoch=1)["mode"] == "full"
    _index(session, ex, "2024-03-02", "The federal budget and the Senate again.")
    _index(session, ex, "2024-03-20", "Climate policy and drought dominated the summit.")
    return session, con


def _counts(con):
    return columnar.windowed_term_counts(con)


def test_an_uninterrupted_merge_leaves_the_epoch_as_it_found_it_and_the_next_refresh_incremental(ctx):
    session, con = _world(ctx)
    assert columnar.refresh_keyword_daily(con, session, corpus_epoch=1)["mode"] == "incremental"
    assert columnar._get_meta(con, BUILT) == "1"
    assert _counts(con) == _counts(_fresh_full(session))
    assert columnar.refresh_keyword_daily(con, session, corpus_epoch=1)["mode"] == "incremental"


@pytest.mark.parametrize(
    "exc",
    [pytest.param(RuntimeError("injected: the INSERT statement raised"), id="statement-error"), pytest.param(MemoryError("injected"), id="memory-error")],
)
def test_a_failure_on_the_insert_after_the_update_is_followed_by_a_full_rebuild_not_a_second_addition(ctx, exc):
    session, con = _world(ctx)
    before = _counts(con)
    faulty = _Faulty(con, _on_the_insert, exc)
    with pytest.raises(type(exc)):
        columnar.refresh_keyword_daily(faulty, session, corpus_epoch=1)
    assert faulty.fired

    assert _counts(con) != before, "premise: the UPDATE of the shared day was applied before the failure"
    assert columnar._get_meta(con, WATERMARK) is not None and columnar._get_meta(con, BUILT) == str(columnar.VOIDED_BUILT_EPOCH)

    res = columnar.refresh_keyword_daily(con, session, corpus_epoch=1)
    assert res["mode"] == "full", "the next refresh merged the same tail again"
    assert _counts(con) == _counts(_fresh_full(session))


def test_a_sqlalchemy_error_in_the_keyword_meta_upsert_is_followed_by_a_full_rebuild(ctx, monkeypatch):
    session, con = _world(ctx)
    before = _counts(con)
    real = columnar._upsert_keyword_meta
    calls = {"n": 0}

    def broken(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OperationalError("SELECT keyword rows", {}, Exception("injected: database is locked"))
        return real(*args, **kwargs)

    monkeypatch.setattr(columnar, "_upsert_keyword_meta", broken)
    with pytest.raises(OperationalError):
        columnar.refresh_keyword_daily(con, session, corpus_epoch=1)

    assert _counts(con) != before, "premise: the UPDATE and the INSERT were applied before the failure"
    assert columnar._get_meta(con, BUILT) == str(columnar.VOIDED_BUILT_EPOCH)
    assert columnar.refresh_keyword_daily(con, session, corpus_epoch=1)["mode"] == "full"
    assert _counts(con) == _counts(_fresh_full(session))


def test_a_stop_before_the_watermark_moves_is_followed_by_a_full_rebuild_even_for_a_kill(ctx):
    """KeyboardInterrupt stands in for a kill: nothing after it runs, so only what was written BEFORE it can save the next refresh."""
    session, con = _world(ctx)
    old_watermark = columnar._get_meta(con, WATERMARK)
    faulty = _Faulty(con, _on_the_watermark, KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        columnar.refresh_keyword_daily(faulty, session, corpus_epoch=1)

    # ``_set_meta`` is a DELETE then an INSERT: the stop lands between them, so the watermark is ABSENT (which the next refresh reads as 0,
    # a re-merge of the whole corpus) rather than the old value. Either way it did not advance.
    assert columnar._get_meta(con, WATERMARK) in (None, old_watermark), "premise: the watermark had not moved"
    assert columnar._get_meta(con, BUILT) == str(columnar.VOIDED_BUILT_EPOCH)
    assert columnar.refresh_keyword_daily(con, session, corpus_epoch=1)["mode"] == "full"
    assert _counts(con) == _counts(_fresh_full(session))


def test_a_failure_before_the_first_write_leaves_the_epoch_alone(ctx, monkeypatch):
    # the tail aggregate is built before the merge writes: a failure there changed nothing, so the store keeps vouching for itself
    session, con = _world(ctx)
    faulty = _Faulty(con, lambda sql, _p: "keyword_daily_tail" in sql and sql.lstrip().startswith("CREATE"), RuntimeError("injected"))
    with pytest.raises(RuntimeError):
        columnar.refresh_keyword_daily(faulty, session, corpus_epoch=1)
    assert columnar._get_meta(con, BUILT) == "1"
    assert columnar.refresh_keyword_daily(con, session, corpus_epoch=1)["mode"] == "incremental"
    assert _counts(con) == _counts(_fresh_full(session))


def test_a_failure_of_the_voiding_write_itself_stops_the_merge_before_its_first_write(ctx):
    """Fail closed: if the store cannot be marked not-vouched-for, nothing is merged. Induced at the voiding write's INSERT (its DELETE has
    run, so the key is absent -- which the next refresh reads as no prior build)."""
    session, con = _world(ctx)
    before = _counts(con)
    faulty = _Faulty(con, _on_the_voiding_write, RuntimeError("injected: the voiding write raised"))
    with pytest.raises(RuntimeError):
        columnar.refresh_keyword_daily(faulty, session, corpus_epoch=1)
    assert faulty.fired
    assert not any(s.startswith(("UPDATE keyword_daily", "INSERT INTO keyword_daily SELECT")) for s in faulty.seen), "a merge statement ran"
    assert _counts(con) == before
    assert columnar._get_meta(con, BUILT) is None
    assert columnar.refresh_keyword_daily(con, session, corpus_epoch=1)["mode"] == "full"
    assert _counts(con) == _counts(_fresh_full(session))


def test_the_voided_epoch_is_no_corpus_epoch_and_the_reader_refuses_it_by_name(ctx):
    session, con = _world(ctx)
    assert columnar.VOIDED_BUILT_EPOCH < 0, "corpus epochs start at 0 and only grow, so a negative value can never equal one"
    columnar._set_meta(con, BUILT, columnar.VOIDED_BUILT_EPOCH)
    # even a (hypothetical) caller epoch equal to the marker is refused: the reader compares against the constant
    assert columnar.refresh_keyword_daily(con, session, corpus_epoch=columnar.VOIDED_BUILT_EPOCH)["mode"] == "full"


class _FaultySession:
    """A session whose ``execute`` raises ``exc`` once, on the ``nth`` statement containing ``needle``; everything else passes through."""

    def __init__(self, session, needle, nth, exc):
        self._s, self._needle, self._nth, self._exc = session, needle, nth, exc
        self._seen = 0
        self.fired = False

    def execute(self, stmt, *a, **k):
        if self._needle in str(stmt):
            self._seen += 1
            if self._seen == self._nth and not self.fired:
                self.fired = True
                raise self._exc
        return self._s.execute(stmt, *a, **k)

    def __getattr__(self, name):
        return getattr(self._s, name)


def test_a_full_rebuild_that_stops_after_its_swap_in_is_not_followed_by_an_incremental_refresh(ctx):
    """THE OLDER GAP, found by the read of the incremental fix. The full branch is entered at an EQUAL epoch only when a table is missing
    (here ``keyword_meta`` is dropped: the store of a build from before that table existed). The build swaps the new ``keyword_daily`` in,
    fills ``keyword_meta`` and only then moves the watermark; the stop is induced in the keyword_meta fill, after its first batch. Cause
    induced: the session raising ``OperationalError`` on the second keywords SELECT; in the field a DuckDB error, MemoryError or a kill
    there is inferred."""
    session, con = _world(ctx)
    con.execute("DROP TABLE keyword_meta")
    old_watermark = columnar._get_meta(con, WATERMARK)
    faulty = _FaultySession(session, "FROM keywords WHERE", 2, OperationalError("SELECT keywords", {}, Exception("injected: database is locked")))
    with pytest.raises(OperationalError):
        columnar.refresh_keyword_daily(con, faulty, corpus_epoch=1, batch_size=2)
    assert faulty.fired

    fresh = _counts(_fresh_full(session))
    assert _counts(con) == fresh, "premise: the new keyword_daily was swapped in before the stop"
    assert columnar._table_present(con, "keyword_meta"), "premise: keyword_meta exists, part-filled, so every table is present again"
    assert columnar._get_meta(con, WATERMARK) == old_watermark, "premise: the watermark was not moved"

    res = columnar.refresh_keyword_daily(con, session, corpus_epoch=1)
    assert res["mode"] == "full", "an incremental refresh merged a tail the swapped-in table already holds"
    assert _counts(con) == fresh
    assert con.execute("SELECT COUNT(*) FROM keyword_meta").fetchone()[0] > 2, "keyword_meta was left part-filled"
