"""Cross-language equivalence ring → coverage by SOURCE country (de-US-centring lens).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The trans-language layer merges a concept across languages; this multi-perspective
view splits that ONE concept's coverage by the producing source's country — counts
only, no score, language-qualified membership (no fabricated merge), unlocated sources
bucketed honestly as null.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.database.models import Article, Base, Keyword, KeywordMention, Source


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()


def _ring():
    """A small two-language ring built directly so the test doesn't depend on the
    shipped catalog's exact contents (the loader is tested elsewhere)."""
    from src.analytics import equivalence
    return equivalence.Ring(id="testconcept", members=(("en", "alpha"), ("fr", "alpha")))


def _add_kw_mention(db, *, term, language, source, n=1):
    kw = db.query(Keyword).filter_by(normalized_term=term, language=language).first()
    if not kw:
        kw = Keyword(term=term, normalized_term=term, language=language)
        db.add(kw); db.flush()
    art = Article(
        url=f"https://{source.domain}/{term}-{language}-{n}",
        canonical_url=f"https://{source.domain}/{term}-{language}-{n}",
        source_id=source.id, title="T", content="x", hash=f"{term}-{language}-{source.domain}-{n}",
        language=language, created_at=datetime.now(UTC),
        published_at=datetime.now(UTC),
    )
    db.add(art); db.flush()
    db.add(KeywordMention(keyword_id=kw.id, article_id=art.id, count=n))
    db.commit()


def test_ring_country_split_groups_by_source_country(db, monkeypatch):
    from src.analytics import equivalence
    ring = _ring()
    # Make the equivalence index resolve our test ring.
    monkeypatch.setattr(equivalence, "ring_meta", lambda rid: ring if rid == "testconcept" else None)
    monkeypatch.setattr(equivalence, "ring_of",
                        lambda lang, norm: "testconcept" if (lang, norm) in ring.members else None)

    us = Source(name="US Src", domain="us.test", country="us"); db.add(us)
    fr = Source(name="FR Src", domain="fr.test", country="fr"); db.add(fr)
    un = Source(name="Unlocated", domain="x.test", country=None); db.add(un)
    db.commit()

    # English "alpha" from a US source; French "alpha" from a FR source; both ring members.
    _add_kw_mention(db, term="alpha", language="en", source=us, n=5)
    _add_kw_mention(db, term="alpha", language="fr", source=fr, n=3)
    _add_kw_mention(db, term="alpha", language="en", source=un, n=2)
    # A non-member keyword must NOT count toward the ring.
    _add_kw_mention(db, term="beta", language="en", source=us, n=9)

    out = q.ring_country_split(db, ring_id="testconcept")
    assert out["found"] is True and out["n_keywords"] >= 2
    by_country = {c["country"]: c for c in out["countries"]}
    assert by_country["us"]["mentions"] == 5 and by_country["us"]["articles"] == 1
    assert by_country["fr"]["mentions"] == 3
    assert by_country[None]["mentions"] == 2  # unlocated bucketed as null, not dropped
    # beta (non-member) excluded -> no country has its 9 mentions.
    assert all(c["mentions"] != 9 for c in out["countries"])
    # Honesty: no score field anywhere.
    for c in out["countries"]:
        assert not any("score" in k for k in c)
    assert "never a credibility ranking or score" in out["caveat"]


def test_ring_country_split_unknown_ring(db):
    out = q.ring_country_split(db, ring_id="nope-not-a-ring-xyz")
    assert out["found"] is False and out["countries"] == []


def test_ring_country_split_excludes_no_language_keywords(db, monkeypatch):
    from src.analytics import equivalence
    ring = _ring()
    monkeypatch.setattr(equivalence, "ring_meta", lambda rid: ring if rid == "testconcept" else None)
    monkeypatch.setattr(equivalence, "ring_of",
                        lambda lang, norm: "testconcept" if (lang and (lang, norm) in ring.members) else None)
    us = Source(name="US", domain="us.test", country="us"); db.add(us); db.commit()
    # A keyword with NULL language must be excluded (conservative — never fabricated).
    _add_kw_mention(db, term="alpha", language=None, source=us, n=4)
    out = q.ring_country_split(db, ring_id="testconcept")
    assert out["n_keywords"] == 0 and out["countries"] == []


# --------------------------------------------------------------------------- #
# ring_country_article_ids — the concept-map §D drill (a country cell -> the
# exact articles behind it, incl. the "not mapped" bucket).
# --------------------------------------------------------------------------- #


