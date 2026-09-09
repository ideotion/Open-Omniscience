"""Item AC: the keyword-tag API (explore + user curation).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Exercises the /api/insights/keyword-tags endpoints directly (no TestClient) over an
in-memory corpus: read with provenance, add/remove a USER tag (reversible), input
validation, and the explore facets + keywords-by-tag queries. Counts only, no score.
"""

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.insights import (
    TagBody,
    add_keyword_tag,
    keyword_tag_facets,
    keyword_tags,
    keywords_by_tag,
    remove_keyword_tag,
)
from src.database.models import Article, Base, Keyword, KeywordMention, KeywordTag, Source


def _sess():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _seed(s):
    s.add(Source(name="Src", domain="s.test"))
    s.flush()
    a = Article(
        url="https://s.test/1", canonical_url="https://s.test/1", source_id=1,
        title="t", content="x", hash="h1",
    )
    s.add(a)
    s.flush()
    kw = Keyword(
        term="election", normalized_term="election", language="en", frequency=0, is_entity=False
    )
    s.add(kw)
    s.flush()
    s.add(KeywordMention(keyword_id=kw.id, article_id=a.id, count=3, observed_on=date.today()))
    s.add(KeywordTag(keyword_id=kw.id, axis="topic", tag="politics", source="baseline"))
    s.commit()
    return kw


def test_read_tags_with_provenance():
    s = _sess()
    _seed(s)
    r = keyword_tags(normalized="Election", db=s)  # casefolded by _n
    assert r["normalized"] == "election"
    assert r["tags"] == {"topic": ["politics"]}
    assert r["sources"] == {"topic:politics": "baseline"}


def test_add_then_remove_user_tag_is_reversible_and_idempotent():
    s = _sess()
    _seed(s)
    r = add_keyword_tag(TagBody(normalized="election", axis="type", tag="Event"), db=s)
    assert r["tags"] == {"topic": ["politics"], "type": ["event"]}  # lowercased
    add_keyword_tag(TagBody(normalized="election", axis="type", tag="event"), db=s)  # idempotent
    assert s.query(KeywordTag).filter_by(axis="type", tag="event", source="user").count() == 1
    remove_keyword_tag(TagBody(normalized="election", axis="type", tag="event"), db=s)
    assert keyword_tags(normalized="election", db=s)["tags"] == {"topic": ["politics"]}


def test_add_rejects_bad_axis_and_unknown_keyword():
    s = _sess()
    _seed(s)
    with pytest.raises(HTTPException) as e1:
        add_keyword_tag(TagBody(normalized="election", axis="colour", tag="blue"), db=s)
    assert e1.value.status_code == 400
    with pytest.raises(HTTPException) as e2:
        add_keyword_tag(TagBody(normalized="nope", axis="topic", tag="x"), db=s)
    assert e2.value.status_code == 404


def test_facets_and_keywords_by_tag():
    s = _sess()
    _seed(s)
    facets = keyword_tag_facets(db=s)["facets"]
    assert {"tag": "politics", "keywords": 1} in facets["topic"]
    assert facets["type"] == []  # empty axis still listed
    kb = keywords_by_tag(axis="topic", tag="politics", limit=50, db=s)
    assert kb["total"] == 1
    row = kb["keywords"][0]
    assert row["normalized"] == "election"
    assert row["articles"] == 1 and row["mentions"] == 3 and row["source"] == "baseline"


def test_a_keyword_tagged_by_both_the_baseline_and_the_operator_is_ONE_row():
    """The explorer listed it twice.

    ``add_keyword_tag`` de-duplicates only within ``source="user"``, so tagging a
    keyword the baseline pass already tagged writes a SECOND row -- and the listing
    grouped by ``(keyword, source)``, so it came back once per source. The per-keyword
    tag editor makes that a normal thing to do rather than a corner case.

    The counts are asserted too, because the obvious fix (group by keyword alone) is
    wrong in a way that is invisible until you look: two tag rows fan the outer join
    to mentions out, and ``sum(count)`` doubles."""
    s = _sess()
    s.add(Source(name="Src", domain="s.test"))
    s.flush()
    art = Article(url="https://x.example/a", canonical_url="https://x.example/a",
                  source_id=1, title="a", content="c", hash="h1")
    kw = Keyword(term="Berlin", normalized_term="berlin", language="en")
    s.add_all([art, kw])
    s.flush()
    s.add(KeywordMention(keyword_id=kw.id, article_id=art.id, count=7))
    s.add(KeywordTag(keyword_id=kw.id, axis="type", tag="place", source="baseline"))
    s.add(KeywordTag(keyword_id=kw.id, axis="type", tag="place", source="user"))
    s.commit()

    out = keywords_by_tag(axis="type", tag="place", limit=50, db=s)
    assert out["total"] == 1, f"one keyword must be one row, got {out['keywords']}"
    row = out["keywords"][0]
    assert row["normalized"] == "berlin"
    assert row["sources"] == ["baseline", "user"], "both assertions are true; say both"
    assert row["source"] == "baseline+user"
    assert row["mentions"] == 7, "the second tag row must not double the mention count"
    assert row["articles"] == 1


def test_a_single_source_tag_still_reads_as_that_source():
    """The neighbouring case must not be collateral damage of the fix."""
    s = _sess()
    kw = Keyword(term="Reuters", normalized_term="reuters", language="en")
    s.add(kw)
    s.flush()
    s.add(KeywordTag(keyword_id=kw.id, axis="type", tag="org", source="baseline"))
    s.commit()

    row = keywords_by_tag(axis="type", tag="org", limit=50, db=s)["keywords"][0]
    assert row["source"] == "baseline" and row["sources"] == ["baseline"]
