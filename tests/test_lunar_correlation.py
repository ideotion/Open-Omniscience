"""Lunar-effects correlation framework — the honest "name the shape" instrument
(deterministic circular-shift permutation test + BH-FDR, correlation != causation).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import lunar
from src.database.models import Article, Base, Keyword, KeywordMention

END = date.today()
START = END - timedelta(days=119)  # ~4 lunar cycles of daily data


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


# --------------------------------------------------------------------------- #
# pure math


def test_circular_shift_perfect_correlation():
    moon = list(lunar.moon_fraction_by_day(START, END).values())
    res = lunar.circular_shift_test(list(moon), moon)  # x == moon -> r = 1
    assert res is not None
    r, p = res
    assert r == pytest.approx(1.0, abs=1e-9)
    assert p < 0.2  # the observed alignment beats almost every rigid shift


def test_circular_shift_constant_series_is_none():
    moon = list(lunar.moon_fraction_by_day(START, END).values())
    assert lunar.circular_shift_test([5.0] * len(moon), moon) is None  # no fabricated r


def test_moon_fraction_is_in_range():
    frac = lunar.moon_fraction_by_day(START, END)
    assert len(frac) >= 100
    assert all(0.0 <= v <= 1.0 for v in frac.values())


def test_single_series_correlation_is_uncorrected():
    moon = lunar.moon_fraction_by_day(START, END)
    # A daily series that discretely tracks the moon.
    daily = {d: 1.0 + round(v * 9) for d, v in moon.items()}
    corr = lunar.correlate_daily_series("moontrack", daily)
    assert corr is not None
    assert corr.r > 0.9
    assert corr.q_value is None and corr.survives is None  # a single test, not a screen
    d = corr.to_dict()
    assert d["term"] == "moontrack" and d["window"]["start"] and d["n"] >= 45


def test_too_sparse_series_is_skipped_not_invented():
    daily = {START.isoformat(): 3.0, END.isoformat(): 5.0}  # 2 active days
    assert lunar.correlate_daily_series("sparse", daily) is None


# --------------------------------------------------------------------------- #
# the screen (BH-FDR corrected) over a real corpus


def _keyword(db, kid, term):
    db.add(Keyword(id=kid, term=term, normalized_term=term))
    db.commit()


_ART = [0]


def _daily_mentions(db, keyword_id, counts_by_day):
    for d, c in counts_by_day.items():
        _ART[0] += 1
        aid = _ART[0]
        db.add(Article(
            id=aid, url=f"https://x/{aid}", canonical_url=f"https://x/{aid}",
            source_id=1, title="T", content="c", hash=f"h{aid}",
            published_at=datetime(d.year, d.month, d.day, tzinfo=UTC),
            created_at=datetime.now(UTC),
        ))
        db.add(KeywordMention(
            keyword_id=keyword_id, article_id=aid, observed_on=d, count=int(c),
        ))
    db.commit()


def test_screen_corrects_for_multiple_testing(db):
    moon = lunar.moon_fraction_by_day(START, END)
    days = sorted(date.fromisoformat(d) for d in moon)
    # A keyword whose daily count tracks the moon.
    _keyword(db, 1, "moontrack")
    _daily_mentions(db, 1, {d: 1 + round(moon[d.isoformat()] * 9) for d in days})
    # A keyword whose daily count follows a weekly cycle (uncorrelated with the lunar month).
    _keyword(db, 2, "weeknoise")
    _daily_mentions(db, 2, {d: 2 + (i % 7) for i, d in enumerate(days)})

    out = lunar.lunar_screen(db, terms=["moontrack", "weeknoise"], fdr_q=0.05)
    assert out["tested"] == 2
    assert out["caveat"] == lunar.CORRELATION_CAVEAT
    assert out["fdr_q"] == 0.05 and "method" in out
    by_term = {r["term"]: r for r in out["results"]}
    # The moon-tracking series is far more correlated (lower p) than the weekly noise.
    assert by_term["moontrack"]["p_value"] < by_term["weeknoise"]["p_value"]
    # Every result carries a BH-adjusted q-value + a survives flag (never a bare p).
    assert all(r["q_value"] is not None and r["survives"] in (True, False) for r in out["results"])


def test_screen_on_pure_noise_finds_nothing_honestly(db):
    moon = lunar.moon_fraction_by_day(START, END)
    days = sorted(date.fromisoformat(d) for d in moon)
    # Two independent weekly-cycle series, neither aligned to the moon.
    _keyword(db, 1, "a")
    _daily_mentions(db, 1, {d: 3 + (i % 7) for i, d in enumerate(days)})
    _keyword(db, 2, "b")
    _daily_mentions(db, 2, {d: 4 + ((i + 3) % 5) for i, d in enumerate(days)})
    out = lunar.lunar_screen(db, terms=["a", "b"], fdr_q=0.05)
    assert out["survivors"] == 0
    assert "honest" in out["note"].lower()
