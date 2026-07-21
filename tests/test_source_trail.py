"""Per-source discovery trail + qualified-citations tally (L5).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Covers src.discovery.source_trail: source_provenance (channel + citing trail) and
source_citation_tally (qualified/disqualified/pending/never_registered + filtered
classes, per-class domain lists as clickable drills). No crypto/main -> every lane.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, ArticleLink, Base, Source, SourceCandidate
from src.discovery.source_trail import (
    TALLY_CAVEAT,
    source_citation_tally,
    source_provenance,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _mk_source(s, name, domain, **kw):
    src = Source(name=name, domain=domain, **kw)
    s.add(src)
    s.commit()
    return src


def _mk_article(s, source_id, key, created_at=None):
    a = Article(
        url=f"https://x/{key}", canonical_url=f"https://x/{key}", source_id=source_id,
        content="x", hash=f"hash-{key}", created_at=created_at,
    )
    s.add(a)
    s.flush()
    return a


def _link(s, article_id, url, link_type="external"):
    s.add(ArticleLink(article_id=article_id, url=url, normalized_url=url, link_type=link_type))


# ------------------------- source_provenance ------------------------- #


def test_provenance_unknown_source_id():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    assert source_provenance(s, 999) == {"found": False}


def test_provenance_from_promoted_candidate(db):
    s = db
    src = _mk_source(s, "Cited Co", "citedco.example")
    s.add(SourceCandidate(
        domain="citedco.example", suggested_name="Cited Co", channel="citation",
        evidence=json.dumps({"distinct_citing_articles": 3}),
        status="promoted", first_seen=datetime(2026, 6, 1),
    ))
    s.commit()
    r = source_provenance(s, src.id)
    assert r["found"] is True
    assert r["channel"] == "citation"
    assert r["evidence"] == {"distinct_citing_articles": 3}
    assert r["first_seen"] is not None
    assert "citation" in r["detail"]
    assert r["qualification_status"] == "unqualified"  # L1 default


def test_provenance_from_catalog_via_tag(db):
    s = db
    src = _mk_source(s, "Wiki Edition", "en.wikipedia.org", tags="wikipedia,via:wikipedia")
    r = source_provenance(s, src.id)
    assert r["channel"] == "wikipedia"
    assert "via:wikipedia" in r["detail"]


def test_provenance_from_cited_source_type_without_candidate_row(db):
    """cited_sources.promote_cited_sources creates the Source directly (no
    SourceCandidate row) -- provenance still resolves via source_type."""
    s = db
    src = _mk_source(s, "reuters.com", "reuters.com", source_type="cited", enabled=False)
    r = source_provenance(s, src.id)
    assert r["channel"] == "cited"


def test_provenance_no_recorded_channel(db):
    s = db
    src = _mk_source(s, "Mystery News", "mystery.example")
    r = source_provenance(s, src.id)
    assert r["channel"] is None
    assert "No recorded discovery provenance" in r["detail"]


def test_provenance_citing_trail_picks_earliest_citer_and_its_source(db):
    s = db
    cited = _mk_source(s, "Cited Domain", "cited.example")
    citer_a = _mk_source(s, "Citer A", "citera.example")
    citer_b = _mk_source(s, "Citer B", "citerb.example")

    later = _mk_article(s, citer_b.id, "later", created_at=datetime(2026, 6, 10, tzinfo=UTC))
    earlier = _mk_article(s, citer_a.id, "earlier", created_at=datetime(2026, 6, 1, tzinfo=UTC))
    s.commit()
    _link(s, earlier.id, "https://cited.example/story")
    _link(s, later.id, "https://cited.example/other-story")
    s.commit()

    r = source_provenance(s, cited.id)
    trail = r["citing_trail"]
    assert trail is not None
    assert trail["article_id"] == earlier.id
    assert trail["citing_source_id"] == citer_a.id
    assert trail["citing_source_domain"] == "citera.example"
    assert trail["distinct_citing_articles"] == 2


def test_provenance_citing_trail_none_when_uncited(db):
    s = db
    src = _mk_source(s, "Lonely", "lonely.example")
    r = source_provenance(s, src.id)
    assert r["citing_trail"] is None


def test_provenance_citing_trail_is_alias_aware(db):
    """bbc.com / bbc.co.uk are known aliases -- a citation via either resolves the
    same trail (src.utils.url_utils.DOMAIN_ALIASES)."""
    s = db
    bbc = _mk_source(s, "BBC", "bbc.com")
    citer = _mk_source(s, "Citer", "citer.example")
    art = _mk_article(s, citer.id, "a1", created_at=datetime(2026, 1, 1, tzinfo=UTC))
    s.commit()
    _link(s, art.id, "https://bbc.co.uk/news/story")  # the ALIAS domain, not bbc.com
    s.commit()
    r = source_provenance(s, bbc.id)
    assert r["citing_trail"] is not None
    assert r["citing_trail"]["citing_source_id"] == citer.id


# ------------------------- source_citation_tally ------------------------- #


def test_tally_unknown_source_id(db):
    assert source_citation_tally(db, 999) == {"found": False}


def test_tally_no_articles_returns_empty_buckets(db):
    s = db
    src = _mk_source(s, "Quiet", "quiet.example")
    r = source_citation_tally(s, src.id)
    assert r["found"] is True
    assert r["counts"] == {
        "qualified": 0, "disqualified": 0, "pending": 0, "never_registered": 0,
        "filtered_commerce": 0, "filtered_social": 0, "filtered_infrastructure": 0,
    }
    assert r["caveat"] == TALLY_CAVEAT


def test_tally_classifies_every_bucket(db):
    s = db
    reporter = _mk_source(s, "Reporter", "reporter.example")
    _mk_source(s, "Qualified Domain", "qualified.example", status="qualified")
    _mk_source(s, "Disqualified Domain", "disqualified.example", status="disqualified")
    _mk_source(s, "Pending Domain", "pending.example", status="unqualified")

    a1 = _mk_article(s, reporter.id, "a1")
    a2 = _mk_article(s, reporter.id, "a2")
    s.commit()
    _link(s, a1.id, "https://qualified.example/x")
    _link(s, a1.id, "https://disqualified.example/y")
    _link(s, a1.id, "https://pending.example/z")
    _link(s, a1.id, "https://twitter.com/reporter")           # social -> filtered
    _link(s, a2.id, "https://fonts.googleapis.com/css")        # infrastructure -> filtered
    _link(s, a2.id, "https://acme-shop.example/deal")           # commerce -> filtered
    _link(s, a2.id, "https://brandnewblog.example/post")        # never registered
    _link(s, a1.id, "https://reporter.example/self-link")       # self-citation excluded
    s.commit()

    r = source_citation_tally(s, reporter.id)
    assert [e["domain"] for e in r["qualified"]] == ["qualified.example"]
    assert [e["domain"] for e in r["disqualified"]] == ["disqualified.example"]
    assert [e["domain"] for e in r["pending"]] == ["pending.example"]
    assert [e["domain"] for e in r["never_registered"]] == ["brandnewblog.example"]
    assert [e["domain"] for e in r["filtered"]["social"]] == ["twitter.com"]
    assert [e["domain"] for e in r["filtered"]["infrastructure"]] == ["fonts.googleapis.com"]
    assert [e["domain"] for e in r["filtered"]["commerce"]] == ["acme-shop.example"]
    # every class entry -- including never_registered/filtered -- carries the citing
    # article ids on THIS source (the reciprocal drill's "link to citing articles").
    assert r["never_registered"][0]["sample_article_ids"] == [a2.id]
    assert r["qualified"][0]["sample_article_ids"] == [a1.id]
    all_domains = (
        [e["domain"] for e in r["qualified"] + r["disqualified"] + r["pending"] + r["never_registered"]]
    )
    assert "reporter.example" not in all_domains
    assert r["counts"]["qualified"] == 1
    assert r["counts"]["disqualified"] == 1
    assert r["counts"]["pending"] == 1
    assert r["counts"]["never_registered"] == 1
    assert r["counts"]["filtered_social"] == 1
    assert r["counts"]["filtered_infrastructure"] == 1
    assert r["counts"]["filtered_commerce"] == 1
    assert "not guilt" in r["caveat"]
    assert "not" in r["caveat"] and "endorsement" in r["caveat"]


def test_tally_no_score_rank_rating_grade_substrings_in_any_key(db):
    """House invariant: field-name discipline -- no score/ranking/rating/grade
    substring in any payload key (qualified/disqualified are explicitly safe)."""
    s = db
    reporter = _mk_source(s, "Reporter2", "reporter2.example")
    _mk_source(s, "Q", "q.example", status="qualified")
    a1 = _mk_article(s, reporter.id, "a1")
    s.commit()
    _link(s, a1.id, "https://q.example/x")
    s.commit()

    def _walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                for bad in ("score", "rank", "rating", "grade"):
                    assert bad not in k.lower(), f"forbidden substring '{bad}' in key {k!r}"
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(source_citation_tally(s, reporter.id))


def test_tally_sample_article_ids_caps_and_collects_all_citing_articles(db):
    """Multiple articles citing the SAME domain all contribute to that domain's
    sample_article_ids (capped), not just the first/last one seen."""
    s = db
    reporter = _mk_source(s, "Reporter3", "reporter3.example")
    _mk_source(s, "Q", "qq.example", status="qualified")
    arts = [_mk_article(s, reporter.id, f"m{i}") for i in range(3)]
    s.commit()
    for a in arts:
        _link(s, a.id, "https://qq.example/story")
    s.commit()

    r = source_citation_tally(s, reporter.id)
    entry = r["qualified"][0]
    assert entry["domain"] == "qq.example"
    assert sorted(entry["sample_article_ids"]) == sorted(a.id for a in arts)
