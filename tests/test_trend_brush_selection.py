"""Resolving a brushed chart span to article ids (GUI visualization plan F4).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The honesty of a brush rests on three things that a positive-space suite would not
check, so each has its own case:

  * it must resolve on ``KeywordMention.observed_on`` -- the column the chart is drawn
    from -- and NOT through the ``published_at`` date filter, which means something
    different. An article whose publish date could not be extracted is plotted on the
    chart, so a brush that missed it would return less than the user selected. (The
    disagreement itself is pinned in ``tests/test_chart_time_vs_filter_time.py``.)
  * it must report ARTICLES and MENTIONS as separate numbers, because a bar's height is
    the mention total and the selection is a set of articles. Letting one stand for the
    other is the conflation this project refuses elsewhere.
  * it must not hand back ids that will vanish when opened. ``trend`` counts quarantined
    articles but the analysis window filters them, so they are removed here and counted.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.queries import trend, trend_range_article_ids
from src.database.models import Article, Base, Keyword, KeywordMention, Source

BASE = datetime(2026, 4, 1, tzinfo=UTC)
_BODY = "Rainfall across the delta displaced residents from low-lying wards. " * 8


@pytest.fixture()
def db():
    """An isolated in-memory corpus -- never SessionLocal, which is shared for the whole
    pytest session and would leak these rows into every later reader."""
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    try:
        yield s
    finally:
        s.close()


def _seed(db, *, days=30, per_day=2, quarantine_every=0, undated_day=None):
    """A keyword mentioned on consecutive days, with optional quarantined rows and one
    optionally-undated article (published_at NULL) to prove the observed_on path."""
    src = Source(name="s.example", domain="s.example")
    db.add(src)
    db.flush()
    kw = Keyword(term="flooding", normalized_term="flooding")
    noise = Keyword(term="election", normalized_term="election")
    db.add_all([kw, noise])
    db.flush()

    n = 0
    undated_ids: list[int] = []
    for d in range(days):
        when = BASE + timedelta(days=d)
        for j in range(per_day):
            n += 1
            undated = undated_day is not None and d == undated_day and j == 0
            art = Article(
                source_id=src.id,
                url=f"https://s.example/a{n}",
                canonical_url=f"https://s.example/a{n}",
                title=f"Delta report {n}",
                content=_BODY,
                hash=f"h{n}",
                published_at=None if undated else when,
                created_at=when,
                quarantined=bool(quarantine_every) and (n % quarantine_every == 0),
            )
            db.add(art)
            db.flush()
            if undated:
                undated_ids.append(art.id)
            # count > 1 so mentions and articles are provably different numbers
            db.add(KeywordMention(keyword_id=kw.id, article_id=art.id, count=2,
                                  observed_on=when.date()))
            # a second keyword on the same articles: its mentions must never be counted
            db.add(KeywordMention(keyword_id=noise.id, article_id=art.id, count=7,
                                  observed_on=when.date()))
    db.commit()
    return kw, undated_ids


def test_the_span_returns_the_articles_in_it_and_nothing_outside(db):
    _seed(db, days=30, per_day=2)
    out = trend_range_article_ids(
        db, "flooding", start=date(2026, 4, 10), end=date(2026, 4, 12)
    )
    assert out["articles"] == 6, "3 days x 2 articles"
    assert len(out["article_ids"]) == 6
    assert out["start"] == "2026-04-10" and out["end"] == "2026-04-12"

    outside = trend_range_article_ids(
        db, "flooding", start=date(2026, 4, 1), end=date(2026, 4, 2)
    )
    assert set(out["article_ids"]).isdisjoint(outside["article_ids"])


def test_articles_and_mentions_are_reported_as_different_numbers(db):
    """The bar height is a mention total. With count=2 per article the two numbers must
    differ, so a caller cannot let one stand for the other."""
    _seed(db, days=10, per_day=2)
    out = trend_range_article_ids(
        db, "flooding", start=date(2026, 4, 1), end=date(2026, 4, 5)
    )
    assert out["articles"] == 10
    assert out["mentions"] == 20, "count=2 per article"
    assert out["mentions"] != out["articles"], (
        "if these are ever equal by construction the test has stopped discriminating"
    )


def test_another_keywords_mentions_are_never_counted(db):
    """The seeded corpus puts a second keyword on the same articles with count=7. If the
    filter on keyword_id were dropped, mentions would jump and articles would not."""
    _seed(db, days=10, per_day=2)
    out = trend_range_article_ids(
        db, "flooding", start=date(2026, 4, 1), end=date(2026, 4, 5)
    )
    assert out["mentions"] == 20, "20 = 10 articles x count 2, never 90 with the noise"


def test_the_bar_total_and_the_brush_total_agree_for_the_same_span(db):
    """The point of resolving on observed_on: what the chart drew and what the brush
    returns are the same rows. A day-bucketed trend summed over the span must equal the
    brush's mention total, or the selection does not match the bars."""
    _seed(db, days=20, per_day=2)
    tr = trend(db, "flooding", bucket="day")
    lo, hi = date(2026, 4, 5), date(2026, 4, 9)
    from_chart = sum(
        p["count"] for p in tr["points"] if lo.isoformat() <= p["date"] <= hi.isoformat()
    )
    out = trend_range_article_ids(db, "flooding", start=lo, end=hi)
    assert from_chart == out["mentions"], (
        "the brush must sum the same rows the bars did"
    )


