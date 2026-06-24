"""Vocabulary-growth curve (src/analytics/keyword_growth.py).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pins: the cumulative curve is correct + monotonic, the figure is read DECRYPT-FREE
(no Article rows needed — proves it never joins to the encrypted articles table), the
Heaps fit separates a saturating vocabulary from junk-linear growth, undated mentions
are counted not dropped, and there is NO score key anywhere.
"""

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.keyword_growth import _fit_heaps, keyword_growth_curve
from src.database.models import Base, Keyword, KeywordMention


def _sess():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _kw(s, norm):
    k = Keyword(term=norm, normalized_term=norm, language="en", frequency=0)
    s.add(k)
    s.flush()
    return k


def _m(s, kw, art, d, count=1):
    s.add(KeywordMention(keyword_id=kw.id, article_id=art, count=count, observed_on=d))


def _no_score_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert "score" not in k.lower(), f"score key found: {k}"
            _no_score_keys(v)
    elif isinstance(obj, list):
        for x in obj:
            _no_score_keys(x)


def test_curve_is_cumulative_and_decrypt_free():
    s = _sess()
    # NB: NO Article rows are ever created -> the curve must read keyword_mentions only.
    a, b, c = _kw(s, "alpha"), _kw(s, "beta"), _kw(s, "gamma")
    # day 1: alpha (in two articles) + beta -> 2 new keywords, 6 tokens
    _m(s, a, 1, date(2026, 1, 1), 2)
    _m(s, a, 2, date(2026, 1, 1), 1)
    _m(s, b, 1, date(2026, 1, 1), 3)
    # day 2: alpha again (NOT new) + gamma (new) -> +1 keyword, +6 tokens
    _m(s, a, 3, date(2026, 1, 2), 1)
    _m(s, c, 3, date(2026, 1, 2), 5)
    s.commit()

    r = keyword_growth_curve(s)
    assert r["kind"] == "keyword-growth-curve" and r["schema"] == "oo-keyword-growth-1"
    assert r["totals"]["keywords"] == 3
    assert r["totals"]["tokens"] == 12  # 2+1+3 + 1+5
    assert r["totals"]["articles"] == 3  # distinct article ids 1,2,3

    ser = r["series"]
    assert ser[0]["keywords"] == 2 and ser[0]["tokens"] == 6   # end of day 1
    assert ser[-1]["keywords"] == 3 and ser[-1]["tokens"] == 12  # end of day 2
    for i in range(1, len(ser)):  # cumulative -> non-decreasing
        assert ser[i]["keywords"] >= ser[i - 1]["keywords"]
        assert ser[i]["tokens"] >= ser[i - 1]["tokens"]

    _no_score_keys(r)  # no composite score anywhere


def test_undated_mentions_are_counted_not_dropped():
    s = _sess()
    a = _kw(s, "alpha")
    _m(s, a, 1, date(2026, 1, 1), 1)
    _m(s, a, 2, None, 4)  # a mention with no observed_on
    s.commit()
    r = keyword_growth_curve(s)
    assert r["totals"]["undated_mentions"] == 1
    assert r["totals"]["tokens"] == 1  # the undated 4 tokens are excluded from the curve
    assert "1 mentions have no date" in r["caveat"]


def test_heaps_fit_separates_saturating_from_junk():
    # A saturating vocabulary: tokens grow 1000x while new keywords slow down -> beta < 1.
    sat = _fit_heaps([10, 100, 1000, 10000], [10, 30, 60, 100])
    assert sat["beta"] is not None and 0.0 < sat["beta"] < 1.0
    # Junk: every new word is a brand-new keyword -> near-linear, beta ~ 1.
    junk = _fit_heaps([10, 100, 1000, 10000], [10, 100, 1000, 10000])
    assert junk["beta"] is not None and 0.9 < junk["beta"] <= 1.05
    # Too few points -> honest None, never a fabricated slope.
    assert _fit_heaps([1], [1])["beta"] is None


def test_empty_corpus_is_honest():
    s = _sess()
    r = keyword_growth_curve(s)
    assert r["totals"]["keywords"] == 0 and r["series"] == []
    assert r["heaps"]["beta"] is None  # no fabricated curve on no data
