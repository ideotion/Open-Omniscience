"""Super-rings: a super-group member can be a cross-language RING (Step 2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Drives the super-group endpoints directly (no TestClient) over an in-memory corpus:
a ring member aggregates mentions across ALL the ring's languages (the super-ring
model), an unknown ring is rejected, and plain family members still work.
"""

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.insights import SuperGroupMembers, add_supergroup_members, list_supergroups
from src.database.models import (
    Article,
    Base,
    Keyword,
    KeywordMention,
    KeywordSuperGroup,
    Source,
)


def _sess():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _kw_with_mentions(s, article, term, norm, lang, count):
    # mention_count/article_count are denormalised counters maintained at index time
    # in production; one mention of `count` in one article -> (count, 1).
    k = Keyword(
        term=term, normalized_term=norm, language=lang, frequency=0, is_entity=False,
        mention_count=count, article_count=1,
    )
    s.add(k)
    s.flush()
    s.add(KeywordMention(keyword_id=k.id, article_id=article.id, count=count, observed_on=date.today()))


def _article(s):
    s.add(Source(name="Src", domain="s.test"))
    s.flush()
    a = Article(
        url="https://s.test/1", canonical_url="https://s.test/1", source_id=1,
        title="t", content="x", hash="h1",
    )
    s.add(a)
    s.flush()
    return a


def test_super_ring_member_aggregates_across_languages():
    s = _sess()
    a = _article(s)
    # the real 'election' ring spans en:election / fr:élection / de:wahl / ...
    _kw_with_mentions(s, a, "election", "election", "en", 5)
    _kw_with_mentions(s, a, "élection", "élection", "fr", 5)
    _kw_with_mentions(s, a, "Wahl", "wahl", "de", 5)
    sg = KeywordSuperGroup(name="Voting")
    s.add(sg)
    s.commit()

    r = add_supergroup_members(sg.id, SuperGroupMembers(rings=["election"]), db=s)
    assert "election" in r["added"]

    voting = next(x for x in list_supergroups(db=s)["supergroups"] if x["name"] == "Voting")
    member = voting["members"][0]
    assert member["ring_id"] == "election"
    assert {"en:election", "fr:élection", "de:wahl"} <= set(member["ring_members"])
    assert member["mentions"] == 15  # 5 + 5 + 5, aggregated across the ring's languages


def test_unknown_ring_is_rejected():
    s = _sess()
    sg = KeywordSuperGroup(name="X")
    s.add(sg)
    s.commit()
    with pytest.raises(HTTPException) as e:
        add_supergroup_members(sg.id, SuperGroupMembers(rings=["definitely-not-a-ring"]), db=s)
    assert e.value.status_code == 400


def test_plain_family_member_still_works():
    s = _sess()
    a = _article(s)
    _kw_with_mentions(s, a, "Trump", "trump", "en", 7)
    sg = KeywordSuperGroup(name="People")
    s.add(sg)
    s.commit()
    add_supergroup_members(sg.id, SuperGroupMembers(normalized=["Trump"]), db=s)
    member = next(x for x in list_supergroups(db=s)["supergroups"] if x["name"] == "People")["members"][0]
    assert member["normalized"] == "trump" and member["mentions"] == 7
    assert "ring_id" not in member  # a family member carries no ring expansion