def test_an_article_with_no_publish_date_is_still_selected(db):
    """THE NEGATIVE-SPACE CASE THAT MOTIVATED THE DESIGN. observed_on coalesces
    published_at/created_at, so such an article IS plotted. Resolving the brush through
    the published_at filter instead would silently drop it -- the user would select a bar
    and receive less than it counted."""
    _kw, undated = _seed(db, days=10, per_day=2, undated_day=3)
    assert undated, "fixture must actually create an undated article"
    out = trend_range_article_ids(
        db, "flooding", start=date(2026, 4, 4), end=date(2026, 4, 4)
    )
    assert undated[0] in out["article_ids"], (
        "an article whose publish date could not be extracted is on the chart, so it must "
        "be in the selection; if this fails the resolver has drifted onto published_at"
    )


def test_quarantined_articles_are_removed_and_counted(db):
    """They are counted by the bar but filtered by the window the selection opens, so
    removing them here is what makes the reported number the number that opens."""
    _seed(db, days=10, per_day=2, quarantine_every=4)
    out = trend_range_article_ids(
        db, "flooding", start=date(2026, 4, 1), end=date(2026, 4, 10)
    )
    assert out["quarantined_excluded"] == 5, "every 4th of 20 articles"
    assert out["articles"] == 15
    assert len(out["article_ids"]) == 15
    quarantined = {
        a.id for a in db.query(Article).filter(Article.quarantined.is_(True)).all()
    }
    assert quarantined, "fixture must actually quarantine something"
    assert set(out["article_ids"]).isdisjoint(quarantined)


def test_the_mention_total_still_includes_quarantined_so_it_matches_the_bar(db):
    """Deliberate asymmetry, and the reason it is right: the bar was drawn from an
    unfiltered aggregate, so silently changing the mention total here would make the
    readout disagree with the chart above it. The difference is disclosed instead."""
    _seed(db, days=10, per_day=2, quarantine_every=4)
    out = trend_range_article_ids(
        db, "flooding", start=date(2026, 4, 1), end=date(2026, 4, 10)
    )
    assert out["mentions"] == 40, "all 20 articles x count 2, quarantined included"
    assert out["articles"] == 15
    assert out["quarantined_excluded"] == 5


def test_an_unknown_term_is_an_honest_empty_not_an_error(db):
    _seed(db, days=5, per_day=1)
    out = trend_range_article_ids(
        db, "nosuchtermanywhere", start=date(2026, 4, 1), end=date(2026, 4, 5)
    )
    assert out["resolved"] is None
    assert out["article_ids"] == [] and out["articles"] == 0 and out["mentions"] == 0
    assert out["method"] and out["caveat"], "an empty result still states its method"


def test_an_inverted_span_returns_empty_rather_than_guessing(db):
    _seed(db, days=10, per_day=1)
    out = trend_range_article_ids(
        db, "flooding", start=date(2026, 4, 9), end=date(2026, 4, 2)
    )
    assert out["article_ids"] == [] and out["articles"] == 0


def test_the_cap_bounds_the_ids_and_says_so(db):
    _seed(db, days=30, per_day=2)
    out = trend_range_article_ids(
        db, "flooding", start=date(2026, 4, 1), end=date(2026, 4, 30), cap=7
    )
    assert len(out["article_ids"]) == 7
    assert out["articles"] == 60, "the true count is reported, not the truncated one"
    assert out["capped"] is True
    full = trend_range_article_ids(
        db, "flooding", start=date(2026, 4, 1), end=date(2026, 4, 30)
    )
    assert full["capped"] is False


def test_method_and_caveat_are_fixed_strings_so_they_can_be_translated(db):
    """A value interpolated into either would make the key vary per corpus and no locale
    entry could ever match it -- the recorded i18n failure mode."""
    _seed(db, days=4, per_day=1)
    a = trend_range_article_ids(db, "flooding", start=date(2026, 4, 1), end=date(2026, 4, 2))
    b = trend_range_article_ids(db, "flooding", start=date(2026, 4, 3), end=date(2026, 4, 4))
    assert a["method"] == b["method"] and a["caveat"] == b["caveat"]
    for s in (a["method"], a["caveat"]):
        assert not any(ch.isdigit() for ch in s), f"a number leaked into a keyed string: {s}"


def test_no_field_name_reads_as_a_score(db):
    """The recursive convention: score/rating/rank/trust/verdict/grade are banned as key
    SUBSTRINGS, and 'degraded' contains 'grade', so the walk is over key names."""
    _seed(db, days=4, per_day=1)
    out = trend_range_article_ids(db, "flooding", start=date(2026, 4, 1), end=date(2026, 4, 4))
    banned = ("score", "rating", "rank", "trust", "verdict", "grade")
    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                low = str(k).lower()
                for b in banned:
                    assert b not in low, f"{path}.{k} contains {b!r}"
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
    walk(out)
