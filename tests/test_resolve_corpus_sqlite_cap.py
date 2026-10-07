"""Audit finding 2026-07-17: several downstream analytics functions
(corpus_keywords, corpus_www, corpus_sentiment, corpus_sources,
corpus_facet_article_ids, who_aggregate, where_aggregate -- src/analytics/queries.py)
filter with an UNCHUNKED ``X.article_id.in_(article_ids)``. The corpus-* endpoints
accept ``cap`` up to 5000 (some up to 20000) -- well past SQLite's historical ~999
bound-variable ceiling. A Home card carrying an explicit, large ``article_ids`` set
(diet_self_audit/capacity_implausible can now carry up to 2000, per an earlier fix
this same audit session) or a plain search with a high ``cap`` would make the
downstream query raise "OperationalError: too many SQL variables" instead of an
honest result. ``_resolve_corpus`` -- the ONE shared resolver every corpus-*
endpoint funnels through -- now clamps ``cap`` to a SQLite-safe bound regardless of
what the caller requested.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.insights import _SQLITE_SAFE_IN_CAP, _resolve_corpus
from src.database.models import Article, Base
from src.database.stand_in import ARTICLE_REASON


@pytest.fixture()
def db():
    """An empty store: an explicit id set names its ids whether or not a row exists, but the resolver now asks the articles table which of them
    is a stand-in (the place-holder a salvage copy writes at a lost id), so it needs a session to ask."""
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    yield session
    session.close()
    engine.dispose()


def test_explicit_article_ids_are_clamped_to_the_sqlite_safe_cap_even_with_a_higher_requested_cap(db):
    many_ids = ",".join(str(i) for i in range(1, 2001))  # 2000 explicit ids
    ids, total = _resolve_corpus(
        db, many_ids, query=None, source=None, start_date=None, end_date=None,
        language=None, tags=None, cap=2000,  # the endpoint's own declared le=5000 range
    )
    assert len(ids) == _SQLITE_SAFE_IN_CAP
    assert len(ids) <= 900  # the value used everywhere else in the codebase for this bound
    assert total == 2000  # the TRUE requested size is still disclosed (capped = total > len(ids))
    assert ids == list(range(1, _SQLITE_SAFE_IN_CAP + 1))  # order-preserving, first N kept


def test_explicit_article_ids_under_the_safe_cap_are_unaffected(db):
    few_ids = "5,3,9,3,1"  # includes a duplicate, deliberately unsorted
    ids, total = _resolve_corpus(
        db, few_ids, query=None, source=None, start_date=None, end_date=None,
        language=None, tags=None, cap=900,
    )
    assert ids == [5, 3, 9, 1]  # deduped, order-preserving, nothing clamped
    assert total == 4


def test_a_stand_in_named_in_an_explicit_set_is_dropped_before_the_cap_and_the_total(db):
    """The stand-in is no article of the set: it takes no place under the cap and is not in the total (dropped after them it would leave the set
    one short of the cap and the total one too large)."""
    db.add(Article(id=5, url="(lost articles 5)", canonical_url="(lost articles 5)", source_id=1, content="", hash="h5", quarantined=True, quarantine_reason=ARTICLE_REASON))
    db.add(Article(id=6, url="https://e.org/6", canonical_url="https://e.org/6", source_id=1, content="", hash="h6", quarantined=True, quarantine_reason="link list"))
    db.commit()
    named = ",".join(str(i) for i in range(1, 1001))  # 1000 explicit ids, the fifth is the stand-in
    ids, total = _resolve_corpus(
        db, named, query=None, source=None, start_date=None, end_date=None,
        language=None, tags=None, cap=2000,
    )
    assert 5 not in ids and 6 in ids  # a link list is a real row, and stays
    assert ids == [i for i in range(1, 902) if i != 5][:_SQLITE_SAFE_IN_CAP], ids[:8]
    assert total == 999


def test_sqlite_safe_cap_constant_matches_the_repo_wide_convention():
    assert _SQLITE_SAFE_IN_CAP == 900
