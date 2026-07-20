"""Keyword -> super-group reverse lookup (supergroups brief S3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import supergroup_index as idx
from src.database.models import (
    Article,
    Base,
    Keyword,
    KeywordMention,
    KeywordSuperGroup,
    KeywordSuperGroupMember,
    Source,
)


def _sess():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def setup_function(_):
    idx.invalidate()  # a stale cache from an earlier test must never leak


def test_direct_family_membership_is_found():
    s = _sess()
    sg = KeywordSuperGroup(name="People")
    s.add(sg)
    s.flush()
    s.add(KeywordSuperGroupMember(supergroup_id=sg.id, normalized_term="trump", ring_id=None))
    s.commit()

    hits = idx.supergroups_for_keyword(s, "trump")
    assert hits == [{"id": sg.id, "name": "People", "via": "family"}]


def test_family_membership_matches_via_the_same_canonical_key_s1_uses():
    """A possessive variant resolves via the SAME canonical_key match S1's
    resolve_member_keyword_ids uses (canonical_key strips a trailing possessive,
    not a plural — the plural-family merge is a separate mechanism entirely)."""
    s = _sess()
    sg = KeywordSuperGroup(name="People")
    s.add(sg)
    s.flush()
    s.add(KeywordSuperGroupMember(supergroup_id=sg.id, normalized_term="trump", ring_id=None))
    s.commit()

    hits = idx.supergroups_for_keyword(s, "trump's")
    assert hits and hits[0]["name"] == "People"


def test_ring_membership_needs_the_keywords_own_language():
    """A ring member covers a keyword only through its (language, term) — no
    language given means no ring resolution (an honest gap, never a guess)."""
    s = _sess()
    sg = KeywordSuperGroup(name="Voting")
    s.add(sg)
    s.flush()
    s.add(KeywordSuperGroupMember(supergroup_id=sg.id, normalized_term="election", ring_id="election"))
    s.commit()

    assert idx.supergroups_for_keyword(s, "élection") == []  # no language -> no ring lookup
    hits = idx.supergroups_for_keyword(s, "élection", language="fr")
    assert hits == [{"id": sg.id, "name": "Voting", "via": "ring", "ring_id": "election"}]


def test_plural_membership_returns_every_group_never_picks_one():
    """The same keyword can sit in more than one group at once (a direct family
    entry in one group AND a covering ring in another) -- both must be listed."""
    s = _sess()
    sg_direct = KeywordSuperGroup(name="Direct")
    sg_ring = KeywordSuperGroup(name="ViaRing")
    s.add_all([sg_direct, sg_ring])
    s.flush()
    s.add(KeywordSuperGroupMember(supergroup_id=sg_direct.id, normalized_term="election", ring_id=None))
    s.add(KeywordSuperGroupMember(supergroup_id=sg_ring.id, normalized_term="election", ring_id="election"))
    s.commit()

    hits = idx.supergroups_for_keyword(s, "election", language="en")
    names = {h["name"] for h in hits}
    assert names == {"Direct", "ViaRing"}
    assert len(hits) == 2  # never deduped away, never a single pick


def test_a_keyword_in_no_group_is_an_honest_empty_list():
    s = _sess()
    assert idx.supergroups_for_keyword(s, "nothing", language="en") == []


def test_cache_is_invalidated_after_a_curation_write():
    s = _sess()
    assert idx.supergroups_for_keyword(s, "trump") == []  # builds + caches the empty index

    sg = KeywordSuperGroup(name="People")
    s.add(sg)
    s.flush()
    s.add(KeywordSuperGroupMember(supergroup_id=sg.id, normalized_term="trump", ring_id=None))
    s.commit()

    # Without invalidation the STALE cached (empty) index would still say "no group".
    assert idx.supergroups_for_keyword(s, "trump") == []
    idx.invalidate()
    assert idx.supergroups_for_keyword(s, "trump") == [{"id": sg.id, "name": "People", "via": "family"}]


def test_batched_lookup_matches_the_single_lookup():
    s = _sess()
    sg = KeywordSuperGroup(name="People")
    s.add(sg)
    s.flush()
    s.add(KeywordSuperGroupMember(supergroup_id=sg.id, normalized_term="trump", ring_id=None))
    s.commit()

    batched = idx.supergroups_for_keywords(s, [("trump", "en"), ("biden", "en")])
    assert batched["trump"] == idx.supergroups_for_keyword(s, "trump", "en")
    assert batched["biden"] == []


# ---------------------------------------------------------------------------
# End-to-end: the chip actually reaches the analysis window's Keywords subtab
# (corpus-keywords) and the omnibar keyword-group rows.


def _client(tmp_path):
    from src.api.main import app
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'sgidx.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    return app, Sess


def test_corpus_keywords_endpoint_carries_the_supergroup_chip(tmp_path):
    app, Sess = _client(tmp_path)
    with Sess() as s:
        s.add(Source(name="Src", domain="s.test"))
        s.flush()
        a = Article(url="https://s.test/1", canonical_url="https://s.test/1",
                    source_id=1, title="t", content="x", hash="h1")
        s.add(a)
        s.flush()
        kw_member = Keyword(term="Trump", normalized_term="trump", language="en", frequency=0,
                             is_entity=False, mention_count=1, article_count=1)
        kw_plain = Keyword(term="widget", normalized_term="widget", language="en", frequency=0,
                            is_entity=False, mention_count=1, article_count=1)
        s.add_all([kw_member, kw_plain])
        s.flush()
        s.add(KeywordMention(keyword_id=kw_member.id, article_id=a.id, count=1, observed_on=date.today()))
        s.add(KeywordMention(keyword_id=kw_plain.id, article_id=a.id, count=1, observed_on=date.today()))
        sg = KeywordSuperGroup(name="People")
        s.add(sg)
        s.flush()
        s.add(KeywordSuperGroupMember(supergroup_id=sg.id, normalized_term="trump", ring_id=None))
        s.commit()
        article_id = a.id
        sg_id = sg.id

    idx.invalidate()
    try:
        with TestClient(app) as c:
            r = c.get(f"/api/insights/corpus-keywords?article_ids={article_id}").json()
            by_norm = {t["normalized"]: t for t in r["terms"]}
            assert by_norm["trump"]["supergroups"] == [{"id": sg_id, "name": "People", "via": "family"}]
            assert "supergroups" not in by_norm["widget"]  # never a fabricated chip
    finally:
        app.dependency_overrides.clear()


def test_omnibar_keyword_group_carries_the_supergroup_chip(tmp_path):
    app, Sess = _client(tmp_path)
    with Sess() as s:
        s.add(Keyword(term="Trump", normalized_term="trump", language="en", frequency=5,
                       is_entity=False, mention_count=1, article_count=1))
        s.add(Keyword(term="widget", normalized_term="widget", language="en", frequency=5,
                      is_entity=False, mention_count=1, article_count=1))
        sg = KeywordSuperGroup(name="People")
        s.add(sg)
        s.flush()
        s.add(KeywordSuperGroupMember(supergroup_id=sg.id, normalized_term="trump", ring_id=None))
        s.commit()
        sg_id = sg.id

    idx.invalidate()
    try:
        with TestClient(app) as c:
            r = c.get("/api/search/omni?q=tru").json()
            kw_group = next(g for g in r["groups"] if g["kind"] == "keywords")
            hit = next(it for it in kw_group["items"] if it["normalized_term"] == "trump")
            assert hit["supergroups"] == [{"id": sg_id, "name": "People", "via": "family"}]
    finally:
        app.dependency_overrides.clear()
