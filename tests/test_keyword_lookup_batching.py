"""
PR 4 / audit §9.2 item 4 — "batched keyword lookups per article".

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THESE TESTS COUNT STATEMENTS, NOT SCHEMA. "The prefetch helper exists" is exactly the
assertion that would stay green through the defect and through a fix that did nothing;
the defect WAS a statement count, so the statement count is what is pinned.

Measured before the change, on a warm apply (the field shape — the vocabulary already
stored): **98 statements for one article, 81 of them the per-term lookup**, one round
trip per kept term into `idx_keyword_normalized_term` on an 11 M-row table. After: 19
statements, one of them the batched IN (...).

The NEGATIVE TWIN matters as much as the positive one. Without it a green suite cannot
tell "the prefetch collapsed the lookups" from "they were always collapsed" — and the
second reading is the comfortable one. `test_the_default_path_is_still_one_query_per_term`
proves the per-term shape is real and still reachable, which is also what keeps every
caller that does not pass a map byte-identical.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.analytics.store as store
from src.analytics.extract import ExtractedTerm
from src.analytics.store import (
    _KEYWORD_PREFETCH_CHUNK,
    _get_or_create_keyword,
    _prefetch_keywords,
    index_article,
)
from src.database.models import Article, Base, Keyword, Source

_PER_TERM = re.compile(r"FROM keywords\b.*normalized_term = \?", re.S)
_BATCHED = re.compile(r"FROM keywords\b.*normalized_term IN ", re.S)


class _Spy:
    """Records every statement the engine executes, so a count is a measurement."""

    def __init__(self, engine):
        self.sql: list[str] = []
        self.params: list[object] = []
        self.on = False

        @event.listens_for(engine, "before_cursor_execute")
        def _before(conn, cursor, statement, parameters, context, executemany):
            if self.on:
                self.sql.append(" ".join(statement.split()))
                self.params.append(parameters)

    def count(self, rx) -> int:
        return sum(1 for s in self.sql if rx.search(s))


def _session_and_spy():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(eng)
    spy = _Spy(eng)
    s = sessionmaker(bind=eng, future=True)()
    s.add(Source(name="S", domain="s.test"))
    s.commit()
    return s, spy


class _FakeExtractor:
    name = "fake"

    def __init__(self, terms):
        self._terms = terms

    def extract(self, text, language=None, **kw):
        return list(self._terms)


def _terms(n, *, prefix="topicword"):
    return [
        ExtractedTerm(term=f"{prefix}{i}", normalized=f"{prefix}{i}", kind="term",
                      count=1, first_offset=i)
        for i in range(n)
    ]


def _article(s, h="a"):
    a = Article(url=f"https://s.test/{h}", canonical_url=f"https://s.test/{h}", source_id=1,
                title="T", content="body", hash=h, language="en",
                created_at=datetime.now(UTC))
    s.add(a)
    s.commit()
    return a


# --- the positive: one article, one query ---------------------------------- #

def test_one_article_resolves_its_whole_vocabulary_in_a_single_query():
    """The measured defect: one SELECT per kept term. Now one for the whole article."""
    s, spy = _session_and_spy()
    terms = _terms(30)
    first = _article(s, "warm")
    index_article(s, first, extractor=_FakeExtractor(terms), country=None, city=None)

    second = _article(s, "b")  # same vocabulary, already stored -> the field shape
    spy.on = True
    index_article(s, second, extractor=_FakeExtractor(terms), country=None, city=None)
    spy.on = False

    assert spy.count(_BATCHED) == 1, "the whole article's terms must resolve in ONE query"
    assert spy.count(_PER_TERM) == 0, "no per-term lookup may survive in index_article"


def test_the_batched_query_asks_for_every_kept_term_and_resolves_them_all():
    """Collapsing the queries must not collapse the ANSWER: all 30 keywords still land."""
    s, _ = _session_and_spy()
    terms = _terms(30)
    a = _article(s, "x")
    out = index_article(s, a, extractor=_FakeExtractor(terms), country=None, city=None)
    assert out["mentions"] == 30
    assert s.query(Keyword).count() == 30


# --- the negative twin: prove the per-term shape is real -------------------- #

def test_the_default_path_is_still_one_query_per_term():
    """Without a map, `_get_or_create_keyword` queries per call — unchanged, and the
    proof that the batched count above is a change rather than a coincidence."""
    s, spy = _session_and_spy()
    terms = _terms(12)
    for t in terms:  # populate
        _get_or_create_keyword(s, t, language="en", extractor="fake")
    s.commit()

    spy.on = True
    for t in terms:
        _get_or_create_keyword(s, t, language="en", extractor="fake")
    spy.on = False
    assert spy.count(_PER_TERM) == 12, "the default (prefetched=None) must stay per-term"


def test_a_prefetched_keyword_costs_no_query_at_all():
    s, spy = _session_and_spy()
    terms = _terms(12)
    for t in terms:
        _get_or_create_keyword(s, t, language="en", extractor="fake")
    s.commit()

    got = _prefetch_keywords(s, [t.normalized for t in terms])
    assert len(got) == 12
    spy.on = True
    for t in terms:
        kw = _get_or_create_keyword(s, t, language="en", extractor="fake", prefetched=got)
        assert kw.normalized_term == t.normalized
    spy.on = False
    assert spy.count(_PER_TERM) == 0 and spy.count(_BATCHED) == 0


# --- the map is the authority for the rest of the article ------------------- #

def test_a_keyword_created_through_the_map_is_reused_without_a_second_query():
    """Two ExtractedTerms sharing a normalized form must resolve to ONE keyword. The
    per-term path got that from the database; the map has to write back to get it."""
    s, spy = _session_and_spy()
    t1 = ExtractedTerm(term="Alpha", normalized="alpha", kind="term", count=1, first_offset=0)
    t2 = ExtractedTerm(term="ALPHA", normalized="alpha", kind="term", count=2, first_offset=9)
    empty: dict[str, Keyword] = {}

    first = _get_or_create_keyword(s, t1, language="en", extractor="fake", prefetched=empty)
    spy.on = True
    again = _get_or_create_keyword(s, t2, language="en", extractor="fake", prefetched=empty)
    spy.on = False

    assert again is first, "the second occurrence must reuse the keyword just created"
    assert spy.count(_PER_TERM) == 0, "and must not go back to the database for it"
    assert s.query(Keyword).filter_by(normalized_term="alpha").count() == 1


def test_the_entity_upgrade_still_happens_through_the_map():
    """A term first seen lowercase, later recognised as an entity, still upgrades —
    the map changed where the keyword comes from, never what happens to it."""
    s, _ = _session_and_spy()
    plain = ExtractedTerm(term="paris", normalized="paris", kind="term", count=1, first_offset=0)
    named = ExtractedTerm(term="Paris", normalized="paris", kind="place", count=1, first_offset=5)
    m: dict[str, Keyword] = {}
    kw = _get_or_create_keyword(s, plain, language="en", extractor="fake", prefetched=m)
    assert kw.is_entity is False
    again = _get_or_create_keyword(s, named, language="en", extractor="fake", prefetched=m)
    assert again is kw and again.is_entity is True and again.entity_type == "place"


# --- the things the prefetch must NOT do ------------------------------------ #

def test_a_suppressed_self_name_never_reaches_the_prefetch_query():
    """The prefetch must ask for exactly the terms the loop will keep. A source
    self-name is dropped by the loop, so asking for it would both widen the query and
    warm a row this article has no business touching."""
    s, spy = _session_and_spy()
    src = s.query(Source).one()
    src.name = "Correctiv"
    s.commit()
    terms = [
        ExtractedTerm(term="CORRECTIV", normalized="correctiv", kind="org", count=1, first_offset=0),
        ExtractedTerm(term="budget", normalized="budget", kind="term", count=1, first_offset=9),
    ]
    a = _article(s, "self")
    a.source = src
    spy.on = True
    out = index_article(s, a, extractor=_FakeExtractor(terms), country=None, city=None)
    spy.on = False

    assert out["self_name_suppressed"] == 1
    asked = [p for stmt, p in zip(spy.sql, spy.params, strict=True) if _BATCHED.search(stmt)]
    flat = [str(v) for params in asked for v in (params or ())]
    assert "budget" in flat
    assert "correctiv" not in flat, "a suppressed self-name must not be asked for"


def test_the_prefetch_chunks_rather_than_outgrowing_the_parameter_ceiling(monkeypatch):
    """SQLite binds a bounded number of parameters. One article never approaches it,
    but the helper must not be the reason a larger caller breaks.

    THE FIXTURE SIZE IS A LITERAL, NOT THE CONSTANT. Sizing the input as
    ``_KEYWORD_PREFETCH_CHUNK + 7`` is self-referential: raise the constant and the
    fixture rises with it, so the test can only ever confirm the constant agrees with
    itself. Caught by mutation — lifting the ceiling to 100,000 left this GREEN (and
    took 86 s, because it built 100,007 keywords to do it). The chunk size is patched
    to a small literal here so the BEHAVIOUR is what is measured; the production value
    is pinned separately below.
    """
    s, spy = _session_and_spy()
    monkeypatch.setattr(store, "_KEYWORD_PREFETCH_CHUNK", 10)
    terms = _terms(25, prefix="w")
    for t in terms:
        _get_or_create_keyword(s, t, language="en", extractor="fake")
    s.commit()

    spy.on = True
    got = _prefetch_keywords(s, [t.normalized for t in terms])
    spy.on = False
    assert len(got) == 25, "every term must still be resolved"
    assert spy.count(_BATCHED) == 3, "25 terms at 10 per chunk is three statements"


def test_the_production_chunk_stays_under_sqlites_historical_parameter_floor():
    """The value itself, pinned against a literal. SQLITE_MAX_VARIABLE_NUMBER is 32,766
    on modern builds but 999 on anything older, and the store is a bundled SQLCipher
    whose build is not ours to assume. A chunk above that floor would fail only on
    someone else's machine, with a corpus large enough to reach it."""
    assert _KEYWORD_PREFETCH_CHUNK <= 900


