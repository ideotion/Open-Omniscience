"""The article's OWN top keyword: the precompute behind the Articles-tab column.

Rulings 23/38/39 (field feedback 2026-08-07).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article, top_keyword_of
from src.database.models import Article, Base, Source


# --------------------------------------------------------------------------
# The pure rule. These are the assertions that make a naive `max()` fail: an
# implementation that returns any member of a tied set, or that reports tied_n
# as 1, passes none of them.
# --------------------------------------------------------------------------


def test_no_keywords_is_all_none_not_a_zero():
    """An article with no keywords has no top keyword -- never a top keyword of 0.

    A fabricated (id, 0) would render in the Articles tab as a real answer."""
    assert top_keyword_of({}) == (None, None, None)


def test_a_single_maximum_is_unambiguous():
    assert top_keyword_of({7: 5, 2: 1, 9: 3}) == (7, 5, 1)


def test_a_tie_reports_every_member_not_a_winner():
    """Two keywords at the same count: tied_n says so, so no caller can render
    one of them as THE top keyword."""
    rep, count, tied = top_keyword_of({7: 4, 2: 4, 9: 1})
    assert count == 4
    assert tied == 2, "a two-way tie must be reported as two, never as one"
    assert rep in (2, 7)


def test_the_representative_is_deterministic_across_equal_inputs():
    """The same counts must yield the same representative however the map was
    built -- otherwise a re-index silently reshuffles the Articles-tab sort."""
    a = top_keyword_of({7: 4, 2: 4, 5: 4})
    b = top_keyword_of({5: 4, 7: 4, 2: 4})
    assert a == b == (2, 4, 3)


def test_a_wide_tie_is_reported_at_its_real_width():
    """The common shape: every keyword occurs once. tied_n carries the true width
    (nothing is truncated); the caller decides how to say "no distinguishing
    keyword"."""
    rep, count, tied = top_keyword_of({i: 1 for i in range(1, 201)})
    assert (rep, count, tied) == (1, 1, 200)


def test_zero_and_negative_counts_are_not_evidence():
    """A count of 0 is not an occurrence, so it can never make a top keyword."""
    assert top_keyword_of({5: 0, 6: 0}) == (None, None, None)
    assert top_keyword_of({5: 0, 6: 2}) == (6, 2, 1)
    assert top_keyword_of({5: -3}) == (None, None, None)


# --------------------------------------------------------------------------
# The production path: index_article is the ONE hook that must maintain it.
# --------------------------------------------------------------------------


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tk.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _article(session, *, hash_: str, content: str, title: str = "T") -> Article:
    a = Article(
        url=f"https://wire.test/{hash_}",
        canonical_url=f"https://wire.test/{hash_}",
        source_id=1,
        title=title,
        hash=hash_,
        language="en",
        content=content,
        published_at=datetime(2026, 6, 1, tzinfo=UTC),
        created_at=datetime.now(UTC),
    )
    session.add(a)
    session.commit()
    return a


def test_index_article_populates_the_precompute(tmp_path):
    Sess = _session(tmp_path)
    with Sess() as s:
        s.add(Source(name="Wire", domain="wire.test"))
        s.commit()
        # "election" is repeated far more than anything else, so it must win outright.
        a = _article(
            s,
            hash_="h1",
            content=(
                "The election dominated. Election coverage grew. Another election story, "
                "and the election again, election after election. A ferry sank."
            ),
        )
        index_article(s, a, extractor=BaselineExtractor())
        s.refresh(a)

        assert a.top_keyword_count is not None and a.top_keyword_count > 1
        assert a.top_keyword_id is not None
        assert a.top_keyword_tied_n == 1, "a clear repeat leader must not read as tied"

        # The stored answer must MATCH the mention rows -- the whole point is that it is
        # a precompute of them, not a second opinion.
        from src.database.models import Keyword, KeywordMention

        rows = (
            s.query(KeywordMention.keyword_id, KeywordMention.count)
            .filter_by(article_id=a.id)
            .all()
        )
        best = max(c for _k, c in rows)
        assert a.top_keyword_count == best
        winners = sorted(k for k, c in rows if c == best)
        assert a.top_keyword_id == winners[0]
        assert a.top_keyword_tied_n == len(winners)
        assert s.get(Keyword, a.top_keyword_id) is not None, "the id must resolve"


def test_reindexing_an_emptied_article_clears_a_stale_top_keyword(tmp_path):
    """The discriminating case for writing the columns UNCONDITIONALLY.

    An implementation that only sets the columns when it found keywords leaves the
    previous extractor generation's answer in place -- a top keyword with no mention
    row behind it, which is exactly the fabricated claim the precompute must not make.
    """
    Sess = _session(tmp_path)
    with Sess() as s:
        s.add(Source(name="Wire", domain="wire.test"))
        s.commit()
        a = _article(
            s,
            hash_="h2",
            content="Election election election election coverage of the election.",
        )
        index_article(s, a, extractor=BaselineExtractor())
        s.refresh(a)
        assert a.top_keyword_id is not None, "precondition: it found a top keyword"

        # Now the article has no extractable keywords at all.
        a.content = "a"
        s.commit()
        index_article(s, a, extractor=BaselineExtractor())
        s.refresh(a)

        assert (a.top_keyword_id, a.top_keyword_count, a.top_keyword_tied_n) == (
            None,
            None,
            None,
        )


@pytest.mark.parametrize("scope", ["full", "keywords"])
def test_both_scopes_refresh_the_precompute(tmp_path, scope):
    """A keyword-only cleanup must refresh it too: the top keyword is a keyword fact,
    so leaving it stale would let the column describe a previous extractor."""
    Sess = _session(tmp_path)
    with Sess() as s:
        s.add(Source(name="Wire", domain="wire.test"))
        s.commit()
        a = _article(
            s,
            hash_=f"h3{scope}",
            content="Harvest harvest harvest harvest of the harvest season.",
        )
        index_article(s, a, extractor=BaselineExtractor(), scope=scope)
        s.refresh(a)
        assert a.top_keyword_count is not None
        assert a.top_keyword_id is not None