def _article_id(db, *, term, language, domain, n=1):
    from src.database.models import Article as _Article
    return db.query(_Article.id).filter_by(hash=f"{term}-{language}-{domain}-{n}").scalar()


def test_ring_country_article_ids_matches_the_exact_country_cell(db, monkeypatch):
    from src.analytics import equivalence
    ring = _ring()
    monkeypatch.setattr(equivalence, "ring_meta", lambda rid: ring if rid == "testconcept" else None)
    monkeypatch.setattr(equivalence, "ring_of",
                        lambda lang, norm: "testconcept" if (lang, norm) in ring.members else None)

    us = Source(name="US Src", domain="us.test", country="us"); db.add(us)
    fr = Source(name="FR Src", domain="fr.test", country="fr"); db.add(fr)
    db.commit()

    _add_kw_mention(db, term="alpha", language="en", source=us, n=5)
    _add_kw_mention(db, term="alpha", language="fr", source=fr, n=3)
    # A non-member keyword in the SAME country must never leak into the drill.
    _add_kw_mention(db, term="beta", language="en", source=us, n=9)

    us_art = _article_id(db, term="alpha", language="en", domain="us.test", n=5)
    fr_art = _article_id(db, term="alpha", language="fr", domain="fr.test", n=3)
    beta_art = _article_id(db, term="beta", language="en", domain="us.test", n=9)

    us_out = q.ring_country_article_ids(db, ring_id="testconcept", country="us")
    assert us_out["found"] is True
    assert us_out["article_ids"] == [us_art]
    assert beta_art not in us_out["article_ids"]

    fr_out = q.ring_country_article_ids(db, ring_id="testconcept", country="fr")
    assert fr_out["article_ids"] == [fr_art]

    # No score anywhere in the payload.
    assert not any("score" in k for k in us_out)


def test_ring_country_article_ids_unlocated_bucket_is_drillable(db, monkeypatch):
    from src.analytics import equivalence
    ring = _ring()
    monkeypatch.setattr(equivalence, "ring_meta", lambda rid: ring if rid == "testconcept" else None)
    monkeypatch.setattr(equivalence, "ring_of",
                        lambda lang, norm: "testconcept" if (lang, norm) in ring.members else None)
    un = Source(name="Unlocated", domain="x.test", country=None); db.add(un); db.commit()
    _add_kw_mention(db, term="alpha", language="en", source=un, n=2)
    un_art = _article_id(db, term="alpha", language="en", domain="x.test", n=2)

    # country=None resolves the SAME "not mapped" bucket ring_country_split reports
    # -- never a silent drop of the (often largest) unlocated bucket.
    out = q.ring_country_article_ids(db, ring_id="testconcept", country=None)
    assert out["found"] is True
    assert out["article_ids"] == [un_art]


def test_ring_country_article_ids_unknown_ring(db):
    out = q.ring_country_article_ids(db, ring_id="nope-not-a-ring-xyz", country="us")
    assert out["found"] is False and out["article_ids"] == []


def test_ring_country_article_ids_bounded_and_disclosed(db, monkeypatch):
    from src.analytics import equivalence
    ring = _ring()
    monkeypatch.setattr(equivalence, "ring_meta", lambda rid: ring if rid == "testconcept" else None)
    monkeypatch.setattr(equivalence, "ring_of",
                        lambda lang, norm: "testconcept" if (lang, norm) in ring.members else None)
    us = Source(name="US Src", domain="us.test", country="us"); db.add(us); db.commit()
    for i in range(1, 6):
        _add_kw_mention(db, term="alpha", language="en", source=us, n=i)

    out = q.ring_country_article_ids(db, ring_id="testconcept", country="us", limit=3)
    assert out["bounded"] is True
    assert out["total"] == 3
    assert len(out["article_ids"]) == 3

    out_full = q.ring_country_article_ids(db, ring_id="testconcept", country="us", limit=100)
    assert out_full["bounded"] is False
    assert out_full["total"] == 5


# --------------------------------------------------------------------------- #
# The country LIST is bounded; the country COUNT never is, and the "not mapped"
# bucket is never one of the rows the bound drops (anti-capping + §D, 2026-07-18).
# --------------------------------------------------------------------------- #