def test_the_prefetch_ignores_empty_terms_and_duplicates():
    """Asserted on the BOUND PARAMETERS, not on the result.

    Both guards are invisible in the output: a duplicate resolves to the same row and
    an empty string matches nothing, so a result-only assertion passes whether or not
    either filter exists — confirmed by mutation, which removed the empty-term filter
    and left an output-only version of this test green. What the filters actually do is
    keep the query from asking, so that is what is measured.
    """
    s, spy = _session_and_spy()
    _get_or_create_keyword(
        s, ExtractedTerm(term="x", normalized="x", kind="term", count=1, first_offset=0),
        language="en", extractor="fake",
    )
    s.commit()
    spy.on = True
    got = _prefetch_keywords(s, ["x", "x", "", "x"])
    spy.on = False
    assert list(got) == ["x"]
    assert spy.count(_BATCHED) == 1

    asked = [p for stmt, p in zip(spy.sql, spy.params, strict=True) if _BATCHED.search(stmt)]
    flat = [str(v) for params in asked for v in (params or ())]
    assert flat == ["x"], f"the query must ask for 'x' once and nothing else, got {flat}"


# --- which row, when several share a term: the LOWEST id -------------------- #
#
# `keywords.normalized_term` is deliberately not unique: the restore merge keys a keyword
# on term AND language, so every multilingual merge leaves rows sharing a term, while the
# indexer looks a term up by the term alone. The 2026-07-29 keyword-cache ruling (ruling 5)
# required a deterministic MIN(id) tie-break for exactly this case.
#
# PR 4 broke it: the prefetch assigned every result row into its dict, so the LAST row won
# -- the HIGHEST id, because SQLite returns an equal-key range in rowid order. Measured: for
# three rows sharing "foo", the per-term lookup answered 1 and the prefetch answered 3.
# Every test below fails on that code.

