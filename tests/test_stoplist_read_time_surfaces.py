"""R111 step T2: a word on the stoplist disappears from the listings that never consulted it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``tests/test_stopword_batch.py`` proves the premise on ``top_terms``: a stopword shipped with an
update hides in stored keywords at read time, no user step, nothing recomputed. These tests prove
it on four more surfaces the T2 inventory found reading the keyword tables without the predicate:
the Feed card chips, the article list's top keyword, the tag explorer and the link preview. The
Insights concept map arms are in ``tests/test_concept_map.py``, which owns that fixture.

The stoplist is simulated the way the loader's output reaches the predicate, through
``filters.hidden_set``, so each test exercises the shipped ``_hidden_predicate`` rather than a
re-typed copy of its comparison. Each surface is checked BOTH ways: the word is listed before it
is stoplisted and gone after, while another word stays.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import filters
from src.database.models import Article, Base, Keyword, KeywordMention, KeywordTag, Source

SHOWN, HIDDEN = "zzharvest", "zzfurniture"


@pytest.fixture()
def stoplist(monkeypatch):
    """``stoplist(word)`` puts ``word`` on the stoplist from now on (no recompute, no restart)."""
    real = filters.hidden_set
    extra: set[str] = set()
    monkeypatch.setattr(filters, "load_settings", lambda: filters.KeywordFilter(use_builtin_stopwords=True))
    monkeypatch.setattr(filters, "hidden_set", lambda *a, **k: frozenset(real(*a, **k)) | extra)

    def _add(word: str) -> None:
        extra.add(word)

    return _add


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as s:
        s.add(Source(id=1, name="A", domain="a.test", country="fr"))
        s.commit()
        s.add(Article(id=1, url="https://a.test/1", canonical_url="https://a.test/1", source_id=1, title="t",
                      content="c", hash="h1", country="fr", language="en",
                      published_at=datetime(2024, 4, 1, tzinfo=UTC), created_at=datetime.now(UTC)))
        s.add(Keyword(id=1, term=HIDDEN, normalized_term=HIDDEN, language="en", mention_count=9, article_count=1))
        s.add(Keyword(id=2, term=SHOWN, normalized_term=SHOWN, language="en", mention_count=7, article_count=1))
        s.commit()
        s.add(KeywordMention(keyword_id=1, article_id=1, count=9, observed_on=date.today()))
        s.add(KeywordMention(keyword_id=2, article_id=1, count=7, observed_on=date.today()))
        s.add(KeywordTag(keyword_id=1, axis="topic", tag="home", source="baseline"))
        s.add(KeywordTag(keyword_id=2, axis="topic", tag="home", source="baseline"))
        s.commit()
        yield s


def test_the_feed_chips_drop_a_stoplisted_word_and_keep_the_next_best_ones(session, stoplist):
    from src.api.feed import _top_keywords

    assert [k["term"] for k in _top_keywords(session, [1])[1]] == [HIDDEN, SHOWN]
    stoplist(HIDDEN)
    assert [k["term"] for k in _top_keywords(session, [1])[1]] == [SHOWN], (
        "the stoplisted word is still a chip, or it took the other word with it"
    )


def test_the_feed_chips_filter_before_the_cut_so_the_slots_go_to_words_that_are_shown(session, stoplist, monkeypatch):
    """With one slot, the stoplisted word must not use it up: the best word that is SHOWN takes it."""
    import src.api.feed as feed

    monkeypatch.setattr(feed, "_TOP_K", 1)
    stoplist(HIDDEN)
    assert [k["term"] for k in feed._top_keywords(session, [1])[1]] == [SHOWN]


def test_the_article_lists_top_keyword_reports_none_when_it_is_stoplisted(session, stoplist):
    """The stored top keyword is a count beside a word: when the word is hidden the row reports no
    top keyword rather than the count beside a different word (the real next best waits for T3)."""
    main = pytest.importorskip("src.api.main")
    art = session.get(Article, 1)
    art.top_keyword_id, art.top_keyword_count, art.top_keyword_tied_n = 1, 9, 1
    session.commit()

    def fields():
        return main._top_keyword_fields(art, main._top_keyword_terms(session, [art]))

    assert fields()["top_keyword"] == HIDDEN
    stoplist(HIDDEN)
    assert fields() == {"top_keyword": None, "top_keyword_count": None, "top_keyword_tied_n": None}


def test_the_tag_explorer_drops_a_stoplisted_word_and_counts_what_it_shows(session, stoplist, monkeypatch):
    import src.api.insights as ins
    from src.api.insights import keywords_by_tag

    # the endpoint's own 120 s read cache would serve the first answer twice; a restart empties it
    monkeypatch.setattr(ins, "_CACHE_TTL_S", 0)

    before = keywords_by_tag(axis="topic", tag="home", limit=50, db=session)
    assert {k["normalized"] for k in before["keywords"]} == {HIDDEN, SHOWN} and before["total"] == 2
    stoplist(HIDDEN)
    after = keywords_by_tag(axis="topic", tag="home", limit=50, db=session)
    assert [k["normalized"] for k in after["keywords"]] == [SHOWN]
    assert after["total"] == 1, "the total still counts a word the listing no longer shows"


def test_the_link_preview_keywords_drop_a_stoplisted_word_and_keep_six_shown(session, stoplist):
    """The preview reads more than six and keeps the first six that are shown."""
    from src.api import link_preview

    for i in range(3, 12):
        session.add(Keyword(id=i, term=f"zzword{i}", normalized_term=f"zzword{i}", language="en",
                            mention_count=1, article_count=1))
    session.commit()
    for i in range(3, 12):
        session.add(KeywordMention(keyword_id=i, article_id=1, count=1, observed_on=date.today()))
    session.commit()
    stoplist(HIDDEN)
    kws = link_preview._local_keywords(session, 1)
    assert HIDDEN not in kws and kws[0] == SHOWN and len(kws) == 6
