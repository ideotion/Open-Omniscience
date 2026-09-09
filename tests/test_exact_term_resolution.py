"""
Regression test for audit §4.1 (P0, 2026-09-08): a fuzzy resolver reaching a display
surface, presented as measurement.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``resolve_keyword()`` (src/analytics/queries.py) falls back to a ``LIKE %term%``
match, ranked by mention count, whenever the exact normalized term is not stored.
That is a reasonable "did you mean" behaviour for a genuinely forgiving human search
box, but it is dishonest wherever the resolved term becomes a LABEL a display surface
renders as the answer (a trend-chart title, a mind-map centre node, a hover-stats
line, a snippet-list heading) — a short/rare probe term (e.g. a commodity symbol) can
be a pure SUBSTRING of an unrelated, high-mention-count keyword, and the old code
returned that unrelated keyword as if it *were* the probe, hand-verified live as:

    GET /api/insights/trend?bucket=week&term=Dy  -> resolved.normalized = "already"
    GET /api/insights/trend?bucket=week&term=Nd  -> resolved.normalized = "indiqué"
    GET /api/insights/trend?bucket=week&term=Pr  -> resolved.normalized = "proposed"

This file pins the fix: ``resolve_keyword(..., exact=True)`` disables the fuzzy
fallback outright, and every display-aggregation function in ``queries.py`` that
renders ``resolved`` as a label (``trend``, ``trend_range_article_ids``,
``associations``, ``keyword_stats``, ``context``) now calls it that way, so a term
that is only a substring of a real keyword resolves to the honest empty result
instead of silently wearing that keyword's data.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.models import Article, Base, Source

# The stored, frequently-mentioned keyword a short probe term collides with as a
# pure substring ("lith" is contained in "lithium" but is never a keyword of its
# own) -- the same collision shape as the live "Dy" -> "already" / "Nd" ->
# "indiqué" / "Pr" -> "proposed" cases, reproduced deterministically here.
_COLLIDING_TEXT = (
    "Lithium prices surged again as lithium demand for batteries grew, with "
    "lithium supply chains under lithium scrutiny worldwide."
)
_SHORT_PROBE = "lith"       # never its own keyword; a pure substring of "lithium"
_REAL_TERM = "lithium"      # the real, resolvable, frequently-mentioned keyword


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    for i, when in enumerate(["2024-03-01", "2024-03-02", "2024-03-03"]):
        _mk(s, f"lith{i}", _COLLIDING_TEXT, when)
    return s


def _mk(db, h, text, when, country="fr"):
    a = Article(
        url=f"https://x.test/{h}",
        canonical_url=f"https://x.test/{h}",
        source_id=1,
        title="T",
        content=text,
        hash=h,
        country=country,
        language="en",
        published_at=datetime.fromisoformat(when).replace(tzinfo=UTC),
        created_at=datetime.now(UTC),
    )
    db.add(a)
    db.commit()
    index_article(db, a, extractor=BaselineExtractor(), country=country, city="Paris")
    return a


# --- resolve_keyword() itself: the exact= contract -------------------------- #

def test_resolve_keyword_default_still_fuzzy_matches(db):
    """The default (exact=False) is UNCHANGED — other-module callers (link_analysis,
    briefing producers) that rely on the forgiving fallback keep it verbatim."""
    kw = q.resolve_keyword(db, _SHORT_PROBE)
    assert kw is not None
    assert kw.normalized_term == _REAL_TERM


def test_resolve_keyword_exact_rejects_substring_match(db):
    """exact=True must refuse a term that only matches as a LIKE substring."""
    assert q.resolve_keyword(db, _SHORT_PROBE, exact=True) is None


def test_resolve_keyword_exact_still_finds_the_real_term(db):
    """exact=True must not be a blanket refusal -- a genuine exact term still
    resolves."""
    kw = q.resolve_keyword(db, _REAL_TERM, exact=True)
    assert kw is not None
    assert kw.normalized_term == _REAL_TERM


# --- Display-path aggregations: the substring probe must resolve to NOTHING - #

def test_trend_rejects_substring_match(db):
    real = q.trend(db, _REAL_TERM, bucket="week")
    assert real["resolved"] is not None
    assert real["total"] > 0

    probe = q.trend(db, _SHORT_PROBE, bucket="week")
    assert probe["resolved"] is None
    assert probe["points"] == []
    assert probe["total"] == 0
    assert probe["articles"] == 0


def test_trend_range_article_ids_rejects_substring_match(db):
    start, end = date(2024, 3, 1), date(2024, 3, 3)
    real = q.trend_range_article_ids(db, _REAL_TERM, start=start, end=end, bucket="day")
    assert real["resolved"] is not None
    assert real["articles"] > 0

    probe = q.trend_range_article_ids(db, _SHORT_PROBE, start=start, end=end, bucket="day")
    assert probe["resolved"] is None
    assert probe["article_ids"] == []
    assert probe["articles"] == 0


def test_associations_rejects_substring_match(db):
    real = q.associations(db, _REAL_TERM)
    assert real["resolved"] is not None  # the real term always resolves, pairs may be sparse
    probe = q.associations(db, _SHORT_PROBE)
    assert probe["resolved"] is None
    assert probe["pairs"] == []


def test_keyword_stats_rejects_substring_match(db):
    real = q.keyword_stats(db, _REAL_TERM)
    assert real["resolved"] is not None
    assert real["mentions"] > 0

    probe = q.keyword_stats(db, _SHORT_PROBE)
    assert probe["resolved"] is None
    assert probe["mentions"] == 0
    assert probe["articles"] == 0


def test_context_rejects_substring_match(db):
    real = q.context(db, _REAL_TERM)
    assert real["resolved"] is not None
    assert real["count"] > 0

    probe = q.context(db, _SHORT_PROBE)
    assert probe["resolved"] is None
    assert probe["mentions"] == []


def test_unrelated_term_stays_empty_not_a_regression(db):
    """A term with no collision at all (audit's own control case: 'lithium'/'cobalt'
    style no-match) must stay the honest empty result, exactly as before."""
    out = q.trend(db, "zzz_not_in_corpus_zzz", bucket="week")
    assert out["resolved"] is None
    assert out["points"] == []
