"""
C13 (2026-07-24 throughput brief, A3): index_article's mention rows are now
written via ONE bulk Core INSERT instead of N individually ORM-tracked adds.

Mandatory negative-space coverage: counters after a bulk-insert index EXACTLY
match a live GROUP BY (zero drift); the delete-then-reinsert epoch is
idempotent (re-indexing the SAME article reproduces the exact same counts --
the project's own "double-count" lesson, guarded here against the new write
path specifically); and a mid-batch failure (a genuine UNIQUE-constraint
collision within one bulk INSERT) is caught cleanly and a subsequent retry
recovers with exact counts -- nothing is silently corrupted or lost.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import ExtractedTerm
from src.analytics.store import index_article
from src.database.models import Article, Base, Keyword, KeywordMention, Source


class _FakeExtractor:
    """An injectable extractor returning a FIXED list of ExtractedTerm objects,
    so a test controls exactly which (keyword, count) pairs index_article must
    resolve and bulk-insert -- no real NLP needed."""

    name = "fake"

    def __init__(self, terms: list[ExtractedTerm]):
        self._terms = terms

    def extract(self, text, *, title="", language="en"):
        return self._terms


@pytest.fixture()
def session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 't.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    s = Sess()
    yield s
    s.close()


@pytest.fixture()
def source(session):
    src = Source(name="Test Source", domain="test.example")
    session.add(src)
    session.commit()
    return src


def _article(session, source, *, url="https://test.example/a", content_len=500):
    a = Article(
        url=url, canonical_url=url, source_id=source.id, title="T",
        content="x" * content_len, hash=url, language="en",
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    session.add(a)
    session.commit()
    return a


def _live_counter_group_by(session) -> dict[int, tuple[int, int]]:
    """The authoritative (mention_count, article_count) per keyword, computed
    directly from keyword_mentions -- the ground truth the denormalised
    Keyword counters must always match."""
    rows = (
        session.query(
            KeywordMention.keyword_id,
            func.sum(KeywordMention.count),
            func.count(func.distinct(KeywordMention.article_id)),
        )
        .group_by(KeywordMention.keyword_id)
        .all()
    )
    return {kid: (int(total or 0), int(n_art or 0)) for kid, total, n_art in rows}


def _assert_counters_match_live_group_by(session):
    live = _live_counter_group_by(session)
    for kw in session.query(Keyword).all():
        expected_men, expected_art = live.get(kw.id, (0, 0))
        assert kw.mention_count == expected_men, (
            f"keyword {kw.normalized_term!r}: mention_count {kw.mention_count} "
            f"!= live GROUP BY {expected_men}"
        )
        assert kw.article_count == expected_art, (
            f"keyword {kw.normalized_term!r}: article_count {kw.article_count} "
            f"!= live GROUP BY {expected_art}"
        )


def test_bulk_inserted_mentions_carry_every_field(session, source):
    a = _article(session, source)
    terms = [ExtractedTerm(term="Widget", normalized="widget", kind="term", count=3, first_offset=7)]
    index_article(session, a, extractor=_FakeExtractor(terms), country="US", city="Springfield")

    m = session.query(KeywordMention).filter_by(article_id=a.id).one()
    assert m.count == 3
    assert m.first_offset == 7
    assert m.country == "us"  # normalize_country canonicalises to lowercase ISO-2
    assert m.city == "Springfield"
    assert m.source_id == source.id
    assert m.extractor == "fake"
    assert m.created_at is not None
    assert m.id is not None  # autoincrement PK assigned correctly by the bulk path


def test_counters_after_a_bulk_insert_match_the_live_group_by(session, source):
    terms = [
        ExtractedTerm(term="Alpha", normalized="alpha", kind="term", count=2, first_offset=0),
        ExtractedTerm(term="Beta", normalized="beta", kind="term", count=5, first_offset=1),
    ]
    a1 = _article(session, source, url="https://test.example/1")
    index_article(session, a1, extractor=_FakeExtractor(terms), country=None, city=None)

    a2 = _article(session, source, url="https://test.example/2")
    terms2 = [
        ExtractedTerm(term="Beta", normalized="beta", kind="term", count=1, first_offset=0),
        ExtractedTerm(term="Gamma", normalized="gamma", kind="term", count=4, first_offset=2),
    ]
    index_article(session, a2, extractor=_FakeExtractor(terms2), country=None, city=None)

    _assert_counters_match_live_group_by(session)
    beta = session.query(Keyword).filter_by(normalized_term="beta").one()
    assert beta.mention_count == 6  # 5 (a1) + 1 (a2)
    assert beta.article_count == 2  # present in both articles


def test_reindex_the_same_article_is_idempotent_no_double_count(session, source):
    """The 'delete-then-reinsert epoch' lesson, guarded against the new bulk
    write path specifically: re-indexing the SAME article must NOT
    double-count its contribution to any keyword's counters."""
    a = _article(session, source)
    terms = [
        ExtractedTerm(term="Alpha", normalized="alpha", kind="term", count=3, first_offset=0),
        ExtractedTerm(term="Beta", normalized="beta", kind="term", count=2, first_offset=1),
    ]
    extractor = _FakeExtractor(terms)
    index_article(session, a, extractor=extractor, country=None, city=None)
    after_first = {
        kw.normalized_term: (kw.mention_count, kw.article_count)
        for kw in session.query(Keyword).all()
    }

    # Re-index the SAME article with the SAME terms (idempotent re-index).
    index_article(session, a, extractor=extractor, country=None, city=None)
    after_second = {
        kw.normalized_term: (kw.mention_count, kw.article_count)
        for kw in session.query(Keyword).all()
    }

    assert after_first == after_second, "a re-index must not change counters at all"
    assert session.query(KeywordMention).filter_by(article_id=a.id).count() == 2
    _assert_counters_match_live_group_by(session)


