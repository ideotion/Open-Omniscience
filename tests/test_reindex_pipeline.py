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

    def _pre(tasks, *, extractor, workers=None, stats=None):
        events.append(("pre", tuple(t[0] for t in tasks), threading.current_thread().name))
        if threading.current_thread().name.startswith("oo-reindex-ahead"):
            # Proof of overlap, without a race: a window started ahead waits (bounded) until an article is applied while it is
            # still in flight. Without the overlap the writer would be waiting on THIS result and nothing would be applied.
            with applied:
                start = n_applied[0]
                ok = applied.wait_for(lambda: n_applied[0] > start, timeout=5)
            events.append(("overlapped", ok))
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


def test_a_stop_leaves_no_helper_running_and_applies_nothing_past_the_boundary(db, recorded):
    ids = _seed(db, 8)
    polls = {"n": 0}

    def _stop() -> bool:
        polls["n"] += 1
        return polls["n"] > 1  # the first window runs, the second boundary stops

    out = S.reindex_articles(db, extractor=BaselineExtractor(), article_ids=ids, workers=4, should_stop=_stop)
    assert out == {"reindexed": 3, "failed": 0}
    assert [e[1] for e in recorded if e[0] == "apply"] == ids[:3]
    assert not [t for t in threading.enumerate() if t.name.startswith("oo-reindex-ahead")]


def test_a_failed_apply_still_waits_for_the_window_started_ahead(db, recorded, monkeypatch):
    ids = _seed(db, 6)
    def _boom(session, art, **kw):
        raise KeyboardInterrupt("an interrupt during the apply")

    monkeypatch.setattr(S, "index_article", _boom)
    with pytest.raises(KeyboardInterrupt):
        S.reindex_articles(db, extractor=BaselineExtractor(), article_ids=ids, workers=4)
    assert not [t for t in threading.enumerate() if t.name.startswith("oo-reindex-ahead")]
