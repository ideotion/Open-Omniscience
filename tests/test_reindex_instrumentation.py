"""Re-index rate instrumentation (field ruling 2026-07-29 item 19, "instrument first").

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A "why is my import slow?" report has to distinguish three very different causes:
CPU-bound extraction, write-bound DB apply, or a pool that SILENTLY degraded to one
core. A single wall-clock number for the whole re-index cannot tell them apart, so the
split — and crucially WHICH PATH the precompute actually took — is measured.

Everything here is an out-parameter, so the return shapes callers already assert on
(``{"reindexed", "failed"}``) are untouched; that is pinned below too.
"""

from __future__ import annotations

import pytest

from src.analytics.extract import BaselineExtractor
from src.analytics.reindex_parallel import _MIN_PARALLEL_BATCH, precompute_batch


def _tasks(n: int):
    return [
        (i, f"Climate policy number {i} shaped the talks and the energy debate.", "T", "en", "en")
        for i in range(1, n + 1)
    ]


def test_stats_is_optional_and_the_result_is_unchanged_without_it():
    """The instrumentation must be invisible when nobody asks for it."""
    tasks = _tasks(4)
    with_stats: dict = {}
    a = precompute_batch(tasks, extractor=BaselineExtractor(), workers=0)
    b = precompute_batch(tasks, extractor=BaselineExtractor(), workers=0, stats=with_stats)
    assert set(a) == set(b) == {t[0] for t in tasks}
    assert with_stats["articles"] == 4


def test_the_serial_short_circuit_is_named_as_such():
    """A small batch deliberately skips the pool. That is NOT a degradation, and the
    report must not read like one — it is recorded as `serial`, distinct from
    `fallback` (a pool that broke)."""
    stats: dict = {}
    n = max(1, _MIN_PARALLEL_BATCH - 1)
    precompute_batch(_tasks(n), extractor=BaselineExtractor(), workers=4, stats=stats)
    assert stats["by_path"] == {"serial": 1}
    assert stats["articles"] == n
    assert stats["windows"] == 1
    assert stats["seconds"] >= 0


def test_workers_zero_is_serial_not_a_failure():
    stats: dict = {}
    precompute_batch(_tasks(40), extractor=BaselineExtractor(), workers=0, stats=stats)
    assert list(stats["by_path"]) == ["serial"]


def test_a_broken_pool_is_recorded_as_a_fallback_not_as_healthy_serial_work(monkeypatch):
    """THE POINT OF THE FEATURE. Before this, a pool that broke on every window
    degraded to one core and looked, in every measurement available, exactly like a
    healthy run — just slower. It must now be nameable."""
    import src.analytics.reindex_parallel as rp

    class _Boom:
        def __init__(self, *a, **k):
            raise OSError("no process pool in this environment")

    monkeypatch.setattr(rp, "ProcessPoolExecutor", _Boom)

    stats: dict = {}
    tasks = _tasks(_MIN_PARALLEL_BATCH + 5)
    out = precompute_batch(tasks, extractor=BaselineExtractor(), workers=4, stats=stats)

    assert set(out) == {t[0] for t in tasks}, "a pool failure must never cost the result"
    assert stats["by_path"] == {"fallback": 1}, "…but it must be VISIBLE as a fallback"


def test_stats_accumulate_across_windows():
    stats: dict = {}
    precompute_batch(_tasks(3), extractor=BaselineExtractor(), workers=0, stats=stats)
    precompute_batch(_tasks(5), extractor=BaselineExtractor(), workers=0, stats=stats)
    assert stats["windows"] == 2
    assert stats["articles"] == 8
    assert stats["by_path"]["serial"] == 2


def test_an_empty_batch_records_nothing_rather_than_a_zero_window():
    """An empty call did no work; inventing a window for it would skew the per-window
    averages a reader computes from these numbers."""
    stats: dict = {}
    assert precompute_batch([], extractor=BaselineExtractor(), stats=stats) == {}
    assert stats == {}


# --------------------------------------------------------------------------- #
#  the reindex_articles half needs src.database.write (PEP 695, Python >= 3.12)
# --------------------------------------------------------------------------- #
def _reindex_importable() -> bool:
    try:
        import src.database.write  # noqa: F401
    except SyntaxError:
        return False
    return True


@pytest.mark.skipif(
    not _reindex_importable(),
    reason="reindex_articles needs src.database.write (PEP 695 generics, Python >= 3.12)",
)
def test_reindex_articles_reports_a_real_split_and_never_a_fabricated_rate(tmp_path):
    from datetime import UTC, datetime

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.analytics.store import reindex_articles
    from src.database.models import Article, Base, Source

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    db.add(Source(name="S", domain="x.test", country="fr"))
    db.commit()
    ids = []
    for i in range(3):
        a = Article(
            url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=1,
            title="T", content="Climate policy dominated the energy talks.", hash=f"h{i}",
            country="fr", language="en",
            published_at=datetime(2024, 3, 1, tzinfo=UTC), created_at=datetime.now(UTC),
        )
        db.add(a)
        db.commit()
        ids.append(a.id)

    stats: dict = {}
    out = reindex_articles(db, extractor=BaselineExtractor(), article_ids=ids, stats=stats)

    assert out == {"reindexed": 3, "failed": 0}, "the RETURN shape must stay untouched"
    for key in ("wall_s", "load_s", "precompute_s", "apply_s", "articles", "precompute"):
        assert key in stats, f"missing measured field {key}"
    assert stats["articles"] == 3
    assert stats["articles_per_second"] is None or stats["articles_per_second"] > 0

    # An empty run must not divide by zero or invent a rate.
    empty: dict = {}
    assert reindex_articles(
        db, extractor=BaselineExtractor(), article_ids=[], stats=empty
    ) == {"reindexed": 0, "failed": 0}
    assert empty["articles"] == 0
    assert empty["articles_per_second"] is None, "no work done means NO rate, never 0.0"
