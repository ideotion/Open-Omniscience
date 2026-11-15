"""R723 (2026-11-15): the re-index computes the NEXT window while the current one is written.

What may not regress: windows are still APPLIED in the caller's order (the resume cursor maps a count back onto that order); the
results are the same as without the overlap; only a POOL precompute is started ahead (a serial one would take the GIL from an apply
that holds the write gate); a stop leaves no helper running; ``OO_REINDEX_PIPELINE=0`` switches it off.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import src.analytics.reindex_parallel as RP
import src.analytics.store as S
from src.analytics.extract import BaselineExtractor
from src.database.models import Article, Base, KeywordMention, Source

_TEXT = "The WHO warned about drought and inflation in Paris on 5 March 2024. Climate policy shifted. " * 3


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.delenv("OO_REINDEX_PIPELINE", raising=False)
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    return s


def _seed(db, n: int) -> list[int]:
    ids = []
    for i in range(n):
        a = Article(
            url=f"https://x.test/{i}",
            canonical_url=f"https://x.test/{i}",
            source_id=1,
            title=f"T{i}",
            content=f"{_TEXT} Item {i}.",
            hash=f"h{i}",
            country="fr",
            language="en",
            published_at=datetime(2024, 3, 1, tzinfo=UTC),
            created_at=datetime.now(UTC),
        )
        db.add(a)
        db.commit()
        ids.append(a.id)
    return ids


@pytest.fixture()
def recorded(monkeypatch):
    """Three-article windows, every precompute treated as a pool one, and the order of events recorded.

    The fake precompute is the real serial computation (``_serial``, the pool's own reference), so results are real; only the
    thread it runs on and when it starts are observed."""
    events: list[tuple] = []
    applied = threading.Condition()
    n_applied = [0]

    def _pre(tasks, *, extractor, workers=None, stats=None, serial_fallback=True):
        events.append(("pre", tuple(t[0] for t in tasks), threading.current_thread().name))
        if threading.current_thread().name.startswith("oo-reindex-ahead"):
            # Proof of overlap, without a race: a window started ahead waits (bounded) until an article is applied while it is
            # still in flight. Without the overlap the writer would be waiting on THIS result and nothing would be applied.
            with applied:
                start = n_applied[0]
                ok = applied.wait_for(lambda: n_applied[0] > start, timeout=5)
            events.append(("overlapped", ok))
        if stats is not None:
            stats["windows"] = stats.get("windows", 0) + 1
        return RP._serial(tasks, extractor)

    real_index = S.index_article

    def _index(session, art, **kw):
        events.append(("apply", art.id))
        with applied:
            n_applied[0] += 1
            applied.notify_all()
        return real_index(session, art, **kw)

    monkeypatch.setattr(S, "_PRECOMPUTE_WINDOW", 3)
    monkeypatch.setattr(RP, "precompute_batch", _pre)
    monkeypatch.setattr(RP, "uses_pool", lambda n, *, extractor, workers=None: True)
    monkeypatch.setattr(S, "index_article", _index)
    return events


def _mentions(db) -> list[tuple]:
    return sorted(
        db.execute(select(KeywordMention.article_id, KeywordMention.keyword_id, KeywordMention.count)).all()
    )


def test_windows_are_applied_in_order_and_the_next_one_is_started_ahead(db, recorded):
    ids = _seed(db, 8)
    stats: dict = {}
    out = S.reindex_articles(db, extractor=BaselineExtractor(), article_ids=ids, workers=4, stats=stats)

    assert out == {"reindexed": 8, "failed": 0}
    assert [e[1] for e in recorded if e[0] == "apply"] == ids, "the resume cursor's order"
    pres = [e for e in recorded if e[0] == "pre"]
    assert [p[1] for p in pres] == [tuple(ids[0:3]), tuple(ids[3:6]), tuple(ids[6:8])]
    assert pres[0][2] == threading.current_thread().name, "the first window has nothing to overlap with"
    assert all(p[2].startswith("oo-reindex-ahead") for p in pres[1:]), "the rest run beside an apply"
    # Each window started ahead saw an article applied while it was in flight.
    assert [e[1] for e in recorded if e[0] == "overlapped"] == [True, True]
    assert stats["pipelined_windows"] == 2
    assert stats["precompute_wait_s"] >= 0.0


def test_the_overlap_changes_no_result(db, recorded, monkeypatch):
    ids = _seed(db, 7)
    S.reindex_articles(db, extractor=BaselineExtractor(), article_ids=ids, workers=4)
    with_overlap = _mentions(db)
    monkeypatch.setenv("OO_REINDEX_PIPELINE", "0")
    S.reindex_articles(db, extractor=BaselineExtractor(), article_ids=ids, workers=4)
    assert with_overlap and _mentions(db) == with_overlap


def test_a_serial_precompute_is_never_started_ahead(db, recorded, monkeypatch):
    """A serial precompute runs in THIS process: beside an apply that holds the write gate it would only take the GIL from it."""
    monkeypatch.setattr(RP, "uses_pool", lambda n, *, extractor, workers=None: False)
    ids = _seed(db, 7)
    stats: dict = {}
    S.reindex_articles(db, extractor=BaselineExtractor(), article_ids=ids, workers=0, stats=stats)
    pres = [e for e in recorded if e[0] == "pre"]
    assert len(pres) == 3 and all(p[2] == threading.current_thread().name for p in pres)
    assert stats["pipelined_windows"] == 0


def test_the_switch_turns_it_off(db, recorded, monkeypatch):
    monkeypatch.setenv("OO_REINDEX_PIPELINE", "0")
    ids = _seed(db, 7)
    stats: dict = {}
    S.reindex_articles(db, extractor=BaselineExtractor(), article_ids=ids, workers=4, stats=stats)
    assert stats["pipelined_windows"] == 0
    assert all(e[2] == threading.current_thread().name for e in recorded if e[0] == "pre")


def test_a_stop_is_answered_without_waiting_for_the_window_computed_ahead(db, recorded, monkeypatch):
    """A Stop at a window boundary returns at once: the window computed ahead is discarded, not waited for (it ends in its own
    time, at the pool timeout at the latest), and nothing past the boundary is applied."""
    ids = _seed(db, 8)
    release = threading.Event()
    fake = RP.precompute_batch

    def _slow_ahead(tasks, *, extractor, workers=None, stats=None, serial_fallback=True):
        if threading.current_thread().name.startswith("oo-reindex-ahead") and tasks[0][0] == ids[6]:
            release.wait(30)
        return fake(tasks, extractor=extractor, workers=workers, stats=stats, serial_fallback=serial_fallback)

    monkeypatch.setattr(RP, "precompute_batch", _slow_ahead)
    polls = {"n": 0}

    def _stop() -> bool:
        polls["n"] += 1
        return polls["n"] > 2  # windows 1 and 2 run; the third boundary stops while window 3 is still computing ahead

    stats: dict = {}
    try:
        out = S.reindex_articles(db, extractor=BaselineExtractor(), article_ids=ids, workers=4, should_stop=_stop, stats=stats)
        assert out == {"reindexed": 6, "failed": 0}
        assert [e[1] for e in recorded if e[0] == "apply"] == ids[:6]
        assert stats["pipelined_windows"] == 1, "the discarded window is not counted"
        assert stats["precompute"]["windows"] == 2
    finally:
        release.set()
    for t in [t for t in threading.enumerate() if t.name.startswith("oo-reindex-ahead")]:
        t.join(10)
        assert not t.is_alive()


def test_a_pool_that_fails_ahead_is_computed_here_and_counted_once(db, recorded, monkeypatch):
    """Ahead, a failed pool never falls back to serial in the helper thread (that would run beside the apply, in the gate hold):
    it raises, and this thread computes the window itself, between applies."""
    ids = _seed(db, 6)
    fake = RP.precompute_batch

    def _fails_ahead(tasks, *, extractor, workers=None, stats=None, serial_fallback=True):
        if not serial_fallback:
            assert threading.current_thread().name.startswith("oo-reindex-ahead")
            stats.setdefault("by_path", {})["pool_failed"] = 1
            raise RP.PoolUnavailable("test")
        return fake(tasks, extractor=extractor, workers=workers, stats=stats)

    monkeypatch.setattr(RP, "precompute_batch", _fails_ahead)
    stats: dict = {}
    out = S.reindex_articles(db, extractor=BaselineExtractor(), article_ids=ids, workers=4, stats=stats)
    assert out == {"reindexed": 6, "failed": 0}
    pres = [e for e in recorded if e[0] == "pre"]
    assert all(p[2] == threading.current_thread().name for p in pres), "both windows computed here"
    assert stats["pipelined_windows"] == 0
    # Counted once, as a fallback, and the redo never asked the pool again (no second "pre" for that window).
    assert stats["precompute"]["by_path"].get("fallback") == 1
    assert "pool_failed" not in stats["precompute"]["by_path"]
    assert [p[1] for p in pres].count(tuple(ids[3:6])) == 0, "window 2 was computed by _serial directly"


def test_a_window_read_ahead_is_fetched_again_when_applied(db, recorded, monkeypatch):
    """The current window's commits expire the objects read ahead; they are fetched again in one query, so an article deleted in
    between is simply absent rather than an error."""
    from sqlalchemy import delete

    ids = _seed(db, 6)
    real_index = S.index_article
    gone = {"done": False}

    def _index(session, art, **kw):
        if not gone["done"]:
            gone["done"] = True
            session.execute(delete(Article).where(Article.id == ids[4]))
        return real_index(session, art, **kw)

    monkeypatch.setattr(S, "index_article", _index)
    stats: dict = {}
    out = S.reindex_articles(db, extractor=BaselineExtractor(), article_ids=ids, workers=4, stats=stats)
    assert out == {"reindexed": 5, "failed": 0}
    assert stats["absent"] == 1


def test_an_interrupt_in_the_apply_is_not_held_by_the_window_computed_ahead(db, recorded, monkeypatch):
    """The interrupt propagates at once; the window computed ahead ends on its own afterwards."""
    ids = _seed(db, 6)

    def _boom(session, art, **kw):
        raise KeyboardInterrupt("an interrupt during the apply")

    monkeypatch.setattr(S, "index_article", _boom)
    with pytest.raises(KeyboardInterrupt):
        S.reindex_articles(db, extractor=BaselineExtractor(), article_ids=ids, workers=4)
    for t in [t for t in threading.enumerate() if t.name.startswith("oo-reindex-ahead")]:
        t.join(10)
        assert not t.is_alive()


def test_without_a_serial_fallback_a_window_the_pool_would_not_take_raises():
    """``serial_fallback=False`` never computes in this process: the caller is running it beside an apply."""
    tasks = [(1, _TEXT, "t", "en", "en")]
    with pytest.raises(RP.PoolUnavailable):
        RP.precompute_batch(tasks, extractor=BaselineExtractor(), workers=0, serial_fallback=False)
    assert set(RP.precompute_batch(tasks, extractor=BaselineExtractor(), workers=0)) == {1}
