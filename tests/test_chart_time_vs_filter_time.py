"""A chart's time axis and the date FILTER do not mean the same thing.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS FILE EXISTS. Two surfaces publish "when an article is", by different rules:

  * ``KeywordMention.observed_on`` = ``(published_at or created_at).date()``
    (``src/analytics/store.py:284``) -- a COALESCE. This is the x-axis of every
    keyword trend chart.
  * the date filter behind Advanced search and ``_resolve_corpus`` =
    ``Article.published_at`` alone (``src/api/main.py:818-821``) -- no fallback.

So an article whose publish date could not be extracted is PLOTTED on the chart at its
ingest date and EXCLUDED by a filter over that same day. Measured below: two articles,
one chart day, one returned.

THE POINT IS NOT THAT THE FILTER IS WRONG. Coalescing it would be the mirror defect:
an article ingested in June with no publish date may have been published in 2019, so
folding ``created_at`` into a filter labelled "published between X and Y" fabricates an
INCLUSION exactly as the present behaviour fabricates an ABSENCE. Restricting to
``published_at`` is the conservative reading and returns only articles we know were
published in range. What is missing is (a) any DISCLOSURE of how many articles the
filter dropped for want of a publish date, and (b) agreement between the two surfaces
about which "June" is being shown.

WHAT IT CONSTRAINS. The planned brush-to-select (GUI visualization plan F4, Unit 6)
must emit the article ids belonging to the buckets the chart actually drew, supplied by
the same aggregate that produced the bar heights. Resolving a brushed range through the
date filter instead would hand back fewer articles than the bars implied, silently --
the user would select what they can see and get less. Carrying the ids makes the brush
inherit the chart's own definition of time by construction, so the disagreement cannot
reach it.

These are CHARACTERIZATION tests: they pin today's behaviour and the reason for it, so a
future change to either surface has to confront the argument above rather than "fixing"
one side by accident.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.models import Article, Base, KeywordMention, Source

DAY = datetime(2026, 6, 15, 9, 0, tzinfo=UTC)
JUNE = (datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 30, tzinfo=UTC))
_BODY = (
    "Flooding displaced thousands across the northern delta region. "
    "Officials said the flooding would continue. "
) * 6


@pytest.fixture()
def db():
    """An isolated in-memory corpus -- never SessionLocal, which is shared for the
    whole pytest session and would leak these rows into every later reader."""
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    try:
        yield s
    finally:
        s.close()


def _seed(db):
    """Two articles ingested the same day; only one carries a publish date."""
    src = Source(name="d.example", domain="d.example")
    db.add(src)
    db.flush()
    dated = Article(
        source_id=src.id, url="https://d.example/a", canonical_url="https://d.example/a",
        title="Delta flooding report", content=_BODY, hash="h-dated",
        published_at=DAY, created_at=DAY,
    )
    undated = Article(
        source_id=src.id, url="https://d.example/b", canonical_url="https://d.example/b",
        title="Delta flooding update", content=_BODY, hash="h-undated",
        published_at=None, created_at=DAY,
    )
    db.add_all([dated, undated])
    db.flush()
    for art in (dated, undated):
        index_article(db, art, extractor=BaselineExtractor())
    db.commit()
    return dated, undated


def _filtered_ids(db):
    """The date filter as _query_articles applies it: published_at, no fallback."""
    lo, hi = JUNE
    rows = (
        db.query(Article.id)
        .filter(Article.published_at >= lo, Article.published_at <= hi)
        .all()
    )
    return {r[0] for r in rows}


def test_both_articles_land_on_the_same_chart_day(db):
    """The coalesce puts an undated article on the chart at its INGEST date, so a trend
    bar counts it. If this ever stops holding, the chart has started hiding articles
    rather than the filter -- a different and worse problem."""
    dated, undated = _seed(db)
    observed = {m.article_id: m.observed_on for m in db.query(KeywordMention).all()}
    assert observed[dated.id] == DAY.date()
    assert observed[undated.id] == DAY.date(), (
        "an article with no publish date must still be plotted, at its ingest date"
    )


def test_the_date_filter_silently_drops_the_undated_article(db):
    """The disagreement itself. Two articles on one chart day; one survives the filter.

    Asserted as a SHORTFALL rather than as a count, so the test states the consequence
    (the filter returns fewer than the chart drew) instead of a number that would need
    editing every time the fixture grows.
    """
    dated, undated = _seed(db)
    plotted = {m.article_id for m in db.query(KeywordMention).all()}
    kept = _filtered_ids(db)

    assert dated.id in kept
    assert undated.id not in kept, (
        "if this passes, the filter has gained a created_at fallback -- read the module "
        "docstring first: that fabricates an INCLUSION for an article whose publish date "
        "is genuinely unknown, and the shortfall should be DISCLOSED instead"
    )
    assert len(kept) < len(plotted), (
        "the filter returns fewer articles than the chart counted, and says nothing"
    )


def test_the_shortfall_is_countable_so_a_caveat_could_state_it(db):
    """The honest repair is a disclosure, which requires the number to be available.

    It is: an article that the coalesce places in the window while carrying no publish
    date is exactly ``published_at IS NULL AND created_at IN window``. A future caveat
    ("N articles in this range carry no publish date and are not included") needs no new
    storage -- only this query. Pinned so the claim cannot rot.
    """
    _seed(db)
    lo, hi = JUNE
    undisclosed = (
        db.query(Article.id)
        .filter(
            Article.published_at.is_(None),
            Article.created_at >= lo,
            Article.created_at <= hi,
        )
        .count()
    )
    assert undisclosed == 1, "the excluded-for-want-of-a-publish-date count is derivable"


def test_a_brush_must_not_resolve_a_range_through_the_date_filter(db):
    """The F4 design constraint, expressed as arithmetic rather than as a comment.

    A brush that covered the whole of June and resolved it through the date filter would
    return strictly fewer ids than the bars it covered were counting. That gap is the
    reason the brush has to carry the aggregate's own ids.
    """
    _seed(db)
    covered_by_the_bars = {m.article_id for m in db.query(KeywordMention).all()}
    would_be_returned = _filtered_ids(db)
    lost = covered_by_the_bars - would_be_returned
    assert lost, (
        "no gap here would mean the constraint is unnecessary -- if that becomes true, "
        "delete this file rather than leaving a guard that cannot fail"
    )
    assert lost.isdisjoint(would_be_returned)
