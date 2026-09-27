"""The keyword resolver follows the lemma CHAIN, as the fold does (M-1 / M-4, re-walk 2026-09-27).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The fold keys a word by ``lemma_key``, which walks the lemmatiser to a fixed point: fr
``nouvelles`` -> ``nouvelle`` -> ``nouveau``. The resolver's lemma rung took ONE step, reached
``nouvelle`` (itself a row the fold had emptied) and so answered the chip counting 109 with the
emptied ``nouvelles`` row: "Resolved to nouvelles · 0 mentions in 0 articles". These rows are
built by hand to the shape the fold leaves -- two emptied husks and the live key, whose DISPLAY
term is still the surface the reader clicked -- so the test needs no fold run to reproduce it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.analytics.lemma import lemmatize, lemmatizer_available
from src.database.models import Article, Base, Keyword, KeywordMention, Source

pytestmark = pytest.mark.skipif(not lemmatizer_available(), reason="simplemma not importable here")


@pytest.fixture()
def s():
    eng = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    sess = sessionmaker(bind=eng, future=True)()
    sess.add(Source(name="S", domain="x.test", country="fr"))
    sess.flush()
    sess.add(Article(url="https://x.test/a", canonical_url="https://x.test/a", source_id=1, title="T",
                     content="c", hash="a", language="fr",
                     published_at=datetime(2026, 9, 1, tzinfo=UTC), created_at=datetime.now(UTC)))
    sess.commit()
    return sess


def _kw(s, term, norm, mentions=0):
    k = Keyword(term=term, normalized_term=norm, language="fr")
    s.add(k)
    s.flush()
    if mentions:
        s.add(KeywordMention(keyword_id=k.id, article_id=1, count=mentions, observed_on=date(2026, 9, 1)))
    s.commit()
    return k


def test_fixture_is_the_two_step_chain_the_walk_measured():
    assert lemmatize("nouvelles", "fr") == "nouvelle"
    assert lemmatize("nouvelle", "fr") == "nouveau"


def test_an_emptied_display_term_resolves_through_two_emptied_hops(s):
    _kw(s, "nouvelles", "nouvelles")          # the husk the fold emptied
    _kw(s, "nouvelle", "nouvelle")            # the next hop, emptied too
    live = _kw(s, "nouvelles", "nouveau", 109)  # the key, still wearing the clicked surface
    kw = q.resolve_keyword(s, "nouvelles", exact=True)
    assert kw is not None and kw.id == live.id
    tr = q.trend(s, "nouvelles")
    assert tr["resolved"]["normalized"] == "nouveau"
    assert tr["total"] == 109


def test_a_word_with_no_row_of_its_own_reaches_the_live_key_two_hops_away(s):
    _kw(s, "nouvelle", "nouvelle")
    live = _kw(s, "nouveau", "nouveau", 5)
    kw = q.resolve_keyword(s, "nouvelles", exact=True)
    assert kw is not None and kw.id == live.id


def test_the_nearest_live_row_wins_so_a_half_folded_corpus_keeps_its_one_step_answer(s):
    # Before a fold both forms can carry mentions; the one-step answer stays the answer.
    near = _kw(s, "cooperativa", "cooperativa", 3)
    _kw(s, "cooperativo", "cooperativo", 4)
    kw = q.resolve_keyword(s, "cooperativas", exact=True)
    assert kw is not None and kw.id == near.id


def test_a_live_keyword_is_never_swapped_for_its_lemma(s):
    kept = _kw(s, "nouvelles", "nouvelles", 2)
    _kw(s, "nouveau", "nouveau", 50)
    kw = q.resolve_keyword(s, "nouvelles", exact=True)
    assert kw is not None and kw.id == kept.id