def _seed_many_countries(db, monkeypatch, *, n_located, located_articles, unlocated_articles):
    """`n_located` located countries with `located_articles` articles each, plus one
    unlocated source. Every located bucket is deliberately BIGGER than the unlocated
    one, so the ordering puts the unlocated row last — the arrangement in which a
    plain ``rows[:limit]`` drops exactly the bucket the §D ruling says must stay
    reachable. A fixture where the unlocated bucket is the largest (its usual field
    shape) cannot discriminate: it survives any limit and the guard passes for free.
    """
    from src.analytics import equivalence
    ring = _ring()
    monkeypatch.setattr(equivalence, "ring_meta", lambda rid: ring if rid == "testconcept" else None)
    monkeypatch.setattr(equivalence, "ring_of",
                        lambda lang, norm: "testconcept" if (lang, norm) in ring.members else None)
    for i in range(n_located):
        s = Source(name=f"S{i}", domain=f"s{i}.test", country=f"c{i:02d}")
        db.add(s); db.commit()
        for k in range(located_articles):
            _add_kw_mention(db, term="alpha", language="en", source=s, n=k + 1)
    un = Source(name="Unlocated", domain="un.test", country=None)
    db.add(un); db.commit()
    for k in range(unlocated_articles):
        _add_kw_mention(db, term="alpha", language="en", source=un, n=k + 1)


def test_the_not_mapped_bucket_survives_the_country_limit(db, monkeypatch):
    """The unlocated bucket is split out BEFORE the limit, so it is reachable however
    many countries carry the concept. It used to be ordered like any other row and
    survived only because it happened to be the largest."""
    _seed_many_countries(db, monkeypatch, n_located=6, located_articles=3, unlocated_articles=1)

    out = q.ring_country_split(db, ring_id="testconcept", limit=3)
    unlocated = [c for c in out["countries"] if c["country"] is None]
    assert len(unlocated) == 1, (
        "the 'not mapped' bucket must ride every payload — it is the clickable drill "
        "the §D ruling names, and dropping it makes it a dead end"
    )
    assert unlocated[0]["articles"] == 1
    # The located side really was cut, so the assertion above is about the split and
    # not about a fixture that happened to fit under the limit.
    assert len([c for c in out["countries"] if c["country"]]) == 3


def test_the_reported_country_count_is_never_the_cap(db, monkeypatch):
    """Anti-capping: a cap may bound which countries are LISTED, never the number
    reported. ``n_countries`` is the exact located total; ``countries_listed`` says
    how many the payload carries; ``truncated`` says the two differ."""
    _seed_many_countries(db, monkeypatch, n_located=6, located_articles=3, unlocated_articles=1)

    out = q.ring_country_split(db, ring_id="testconcept", limit=3)
    assert out["n_countries"] == 6, "the exact count of located countries, not the limit"
    assert out["countries_listed"] == 3
    assert out["truncated"] is True
    # The number a reader could otherwise count off the map must be STRICTLY below the
    # reported total, or this guard would pass against a payload that reports the cap.
    assert len([c for c in out["countries"] if c["country"]]) < out["n_countries"]


def test_an_untruncated_split_never_claims_a_truncation(db, monkeypatch):
    """The negative-space twin: under the limit nothing is cut, so ``truncated`` is
    False and the two counts agree. An over-eager flag would print a "listed 6 of 6"
    disclosure about a complete list — a fabricated gap, exactly as dishonest as the
    hidden cap it replaces."""
    _seed_many_countries(db, monkeypatch, n_located=6, located_articles=3, unlocated_articles=1)

    out = q.ring_country_split(db, ring_id="testconcept", limit=40)
    assert out["truncated"] is False
    assert out["n_countries"] == 6 and out["countries_listed"] == 6
    assert len([c for c in out["countries"] if c["country"]]) == out["n_countries"]
    assert any(c["country"] is None for c in out["countries"])


def test_a_split_with_nothing_indexed_reports_zero_rather_than_omitting_it(db, monkeypatch):
    """Zero located countries is a real measurement here (nothing indexed yet), not an
    unmeasured gap — so the counts ride that branch too and no consumer has to default
    an absent field into a number."""
    from src.analytics import equivalence
    ring = _ring()
    monkeypatch.setattr(equivalence, "ring_meta", lambda rid: ring if rid == "testconcept" else None)
    monkeypatch.setattr(equivalence, "ring_of", lambda lang, norm: None)

    out = q.ring_country_split(db, ring_id="testconcept")
    assert out["n_keywords"] == 0
    assert out["n_countries"] == 0 and out["countries_listed"] == 0
    assert out["truncated"] is False