def test_reindex_with_changed_terms_reflects_only_the_net_change(session, source):
    a = _article(session, source)
    index_article(
        session, a,
        extractor=_FakeExtractor(
            [ExtractedTerm(term="Alpha", normalized="alpha", kind="term", count=3, first_offset=0)]
        ),
        country=None, city=None,
    )
    # Re-index with a DIFFERENT term set: "alpha" drops out, "beta" appears.
    index_article(
        session, a,
        extractor=_FakeExtractor(
            [ExtractedTerm(term="Beta", normalized="beta", kind="term", count=4, first_offset=0)]
        ),
        country=None, city=None,
    )
    alpha = session.query(Keyword).filter_by(normalized_term="alpha").one()
    beta = session.query(Keyword).filter_by(normalized_term="beta").one()
    assert alpha.mention_count == 0 and alpha.article_count == 0  # net change: -3 / -1
    assert beta.mention_count == 4 and beta.article_count == 1
    _assert_counters_match_live_group_by(session)


def test_a_mid_batch_collision_raises_and_a_clean_retry_recovers_exactly(session, source):
    """Simulates a genuine UNIQUE-constraint collision WITHIN one article's
    bulk INSERT (two ExtractedTerm objects that resolve to the SAME keyword
    id -- a hypothetical extractor defect, never expected in practice, but
    the property under test is that the failure is caught cleanly and a
    subsequent clean retry recovers with EXACT counts, never a corrupted or
    doubled state)."""
    a = _article(session, source)

    # Pre-create the "alpha" keyword so BOTH ExtractedTerm entries resolve to
    # the SAME kw.id via _get_or_create_keyword's normal lookup -- producing
    # two mention_rows dicts with the identical (keyword_id, article_id) pair,
    # which the unique index ix_mention_keyword_article must refuse.
    colliding_terms = [
        ExtractedTerm(term="Alpha", normalized="alpha", kind="term", count=1, first_offset=0),
        ExtractedTerm(term="ALPHA", normalized="alpha", kind="term", count=2, first_offset=5),
    ]
    with pytest.raises(IntegrityError):
        index_article(session, a, extractor=_FakeExtractor(colliding_terms), country=None, city=None)
    session.rollback()  # the caller's own recovery step (mirrors batch.py's redo path)

    # A clean retry with NON-colliding terms must succeed and produce EXACT
    # counts -- the failed attempt left nothing behind to corrupt this one.
    index_article(
        session, a,
        extractor=_FakeExtractor(
            [ExtractedTerm(term="Alpha", normalized="alpha", kind="term", count=3, first_offset=0)]
        ),
        country=None, city=None,
    )
    assert session.query(KeywordMention).filter_by(article_id=a.id).count() == 1
    alpha = session.query(Keyword).filter_by(normalized_term="alpha").one()
    assert alpha.mention_count == 3 and alpha.article_count == 1
    _assert_counters_match_live_group_by(session)
