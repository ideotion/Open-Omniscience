"""Connection first, then the gate, for a SESSION that writes under ``write_lock()`` (the read of the final head, finding M2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``tests/test_gate_connection_order.py`` scans ``src/`` for the order and proves the scan on snippets; this file drives the REAL sites. A session
that has committed (or never read) holds no pooled connection, so ``with write_lock(): session.get(...)`` took the gate and THEN waited for the
pool: with the pool's connections out, which is where a queue of writers each holding one while it waits for the gate leaves it, the gate holder
stood for the pool's 30 s timeout with the whole write queue behind it. Every site below is called on a FRESH session, and the pool must have a
connection out of it when the gate is first asked for (``GateProbe``: not a re-entry, on any thread).

Also here: ``prune_orphan_keywords`` held the gate across ALL of a slice's delete chunks, and each chunk's commit gave the connection back, so
every chunk after the first took the pool again under the gate. It holds the gate per chunk now, connection first, and each chunk asks again,
under the gate, whether a keyword it was told to delete has gained a mention since (a writer can run between two chunks now).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event, insert
from sqlalchemy.pool import QueuePool

from src.database import writer
from src.database.models import (
    Article,
    Base,
    DerivedMeta,
    Keyword,
    KeywordMention,
    KeywordTag,
    Source,
)
from tests.test_gate_connection_order import GateProbe, _factory


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A pooled engine (two connections, so a seeding session and a site can both run), the writer's own session hooks, empty tables."""
    monkeypatch.setenv("OO_WRITE_GATE_WATCHDOG", "0")
    eng = create_engine(f"sqlite:///{tmp_path / 'sessions.db'}", poolclass=QueuePool, pool_size=2, max_overflow=0, pool_timeout=5)

    @event.listens_for(eng, "connect")
    def _wal(dbapi_conn, _rec):  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    Base.metadata.create_all(eng)
    factory = _factory(eng)
    yield eng, factory
    eng.dispose()


def _seed(factory, *rows):
    s = factory()
    try:
        s.add_all(rows)
        s.commit()
    finally:
        s.close()


def _keyword_world(factory, n_keywords=3, with_mentions=()):
    """``n_keywords`` keywords (ids 1..n), a source and an article; the ids in ``with_mentions`` have one mention each."""
    _seed(factory, Source(name="s", domain="s.example"))
    s = factory()
    try:
        s.add(Article(title="a", url="https://s.example/1", canonical_url="https://s.example/1", source_id=1, hash="h1", content="body", language="en"))
        for i in range(1, n_keywords + 1):
            s.add(Keyword(term=f"k{i}", normalized_term=f"k{i}", language="en"))
        s.commit()
        if with_mentions:
            s.execute(insert(KeywordMention), [{"keyword_id": k, "article_id": 1, "count": 1} for k in with_mentions])
            s.commit()
    finally:
        s.close()


# --------------------------------------------------------------------------- #
#  each site, on a fresh session: the pool has a connection out when the gate is first asked for
# --------------------------------------------------------------------------- #
def _marker(factory, key):
    _seed(factory, DerivedMeta(key=key, value="x"))


def _bulk_open(eng, factory):
    from src.analytics import bulk_build

    bulk_build.open_state(factory(), ["ix_a"])


def _bulk_close(eng, factory):
    from src.analytics import bulk_build

    _marker(factory, bulk_build.BULK_BUILD_KEY)
    assert bulk_build.close_state(factory()) is True


def _deferral_open(eng, factory):
    from src.analytics import counter_deferral

    counter_deferral.open_deferral(factory())


def _deferral_close(eng, factory):
    from src.analytics import counter_deferral

    _marker(factory, counter_deferral.COUNTER_DEFERRAL_KEY)
    assert counter_deferral.close_deferral(factory()) is True


def _epoch(eng, factory):
    from src.analytics.corpus_epoch import bump_corpus_epoch

    assert bump_corpus_epoch(factory(), reason="probe") == 1


def _keyword_updates(eng, factory):
    from src.analytics import store

    _keyword_world(factory, 1)
    store._write_keyword_updates(factory(), [{"id": 1, "language": "fr"}])


def _keyword_languages(eng, factory):
    from src.analytics import store

    _keyword_world(factory, 1)
    store._write_keyword_languages(factory(), [{"id": 1, "language": "fr"}])


def _backfill(eng, factory):
    from src.analytics import store

    _keyword_world(factory, 2, with_mentions=(1,))
    assert store.backfill_keyword_counters(factory())["keywords"] == 2


def _reconcile_keywords(eng, factory):
    from src.analytics import store

    _keyword_world(factory, 2, with_mentions=(1,))
    assert store.reconcile_keyword_counters(factory())["keywords"] == 2


def _reconcile_sources(eng, factory):
    from src.analytics import store

    _keyword_world(factory, 1)
    store.reconcile_source_counters(factory())


def _prune(eng, factory):
    from src.analytics import store

    _keyword_world(factory, 2, with_mentions=(1,))
    assert store.prune_orphan_keywords(factory())["pruned"] == 1


def _fts_optimize(eng, factory):
    from src.database import fts

    fts.optimize_after_bulk(factory())


def _source_topics_fresh(eng, factory, monkeypatch=None):
    from src.analytics import source_topics

    _seed(factory, Source(name="s", domain="s.example"))
    real = source_topics.source_topic_candidates
    source_topics.source_topic_candidates = lambda *a, **k: {"candidates": [{"id": 1, "topics": ["x"]}]}
    try:
        assert source_topics.apply_source_topics(factory())["sources_updated"] == 1
    finally:
        source_topics.source_topic_candidates = real


