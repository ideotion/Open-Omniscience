"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Tests for offline source discovery (0.0.8 part 2, WP5 / RM-19): the citation
and catalog channels stage candidates with evidence, respect the budget, never
re-suggest known/dismissed domains, and the promote/dismiss flow keeps the
operator in charge (promotion creates a DISABLED source). No network anywhere.
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.database.models import Article, ArticleLink, Source, SourceCandidate
from src.database.session import SessionLocal, init_db
from src.discovery.channels import citation_channel, is_commerce_domain, run_discovery


@pytest.fixture()
def db():
    init_db()
    s = SessionLocal()
    yield s
    s.rollback()
    s.close()


def _seed_citations(s, domain: str, n_articles: int) -> None:
    tag = uuid.uuid4().hex[:8]
    src = Source(name=f"D {tag}", domain=f"d-{tag}.example", language="en")
    s.add(src)
    s.flush()
    for i in range(n_articles):
        a = Article(
            url=f"https://d-{tag}.example/{i}",
            canonical_url=f"https://d-{tag}.example/{i}",
            source_id=src.id,
            title=f"Citing {i}",
            content="x " * 50,
            language="en",
            hash=uuid.uuid4().hex + uuid.uuid4().hex,
        )
        s.add(a)
        s.flush()
        s.add(ArticleLink(
            article_id=a.id,
            url=f"https://{domain}/story-{i}",
            normalized_url=f"https://{domain}/story-{i}",
            link_type="external",
        ))
    s.flush()


def test_citation_channel_stages_candidate_with_evidence(db):
    domain = f"cited-{uuid.uuid4().hex[:6]}.example"
    _seed_citations(db, domain, 4)  # >= the min of 3
    created = citation_channel(db, cap=10)
    assert domain in created
    cand = db.query(SourceCandidate).filter_by(domain=domain).one()
    assert cand.channel == "citation" and cand.status == "candidate"
    ev = json.loads(cand.evidence)
    assert ev["distinct_citing_articles"] == 4
    assert len(ev["sample_article_ids"]) <= 5


def test_citation_channel_skips_known_and_dismissed_domains(db):
    known = f"known-{uuid.uuid4().hex[:6]}.example"
    _seed_citations(db, known, 4)
    db.add(Source(name="Already here", domain=known, language="en"))
    dismissed = f"dis-{uuid.uuid4().hex[:6]}.example"
    _seed_citations(db, dismissed, 4)
    db.add(SourceCandidate(domain=dismissed, channel="citation", status="dismissed"))
    db.flush()
    created = citation_channel(db, cap=50)
    assert known not in created
    assert dismissed not in created  # dismissal is remembered, never re-suggested


def test_citation_channel_never_re_proposes_a_disqualified_domain(db):
    """S1.1 verification (2026-07-23 field-feedback workflow, ledger 'SOURCE
    QUALIFICATION' thread): a source the qualification lifecycle disqualified is STILL
    a ``Source`` row (the status is a stamp, not a deletion) — ``_existing_domains``
    keys on ``Source.domain`` alone, so a disqualified domain is excluded from
    re-proposal BY CONSTRUCTION, the same as any other already-registered domain. This
    pins that property explicitly rather than leaving it an implicit side effect."""
    from src.catalog.qualification import STATUS_DISQUALIFIED

    disq = f"disqualified-{uuid.uuid4().hex[:6]}.example"
    _seed_citations(db, disq, 4)  # enough citations to WOULD qualify as a candidate
    db.add(Source(name="Was disqualified", domain=disq, language="en", enabled=True,
                  status=STATUS_DISQUALIFIED))
    db.flush()
    created = citation_channel(db, cap=50)
    assert disq not in created


def test_is_commerce_domain_filter():
    # The field-log offenders (2026-06-13) and kindred storefronts.
    assert is_commerce_domain("shop.popsci.com")
    assert is_commerce_domain("store.popsci.com")
    assert is_commerce_domain("popularscienceprints.com")
    assert is_commerce_domain("buy.example.com")
    assert is_commerce_domain("acme.shop")  # commercial gTLD
    assert is_commerce_domain("brand.store")
    # Journalism / ordinary domains must pass through.
    assert not is_commerce_domain("popsci.com")
    assert not is_commerce_domain("nation.africa")
    assert not is_commerce_domain("theguardian.com")
    assert not is_commerce_domain("en.wikipedia.org")
    assert not is_commerce_domain("")
    assert not is_commerce_domain(None)


def test_citation_channel_skips_commerce_storefronts(db):
    # A frequently-cited storefront is still not a journalism source.
    shop = "shop.popsci.example"  # leftmost storefront label
    prints = "popularscienceprints.example"  # …prints name
    legit = f"news-{uuid.uuid4().hex[:6]}.example"
    for d in (shop, prints, legit):
        _seed_citations(db, d, 4)  # all above the min
    created = citation_channel(db, cap=50)
    assert legit in created
    assert shop not in created
    assert prints not in created
    # And nothing commercial was staged as a candidate.
    assert db.query(SourceCandidate).filter_by(domain=shop).first() is None
    assert db.query(SourceCandidate).filter_by(domain=prints).first() is None


def test_citation_channel_honours_the_cap(db):
    doms = [f"cap-{uuid.uuid4().hex[:6]}.example" for _ in range(4)]
    for d in doms:
        _seed_citations(db, d, 3)
    created = citation_channel(db, cap=2)
    assert len([d for d in created if d in doms]) <= 2


def test_run_discovery_disabled_at_zero_budget(db):
    report = run_discovery(db, per_run=0)
    assert report == {"enabled": False, "created": 0}


def test_run_discovery_reports_what_it_did(db):
    domain = f"rep-{uuid.uuid4().hex[:6]}.example"
    _seed_citations(db, domain, 5)
    report = run_discovery(db, per_run=6)
    assert report["enabled"] is True and report["budget"] == 6
    assert domain in report["citation"]
    assert report["created"] >= 1  # the visible record for the run log


def test_promote_creates_disabled_source_and_dismiss_round_trip(db):
    d1 = f"pr-{uuid.uuid4().hex[:6]}.example"
    d2 = f"dm-{uuid.uuid4().hex[:6]}.example"
    db.add(SourceCandidate(domain=d1, channel="citation", status="candidate"))
    db.add(SourceCandidate(domain=d2, channel="catalog", status="candidate"))
    db.commit()
    with TestClient(app) as client:
        lst = client.get("/api/sources/candidates").json()
        ids = {c["domain"]: c["id"] for c in lst["candidates"]}
        r = client.post(f"/api/sources/candidates/{ids[d1]}/promote")
        assert r.status_code == 200
        assert r.json()["enabled"] is False  # the operator's deliberate act remains
        r = client.post(f"/api/sources/candidates/{ids[d2]}/dismiss")
        assert r.status_code == 200
        # re-promoting a promoted candidate is refused honestly
        assert client.post(f"/api/sources/candidates/{ids[d1]}/promote").status_code == 409
    s2 = SessionLocal()
    try:
        src = s2.query(Source).filter_by(domain=d1).one()
        assert src.enabled is False
        assert s2.query(SourceCandidate).filter_by(domain=d2).one().status == "dismissed"
    finally:
        s2.close()