def _shared_term(s, languages=("en", "fr", "de")):
    """Rows sharing one normalized term -- the shape a multilingual merge leaves."""
    for lang in languages:
        s.add(Keyword(term="foo", normalized_term="foo", language=lang, frequency=0))
    s.add(Keyword(term="bar", normalized_term="bar", language="en", frequency=0))
    s.commit()
    return [k.id for k in s.query(Keyword).filter_by(normalized_term="foo").order_by(Keyword.id)]


def test_the_prefetch_resolves_a_shared_term_to_its_lowest_id():
    s, _ = _session_and_spy()
    ids = _shared_term(s)
    assert len(ids) == 3
    got = _prefetch_keywords(s, ["foo", "bar"])
    assert got["foo"].id == min(ids), (
        f"a term shared by rows {ids} must resolve to the lowest id (ruling 5), "
        f"got {got['foo'].id}"
    )


def test_both_lookup_paths_agree_on_a_shared_term():
    """The batched path replaced the per-term one for index_article; the two must give
    the same answer, or the switch silently moved every shared term's mentions."""
    s, _ = _session_and_spy()
    _shared_term(s)
    t = ExtractedTerm(term="foo", normalized="foo", kind="term", count=1, first_offset=0)
    per_term = _get_or_create_keyword(s, t, language="en", extractor="fake")
    batched = _get_or_create_keyword(
        s, t, language="en", extractor="fake", prefetched=_prefetch_keywords(s, ["foo"])
    )
    assert batched.id == per_term.id


def test_index_article_attaches_a_shared_terms_mentions_to_the_lowest_id():
    """The behaviour, not the helper: which row the MENTION lands on. This is where the
    defect did its damage -- a helper-level assertion can stay green while the caller
    stops using the helper, which is PR 5's recorded lesson."""
    from src.database.models import KeywordMention

    s, _ = _session_and_spy()
    ids = _shared_term(s)
    a = _article(s, "shared")
    terms = [ExtractedTerm(term="foo", normalized="foo", kind="term", count=4, first_offset=0)]
    index_article(s, a, extractor=_FakeExtractor(terms), country=None, city=None)
    landed = [m.keyword_id for m in s.query(KeywordMention).filter_by(article_id=a.id)]
    assert landed == [min(ids)], f"the mention must land on {min(ids)}, landed on {landed}"


def test_a_shared_term_keeps_landing_on_one_row_across_articles():
    """The symptom as an operator would meet it: one term, two articles, two rows. Before
    the fix an article indexed by the per-term path and one indexed by the prefetch split
    the same term across rows 1 and 3, and the term's count with them."""
    from src.database.models import KeywordMention

    s, _ = _session_and_spy()
    ids = _shared_term(s)
    t = ExtractedTerm(term="foo", normalized="foo", kind="term", count=1, first_offset=0)
    first = _get_or_create_keyword(s, t, language="en", extractor="fake")  # per-term path
    a = _article(s, "later")
    index_article(s, a, extractor=_FakeExtractor([t]), country=None, city=None)
    rows = {m.keyword_id for m in s.query(KeywordMention).filter_by(article_id=a.id)}
    assert rows == {first.id} == {min(ids)}
