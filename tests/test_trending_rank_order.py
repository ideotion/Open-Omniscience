"""The bounded, lazy ranking inside ``trending`` (diagnostics rank 4).

``trending`` used to put a six-field tuple for EVERY keyword over the floor into one list and
sort it; on a large corpus that list was the allocation burst one instance died in. The
ranking now streams through ``heapq.nsmallest`` a chunk at a time. The contract is that the
ORDER is unchanged, ties included, so these tests compare it with the old construction
verbatim on a corpus built to be full of ties.
"""

from __future__ import annotations

import random
import tracemalloc

import pytest

from src.analytics import queries


def _old(recent, prior, *, min_recent, baseline_days, window_days):
    """The construction this replaced, copied so the comparison is against the real thing."""
    scored = []
    for kid, rc in recent.items():
        rc = int(rc or 0)
        if rc < min_recent:
            continue
        pc = int(prior.get(kid, 0) or 0)
        expected = (pc / baseline_days) * window_days
        growth, is_ratio = queries._growth_of(rc, expected)
        scored.append((kid, rc, pc, round(expected, 2), round(growth, 2), is_ratio))
    scored.sort(key=lambda x: (-x[4], -x[1]))
    return scored


def _corpus(seed: int, n: int):
    rng = random.Random(seed)
    # Few distinct counts, so equal (growth, recent) keys are the rule and the stable-tie
    # behaviour is what is under test; ids deliberately not in dict order.
    kids = rng.sample(range(10_000, 10_000 + n * 3), n)
    recent = {k: rng.choice([0, 1, 2, 3, 3, 4, 5, 8, 13]) for k in kids}
    prior = {k: rng.choice([0, 0, 1, 2, 6, 30, 90]) for k in kids if rng.random() < 0.7}
    return recent, prior


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
@pytest.mark.parametrize("want", [1, 4, 20, 10_000])
def test_the_order_is_exactly_the_old_sorted_list_ties_included(seed, want):
    recent, prior = _corpus(seed, 3000)
    kw = {"min_recent": 2, "baseline_days": 30, "window_days": 7}
    got = list(queries._rising_in_rank_order(recent, prior, want=want, **kw))
    assert got == _old(recent, prior, **kw)


def test_a_chunk_is_grown_when_the_caller_filters_most_of_it_away():
    recent, prior = _corpus(9, 2000)
    kw = {"min_recent": 1, "baseline_days": 30, "window_days": 1}
    want = 3  # the first chunk is 64; a caller that keeps only one in 50 needs several
    stream = queries._rising_in_rank_order(recent, prior, want=want, **kw)
    kept = [row for i, row in enumerate(stream) if i % 50 == 0]
    assert kept == _old(recent, prior, **kw)[::50]


def test_nothing_over_the_floor_yields_nothing():
    kw = {"min_recent": 5, "baseline_days": 30, "window_days": 7}
    assert list(queries._rising_in_rank_order({1: 1, 2: 4}, {}, want=3, **kw)) == []


def test_asking_for_the_top_few_allocates_far_less_than_building_every_row():
    recent, prior = _corpus(5, 60_000)
    kw = {"min_recent": 1, "baseline_days": 30, "window_days": 7}
    tracemalloc.start()
    base = tracemalloc.take_snapshot()
    first = [next(iter(queries._rising_in_rank_order(recent, prior, want=8, **kw))) for _ in range(1)]
    lazy_peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.reset_peak()
    _old(recent, prior, **kw)
    old_peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    del base, first
    assert lazy_peak < old_peak / 3, (lazy_peak, old_peak)


def test_scanned_counts_the_keywords_over_the_floor_and_no_others(tmp_path):
    """``scanned`` is the figure the multiple-comparisons caveat quotes ("with many terms
    scanned, some ratios run high by chance"): how many keywords were screened, i.e. the ones
    over the ``min_recent`` floor. It is its own pass now, so it is pinned (the coordinator's
    check of PR #1284, mutant E11: counting every keyword passed every test)."""
    from datetime import date, timedelta

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base, Keyword, KeywordMention, Source

    engine = create_engine(f"sqlite:///{tmp_path / 'scanned.db'}", future=True)
    Base.metadata.create_all(engine)
    today = date.today()
    with sessionmaker(bind=engine, future=True)() as s:
        s.add(Source(name="S", domain="x.test"))
        for i, recent in enumerate([1, 2, 3, 4, 9], start=1):
            s.add(Keyword(term=f"zzscan{i}", normalized_term=f"zzscan{i}", language="en"))
        s.flush()
        for i, recent in enumerate([1, 2, 3, 4, 9], start=1):
            s.add(KeywordMention(keyword_id=i, article_id=i, count=recent, observed_on=today))
        s.commit()
        out = queries.trending(s, window_days=7, baseline_days=30, limit=10, min_recent=3)
    assert out["scanned"] == 3, "only the keywords with at least min_recent mentions were screened"

