"""Row 416 (2026-11-24): the re-index keeps ONE worker pool for the whole drain instead of one per window.

What may not regress: a drain over several windows starts one pool, not one per window; the rows it writes are the same as
the serial computation's; the pool is replaced after its recycle count; a worker that dies mid-drain costs only speed -- the
broken pool is killed, that window is computed serially (the ruled fallback), the next window gets a fresh pool, nothing
committed is lost and nothing hangs; and the drain leaves no worker running when it returns.

These start real worker processes (the property is about process lifetime, which a fake pool cannot show), with small
windows so each test stays a few seconds.
"""

from __future__ import annotations

import os
import signal
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import src.analytics.reindex_parallel as RP
import src.analytics.store as S
from src.analytics.extract import BaselineExtractor
from src.database.models import Article, Base, Keyword, KeywordMention, Source
from tests._app_engine import app_sqlite_engine

_TEXTS = (
    "The WHO warned about drought and inflation in Paris on 5 March 2024. Climate policy shifted. ",
    "Le gouvernement a annoncé des réformes à Lyon le 3 avril 2024. Les syndicats ont protesté. ",
    "Die Regierung in Berlin kündigte am 2. Mai 2024 neue Wahlen an. Die Opposition reagierte. ",
)
_WINDOW = 20  # at least _MIN_PARALLEL_BATCH, so every window takes the pool


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.delenv("OO_REINDEX_PIPELINE", raising=False)
    monkeypatch.delenv("OO_REINDEX_WORKERS", raising=False)
    monkeypatch.delenv("OO_REINDEX_POOL_RECYCLE_ARTICLES", raising=False)
    monkeypatch.setattr(S, "_PRECOMPUTE_WINDOW", _WINDOW)
    engine = app_sqlite_engine(":memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    yield s
    s.close()
    engine.dispose()


def _seed(db, n: int) -> list[int]:
    langs = ("en", "fr", "de")
    for i in range(n):
        u = f"https://x.test/{i}"
        db.add(Article(url=u, canonical_url=u, source_id=1, title=f"T{i}", content=f"{_TEXTS[i % 3] * 3} Item {i}.",
                       hash=f"h{i}", country="fr", language=langs[i % 3],
                       published_at=datetime(2024, 3, 1, tzinfo=UTC), created_at=datetime.now(UTC)))
    db.commit()
    return [r[0] for r in db.execute(select(Article.id).order_by(Article.id))]


def _mentions(db) -> set[tuple]:
    rows = db.execute(
        select(KeywordMention.article_id, Keyword.normalized_term, Keyword.language, KeywordMention.count)
        .join(Keyword, Keyword.id == KeywordMention.keyword_id)
    )
    return {tuple(r) for r in rows}


def _serial_reference(n: int, monkeypatch) -> set[tuple]:
    """The same corpus drained with no pool at all: the reference every pooled drain must equal."""
    engine = app_sqlite_engine(":memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    ids = _seed(s, n)
    assert S.reindex_articles(s, extractor=BaselineExtractor(), article_ids=ids, workers=0) == {"reindexed": n, "failed": 0}
    out = _mentions(s)
    s.close()
    engine.dispose()
    return out


def _no_live_pool() -> bool:
    with RP._LIVE_POOLS_LOCK:
        return not RP._LIVE_POOLS


def test_a_drain_of_several_windows_starts_one_pool_and_writes_the_serial_rows(db, monkeypatch):
    ids = _seed(db, 3 * _WINDOW)
    stats: dict = {}
    out = S.reindex_articles(db, extractor=BaselineExtractor(), article_ids=ids, workers=2, stats=stats)
    assert out == {"reindexed": len(ids), "failed": 0}
    pre = stats["precompute"]
    assert pre["by_path"].get("pool") == 3, pre
    assert pre["pools_started"] == 1, "one pool for three windows, not one per window"
    assert pre["pools_recycled"] == 0 and pre["pools_broken"] == 0
    assert _mentions(db) == _serial_reference(len(ids), monkeypatch)
    assert _no_live_pool(), "the drain closed its pool"


def test_the_pool_is_replaced_after_its_recycle_count(db, monkeypatch):
    monkeypatch.setenv("OO_REINDEX_POOL_RECYCLE_ARTICLES", str(_WINDOW))
    ids = _seed(db, 3 * _WINDOW)
    stats: dict = {}
    S.reindex_articles(db, extractor=BaselineExtractor(), article_ids=ids, workers=2, stats=stats)
    pre = stats["precompute"]
    assert pre["pools_started"] == 3 and pre["pools_recycled"] == 2, pre
    assert _mentions(db) == _serial_reference(len(ids), monkeypatch)
    assert _no_live_pool()


def test_a_worker_killed_mid_drain_costs_speed_only(db, monkeypatch):
    """A worker dies while the drain runs (SIGKILL: no cleanup, the harshest case). The window that meets the broken pool is
    computed serially, a later window gets a fresh pool, every article is indexed, the rows equal the serial reference --
    so nothing already committed was lost or rewritten -- and the drain returns rather than hangs."""
    ids = _seed(db, 4 * _WINDOW)
    real_index = S.index_article
    state = {"applied": 0, "killed": None}

    def _index(session, art, **kw):
        state["applied"] += 1
        if state["applied"] == 1:
            # The first window's apply: window 2 is now computing ahead in the kept pool. Kill one of its workers.
            with RP._LIVE_POOLS_LOCK:
                pools = list(RP._LIVE_POOLS)
            procs = [p for pool in pools for p in (getattr(pool, "_processes", None) or {}).values() if p.is_alive()]
            if procs:
                state["killed"] = procs[0].pid
                os.kill(procs[0].pid, signal.SIGKILL)
        return real_index(session, art, **kw)

    monkeypatch.setattr(S, "index_article", _index)
    stats: dict = {}
    out = S.reindex_articles(db, extractor=BaselineExtractor(), article_ids=ids, workers=2, stats=stats)
    assert state["killed"] is not None, "a live worker was found to kill"
    assert out == {"reindexed": len(ids), "failed": 0}
    pre = stats["precompute"]
    assert pre["pools_broken"] >= 1, pre
    assert pre["pools_started"] >= 2, "a later window got a fresh pool"
    assert pre["by_path"].get("pool", 0) >= 1, "and used it"
    assert _mentions(db) == _serial_reference(len(ids), monkeypatch)
    assert _no_live_pool()


def test_a_stop_kills_the_kept_pool_rather_than_waiting_for_it(db, monkeypatch):
    ids = _seed(db, 3 * _WINDOW)
    polls = {"n": 0}

    def _stop() -> bool:
        polls["n"] += 1
        return polls["n"] > 1  # window 1 is applied; window 2, computed ahead, is discarded

    out = S.reindex_articles(db, extractor=BaselineExtractor(), article_ids=ids, workers=2, should_stop=_stop)
    assert out == {"reindexed": _WINDOW, "failed": 0}
    assert _no_live_pool(), "no worker outlives a stopped drain"


def test_a_one_window_caller_without_a_drain_pool_still_closes_its_own_pool():
    """precompute_batch without a DrainPool is unchanged: a pool for that window alone, shut down before it returns."""
    tasks = [(i, _TEXTS[i % 3] * 3, f"T{i}", "en", "en") for i in range(_WINDOW)]
    out = RP.precompute_batch(tasks, extractor=BaselineExtractor(), workers=2)
    assert set(out) == set(range(_WINDOW))
    assert _no_live_pool()


def test_a_kept_pool_is_reused_until_asked_for_fewer_workers():
    """Reused while it is no larger than asked for; a larger ask does not grow it (that waits for the recycle, so a memory
    reading that moves back and forth cannot restart the workers every window); a smaller ask replaces it."""
    dp = RP.DrainPool(recycle_after=None)
    try:
        a = dp.acquire(n_workers=2, extractor_name="baseline", gazetteer=None)
        assert dp.acquire(n_workers=2, extractor_name="baseline", gazetteer=None) is a
        assert dp.acquire(n_workers=3, extractor_name="baseline", gazetteer=None) is a, "never grown mid-drain"
        b = dp.acquire(n_workers=1, extractor_name="baseline", gazetteer=None)
        assert b is not a and dp.started == 2 and dp.shrunk == 1 and dp.recycled == 0
        assert a not in RP._LIVE_POOLS, "the replaced pool was closed and unregistered"
    finally:
        dp.close()
    assert _no_live_pool()


def test_the_worker_count_is_bounded_by_free_memory(monkeypatch):
    """Row 416's memory condition: a worker holds about _WORKER_MEMORY_MB for the whole drain, so the count is also bounded by
    (available - reserve) / per-worker, with the kept pool's own workers added back, and unchanged when memory cannot be read
    or the operator set OO_REINDEX_WORKERS."""
    import src.config.cgroup_memory as CG

    monkeypatch.delenv("OO_REINDEX_WORKERS", raising=False)
    per, reserve = RP._WORKER_MEMORY_MB, RP._MEMORY_RESERVE_MB

    def _avail(mb):
        monkeypatch.setattr(CG, "effective_memory", lambda *a, **k: {"available_mb": mb})

    _avail(reserve + 10 * per)
    assert RP.pool_workers(4) == 4, "plenty of memory: the core-based count"
    _avail(reserve + 2.5 * per)
    assert RP.pool_workers(4) == 2
    _avail(reserve + 1.5 * per)
    assert RP.pool_workers(4) == 1, "room for one worker is the serial path"

    class _Held:
        def held_mb(self):
            return 2 * per

    assert RP.pool_workers(4, drain_pool=_Held()) == 3, "the kept pool's own workers count as available to it"
    _avail(None)
    assert RP.pool_workers(4) == 4, "an unmeasured machine is not a small one"
    _avail(reserve)
    monkeypatch.setenv("OO_REINDEX_WORKERS", "3")
    assert RP.pool_workers(4) == 3, "the operator's explicit number is never second-guessed"


def test_memory_pressure_mid_drain_shrinks_then_closes_the_pool(db, monkeypatch):
    """Pressure that appears mid-drain: the next window gets a SMALLER pool; with no room for two workers, the window is
    computed serially and the kept pool is closed. Rows are the serial reference throughout."""
    import src.config.cgroup_memory as CG

    ids = _seed(db, 4 * _WINDOW)
    per, reserve = RP._WORKER_MEMORY_MB, RP._MEMORY_RESERVE_MB
    # Each window reads memory twice (the planning check and the window itself), and the held workers are added back:
    # report available so that the room left for NEW workers shrinks window by window.
    budget = {"n": 0}
    rooms = [3, 3, 3, 3, 2, 2, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1]

    def _eff(*a, **k):
        i = min(budget["n"], len(rooms) - 1)
        budget["n"] += 1
        return {"available_mb": reserve + rooms[i] * per + 1}

    monkeypatch.setattr(CG, "effective_memory", _eff)
    monkeypatch.setattr(RP.DrainPool, "held_mb", lambda self: 0.0)
    stats: dict = {}
    out = S.reindex_articles(db, extractor=BaselineExtractor(), article_ids=ids, workers=3, stats=stats)
    assert out == {"reindexed": len(ids), "failed": 0}
    pre = stats["precompute"]
    assert pre.get("memory_capped_windows", 0) >= 1, pre
    assert pre["by_path"].get("serial", 0) >= 1, "a window with no room for two workers ran here"
    assert _mentions(db) == _serial_reference(len(ids), monkeypatch)
    assert _no_live_pool(), "the pool was closed when memory ran out, and at the end"


def test_a_closed_drain_pool_starts_no_new_pool():
    """Security read of row 416, finding 1: a window computed ahead can reach acquire() after the drain's finally closed the
    pool (a stop, an exception in the apply). It must get PoolUnavailable, never a fresh pool that nobody would close."""
    dp = RP.DrainPool(recycle_after=None)
    dp.acquire(n_workers=2, extractor_name="baseline", gazetteer=None)
    dp.close(abandon=True)
    with pytest.raises(RP.PoolUnavailable):
        dp.acquire(n_workers=2, extractor_name="baseline", gazetteer=None)
    assert _no_live_pool()


def test_a_released_drain_pool_may_start_again():
    """Released for memory is not closed: a later window, with memory back, may start a pool again."""
    dp = RP.DrainPool(recycle_after=None)
    try:
        a = dp.acquire(n_workers=2, extractor_name="baseline", gazetteer=None)
        dp.release()
        assert a not in RP._LIVE_POOLS
        b = dp.acquire(n_workers=2, extractor_name="baseline", gazetteer=None)
        assert b is not a and dp.started == 2
    finally:
        dp.close()
    assert _no_live_pool()


def test_an_interrupt_while_the_ahead_window_is_taken_kills_it_rather_than_waits(db, monkeypatch):
    """Row 425: ``_ahead`` is emptied when a window's turn starts, before its articles are read and its result is waited for.
    A Ctrl-C in that gap used to leave the finally believing nothing was ahead, so it WAITED for the window computing in the
    kept pool (up to the pool timeout) before closing it. The window still in flight is now killed, as on any other stop."""
    ids = _seed(db, 3 * _WINDOW)
    real_query = db.query
    calls = {"n": 0}

    def _query(*entities, **kw):
        if entities and entities[0] is Article:
            calls["n"] += 1
            # 1: window 1 read; 2: window 2 read ahead (now computing in the pool); 3: window 2's own turn.
            if calls["n"] == 3:
                raise KeyboardInterrupt
        return real_query(*entities, **kw)

    monkeypatch.setattr(db, "query", _query)
    closes: list[bool] = []
    real_close = RP.DrainPool.close

    def _close(self, *, abandon=False):
        closes.append(abandon)
        return real_close(self, abandon=abandon)

    monkeypatch.setattr(RP.DrainPool, "close", _close)
    with pytest.raises(KeyboardInterrupt):
        S.reindex_articles(db, extractor=BaselineExtractor(), article_ids=ids, workers=2)
    assert calls["n"] == 3, "the interrupt landed in window 2's own read, with window 2 computed ahead"
    assert closes and closes[-1] is True, "the window still ahead was killed, not waited for"
    assert _no_live_pool()