def _source_topics_shared(eng, factory):
    from src.analytics import source_topics

    s = factory()
    s.begin()  # in a transaction, with no connection out: the shared-session branch
    assert s.in_transaction()
    source_topics._apply_source_topics_on_a_shared_session(s, min_articles=1, top_n=3)


SITES = {
    "bulk_build.open_state": _bulk_open,
    "bulk_build.close_state": _bulk_close,
    "counter_deferral.open_deferral": _deferral_open,
    "counter_deferral.close_deferral": _deferral_close,
    "corpus_epoch.bump_corpus_epoch": _epoch,
    "store._write_keyword_updates": _keyword_updates,
    "store._write_keyword_languages": _keyword_languages,
    "store.backfill_keyword_counters": _backfill,
    "store.reconcile_keyword_counters": _reconcile_keywords,
    "store.reconcile_source_counters": _reconcile_sources,
    "store.prune_orphan_keywords": _prune,
    "fts.optimize_after_bulk": _fts_optimize,
    "source_topics.apply_source_topics": _source_topics_fresh,
    "source_topics._apply_source_topics_on_a_shared_session": _source_topics_shared,
}


@pytest.mark.parametrize("site", sorted(SITES))
def test_a_fresh_session_has_its_connection_out_when_the_gate_is_first_asked_for(world, monkeypatch, site):
    eng, factory = world
    # One keyword per slice: the sweeps commit between slices, and it is the SECOND slice that finds the session without a connection.
    monkeypatch.setattr("src.analytics.store._RECONCILE_SCAN_CHUNK", 1)
    probe = GateProbe(monkeypatch, eng)
    SITES[site](eng, factory)
    assert probe.out_at_first_ask, f"{site} never asked for the gate: the probe did not reach it"
    # EVERY first ask, not the first one: a site seeds its rows through a session of its own (a connection out, by the hooks), and that ask
    # must not stand in for the site's.
    assert min(probe.out_at_first_ask) >= 1, f"{site} asked for the gate with no connection out: the gate first, then the pool"


# --------------------------------------------------------------------------- #
#  the swallowing site: a pool timeout is a missed bump, and the gate was never taken for it
# --------------------------------------------------------------------------- #
def test_a_bump_that_cannot_get_a_connection_holds_no_gate_and_returns_the_unchanged_epoch(world, monkeypatch):
    from src.analytics.corpus_epoch import bump_corpus_epoch

    eng, factory = world
    eng.pool._timeout = 0.3
    hogs = [eng.connect(), eng.connect()]
    seen: list[bool] = []
    real = writer.write_gate.acquire

    def acquire(*args, **kwargs):
        seen.append(True)
        return real(*args, **kwargs)

    monkeypatch.setattr(writer.write_gate, "acquire", acquire)
    try:
        assert bump_corpus_epoch(factory(), reason="probe") == 0, "the bump is best-effort: it answers the unchanged epoch"
    finally:
        for h in hogs:
            h.close()
    assert not seen, "the gate was asked for although no connection could be had: the order is the gate first again"


# --------------------------------------------------------------------------- #
#  prune_orphan_keywords: the gate per chunk, connection first, and a keyword that gained a mention is kept
# --------------------------------------------------------------------------- #
def _spy_connection_first(monkeypatch, module="src.analytics.store"):
    """Records ``(holds the gate?)`` at each ``connection_first`` call made FROM ``module`` (the session hooks call it too, under the gate,
    and are not what is asked) and lets a test act at a chosen call."""
    import sys

    calls: list[bool] = []
    hooks: dict[int, object] = {}
    real = writer.connection_first

    def spy(session):
        if sys._getframe(1).f_globals.get("__name__") != module:
            return real(session)
        calls.append(writer.write_gate.held_by_current_thread())
        real(session)
        if len(calls) in hooks:
            hooks[len(calls)]()

    monkeypatch.setattr(writer, "connection_first", spy)
    return calls, hooks


def test_prune_takes_the_gate_once_per_chunk_and_the_connection_before_each(world, monkeypatch):
    from src.analytics import store

    eng, factory = world
    _keyword_world(factory, 5)  # five orphans
    calls, _ = _spy_connection_first(monkeypatch)
    assert store.prune_orphan_keywords(factory(), chunk=2)["pruned"] == 5
    assert len(calls) == 3, f"five ids in chunks of two are three holds: {calls}"
    assert calls == [False, False, False], "a connection was asked for under the gate: the order is the gate first, then the pool"


def test_a_keyword_that_gained_a_mention_between_two_chunks_is_kept_with_its_tags(world, monkeypatch):
    from src.analytics import store

    eng, factory = world
    _keyword_world(factory, 4)  # ids 1..4, all orphans; chunk=2 -> [1, 2] then [3, 4]
    _seed(factory, KeywordTag(keyword_id=3, axis="topic", tag="t", source="manual"))
    calls, hooks = _spy_connection_first(monkeypatch)

    def a_writer_indexes_an_article():
        w = factory()
        try:
            w.execute(insert(KeywordMention), [{"keyword_id": 3, "article_id": 1, "count": 1}])
            w.commit()
        finally:
            w.close()

    hooks[2] = a_writer_indexes_an_article  # after the first chunk is gone, before the second asks the gate
    result = store.prune_orphan_keywords(factory(), chunk=2)
    s = factory()
    try:
        left = sorted(k.id for k in s.query(Keyword))
        tags = s.query(KeywordTag).filter(KeywordTag.keyword_id == 3).count()
    finally:
        s.close()
    assert left == [3], f"keyword 3 has a mention now and must stay (1, 2 and 4 were garbage): {left}"
    assert tags == 1, "its tags stay with it"
    assert result["pruned"] == 3
