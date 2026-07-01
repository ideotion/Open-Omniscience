"""Auto-integrate in-article secondary sources (cited domains) as new sources.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Independence is measured by DISTINCT CITING SOURCES (never article count); promoted
domains become DISABLED ``cited`` sources (metadata only, never scraped); commerce/
social storefronts are excluded, existing outlets are alias-deduped, and no fabricated
score is ever written. No crypto/main -> runs in every lane.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog.provenance import CITED, provenance_of
from src.database.models import Article, ArticleLink, Base, Source
from src.discovery.cited_sources import cited_domain_stats, promote_cited_sources


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    srcs = {
        "a": Source(name="News A", domain="newsa.com"),
        "b": Source(name="News B", domain="newsb.com"),
        "c": Source(name="News C", domain="newsc.com"),
        "bbc": Source(name="BBC", domain="bbc.com"),  # existing -> alias dedup vs bbc.co.uk
    }
    s.add_all(srcs.values())
    s.commit()
    arts: dict[str, Article] = {}
    # (key, source-key)
    for i, (key, sk) in enumerate(
        [("a1", "a"), ("a2", "a"), ("a3", "b"), ("a4", "c")]
    ):
        art = Article(
            url=f"https://x/{i}", canonical_url=f"https://x/{i}", source_id=srcs[sk].id,
            content="x", hash=f"art-{i}",
        )
        s.add(art)
        s.flush()
        arts[key] = art

    def link(akey, url, lt="external"):
        s.add(ArticleLink(article_id=arts[akey].id, url=url, normalized_url=url, link_type=lt))

    # reuters: sources {a,b}=2 -> promote
    for k in ("a1", "a2", "a3"):
        link(k, "https://www.reuters.com/x")
    # example.org: 2 articles but ONE source (a) -> below the source gate
    for k in ("a1", "a2"):
        link(k, "https://example.org/y")
    # apnews: sources {a,b,c}=3 -> promote
    for k in ("a1", "a3", "a4"):
        link(k, "https://apnews.com/z")
    for k in ("a1", "a3", "a4"):
        link(k, "https://acme-store.com/p")   # commerce
    for k in ("a1", "a3", "a4"):
        link(k, "https://facebook.com/pg")    # social
    for k in ("a1", "a3"):
        link(k, "https://www.bbc.co.uk/news")  # alias of existing bbc.com
    link("a1", "https://newsa.com/self", lt="internal")  # internal -> ignored
    s.commit()
    return s


def test_independence_is_distinct_sources_not_articles(db):
    stats = cited_domain_stats(db)
    assert len(stats["reuters.com"]["sources"]) == 2
    assert len(stats["reuters.com"]["articles"]) == 3
    # a chatty single source: 2 articles, but only 1 independent source
    assert len(stats["example.org"]["articles"]) == 2
    assert len(stats["example.org"]["sources"]) == 1
    # internal links are not secondary sources
    assert "newsa.com" not in stats


def test_dry_run_previews_without_creating(db):
    res = promote_cited_sources(db, min_source_citers=2, dry_run=True)
    assert res["created"] == []
    assert sorted(c["domain"] for c in res["candidates"]) == ["apnews.com", "reuters.com"]
    assert db.query(Source).filter_by(source_type=CITED).count() == 0


def test_promotes_multiply_sourced_domains_as_disabled_cited(db):
    res = promote_cited_sources(db, min_source_citers=2)
    assert sorted(c["domain"] for c in res["created"]) == ["apnews.com", "reuters.com"]
    reuters = db.query(Source).filter_by(domain="reuters.com").one()
    assert reuters.enabled is False          # never auto-scraped
    assert reuters.source_type == CITED
    assert reuters.tags == "cited"
    assert reuters.reliability_score is None  # NEVER a fabricated score
    assert provenance_of(reuters.domain, reuters.source_type) == CITED


def test_filters_commerce_social_and_alias_existing(db):
    res = promote_cited_sources(db, min_source_citers=2)
    assert res["skipped"]["commerce"] == 1       # acme-store.com
    assert res["skipped"]["social"] == 1         # facebook.com
    assert res["skipped"]["already_a_source"] == 1  # bbc.co.uk == existing bbc.com (alias)
    assert res["skipped"]["below_gate"] >= 1     # example.org (1 source)
    assert not db.query(Source).filter(Source.domain.in_(
        ["acme-store.com", "facebook.com", "bbc.co.uk"])).count()


def test_gate_and_idempotency(db):
    # A stricter gate (>=3 sources) promotes only apnews.
    strict = promote_cited_sources(db, min_source_citers=3)
    assert [c["domain"] for c in strict["created"]] == ["apnews.com"]
    # Re-running never duplicates (reuters/apnews now exist).
    again = promote_cited_sources(db, min_source_citers=2)
    assert "apnews.com" not in [c["domain"] for c in again["created"]]
    assert db.query(Source).filter_by(domain="apnews.com").count() == 1
