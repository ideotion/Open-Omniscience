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
