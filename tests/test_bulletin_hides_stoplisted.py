"""R111 step T2 in the bulletin: a keyword the stoplist hides takes no slot, joins no story, heads no column.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Three readers made a keyword list without the stoplist's hidden predicate, so a word shipped
in a stoplist batch stayed in already-written editions' inputs until something else changed:

* ``coverage._terms`` (a country's keyword columns): the top rows were cut BEFORE any filter
  could act. The fetch now widens until it holds the headroom in VISIBLE rows.
* ``stories.article_keyword_sets`` (what two articles are compared on): a hidden word took one
  of an article's twelve slots and, repeated in two unrelated articles, joined them.
* ``articles._keywords`` (an article's own keywords): the per-article cut was taken over the
  hidden words too.

Each test has a mutation that fails it (the filter removed), and each states the numbers that
make the failure visible. The eight hidden words are batch 1's (LaTeX macros and boilerplate); the
visible ones are ordinary words.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.analytics.extract import global_stopwords
from src.bulletin import stories
from src.bulletin.articles import _keywords
from src.bulletin.coverage import _terms
from src.bulletin.period import resolve_period
from src.bulletin.stories import article_keyword_sets, build_stories
from src.database.models import Article, Base, Keyword, KeywordMention, Source

HIDDEN = ["mathcal", "mathbf", "mathbb", "mathrm", "fig", "supplementary", "crossref", "likelyno7"]
VISIBLE = ["ballot", "budget", "border", "harbour"]
_P = resolve_period("weekly", end=date(2026, 8, 1))
_DAY = date(2026, 7, 27)


@pytest.fixture()
def s():
    stop = global_stopwords()
    assert all(w in stop for w in HIDDEN), "the fixture's hidden words must be on the shipped list"
    assert not any(w in stop for w in VISIBLE)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()


def _world(s, spec: dict[str, dict[str, int]]):
    """spec: {article label: {term: count}} -> ({label: article id}, {term: keyword id})."""
    src = Source(name="Only", domain="only.test")
    s.add(src)
    s.flush()
    arts: dict[str, int] = {}
    kws: dict[str, int] = {}
    for i, (label, terms) in enumerate(spec.items(), start=1):
        art = Article(
            url=f"https://x/{i}", canonical_url=f"https://x/{i}", source_id=src.id,
            title=f"Article {label}", content=f"Body of {label}. " * 50, hash=f"{i:064d}",
            published_at=datetime.combine(_DAY, datetime.min.time()), quarantined=False,
        )
        s.add(art)
        s.flush()
        arts[label] = art.id
        for term, count in terms.items():
            if term not in kws:
                k = Keyword(term=term, normalized_term=term, language="en")
                s.add(k)
                s.flush()
                kws[term] = k.id
            s.add(KeywordMention(keyword_id=kws[term], article_id=art.id, count=count,
                                 observed_on=_DAY, source_id=src.id))
    s.commit()
    return arts, kws


# ---------------------------------------------------------------------------------- stories


def test_two_unrelated_articles_that_repeat_hidden_words_are_not_one_story(s):
    """Four shared hidden words and two private visible ones each: Jaccard 4/8 = 0.5 clears the 0.34
    join with the hidden words counted, and is 0/4 without them."""
    shared = dict.fromkeys(HIDDEN[:4], 1)
    _world(s, {
        "a": {**shared, "ballot": 1, "budget": 1},
        "b": {**shared, "border": 1, "harbour": 1},
    })
    out = build_stories(s, _P)
    assert out["stories_found"] == 0, "the two articles were joined on words the app hides"


def test_a_hidden_word_does_not_take_one_of_the_slots(s, monkeypatch):
    """Three slots, three hidden words that outrank three visible ones: the visible ones are the set."""
    monkeypatch.setattr(stories, "_TERMS_PER_ARTICLE", 3)
    arts, kws = _world(s, {"a": {**dict.fromkeys(HIDDEN[:3], 9), "ballot": 2, "budget": 2, "border": 1}})
    sets = article_keyword_sets(s, _P)
    assert sets[arts["a"]] == {kws["ballot"], kws["budget"], kws["border"]}


def test_shared_terms_never_name_a_hidden_word(s):
    _world(s, {
        "a": {"ballot": 3, "budget": 3, "border": 3, "harbour": 3, "mathcal": 1},
        "b": {"ballot": 3, "budget": 3, "border": 3, "harbour": 3, "mathcal": 1},
    })
    out = build_stories(s, _P)
    assert out["stories_found"] == 1
    assert "mathcal" not in out["stories"][0]["shared_terms"]
    assert sorted(out["stories"][0]["shared_terms"]) == sorted(VISIBLE)


def test_an_article_with_only_hidden_words_still_counts_in_the_period(s):
    """`articles_in_period` is exact: the article stays counted, is compared on nothing, and joins no story."""
    _world(s, {"a": {"mathcal": 3, "mathbf": 2}, "b": {"ballot": 1}})
    out = build_stories(s, _P)
    assert out["articles_in_period"] == 2
    assert out["articles_compared"] == 1
    assert out["stories_found"] == 0


# --------------------------------------------------------------------------------- coverage


def test_a_columns_top_terms_skip_hidden_words_even_when_they_outnumber_the_headroom(s):
    """Eight hidden words outrank every visible one and the headroom is `limit * 4` = 8 rows, so a cut
    before the filter would return nothing: the fetch has to widen."""
    spec = {f"h{i}": {w: 50 - i} for i, w in enumerate(HIDDEN)}
    spec["v"] = {"ballot": 5, "budget": 4, "border": 3}
    _world(s, spec)
    rows = _terms(s, _P, where=[], limit=2)
    assert [r["term"] for r in rows] == ["ballot", "budget"]


def test_the_widening_stops_when_the_window_has_no_more_rows(s):
    """Only hidden words in the window: an empty column, not a loop."""
    _world(s, {f"h{i}": {w: 5} for i, w in enumerate(HIDDEN)})
    assert _terms(s, _P, where=[], limit=2) == []


def test_visible_terms_keep_their_counts_when_hidden_ones_are_dropped(s):
    _world(s, {"a": {"mathcal": 40, "ballot": 7}, "b": {"ballot": 3, "mathcal": 40}})
    rows = _terms(s, _P, where=[], limit=5)
    assert [(r["term"], r["mentions"], r["articles"]) for r in rows] == [("ballot", 10, 2)]


# ---------------------------------------------------------------------------------- articles


def test_an_articles_own_keywords_are_the_best_of_what_is_left(s):
    arts, _kws = _world(s, {"a": {"mathcal": 30, "ballot": 5, "budget": 4, "border": 3}})
    got = _keywords(s, [arts["a"]], per=2)
    assert [k["term"] for k in got[arts["a"]]] == ["ballot", "budget"], "per minus the hidden ones"
