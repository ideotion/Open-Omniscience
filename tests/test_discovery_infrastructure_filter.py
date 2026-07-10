"""Discovery infrastructure/boilerplate/social noise filter (maintainer field 2026-07-10).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Citation-based source discovery surfaced fonts.googleapis.com, policies.google.com,
creativecommons.org, bsky.app and t.me as candidates — ranked HIGH by raw citation count
precisely because they are ubiquitous footer/asset links on nearly every page, not because
they are sources. Two gaps closed: (1) the citation channel never called is_social (so
bsky.app/t.me leaked, though cited_sources.py already filtered them); (2) nothing filtered
CDN/analytics/boilerplate-legal hosts. This pins both directions: the noise is rejected, real
outlets on the same parents (news.google.com) are not.

Additive file (no overlap with test_discovery_channels.py / test_discovery_commerce_filter.py)
so it cannot collide with concurrent branches. No network anywhere.
"""

from __future__ import annotations

import uuid

import pytest

from src.database.models import Article, ArticleLink, Source, SourceCandidate
from src.database.session import SessionLocal, init_db
from src.discovery.channels import citation_channel, is_infrastructure_domain

# Hosts the filter SHOULD reject (the verbatim field offenders + kin).
INFRA_HOSTS = [
    "fonts.googleapis.com",      # font CDN (googleapis.com set + "fonts" label)
    "ajax.googleapis.com",       # script CDN
    "policies.google.com",       # boilerplate legal ("policies" label)
    "creativecommons.org",       # license footer link (exact set)
    "cdn.jsdelivr.net",          # CDN ("cdn" label + jsdelivr set)
    "fonts.gstatic.com",         # font assets
    "static.example.com",        # "static" asset host label
    "assets.example.org",        # "assets" host label
    "www.google-analytics.com",  # analytics (exact set, subdomain)
    "googletagmanager.com",      # tag manager (exact set)
    "schema.org",                # markup vocabulary (pure boilerplate, never a news source)
]

# Hosts the filter must NOT reject (real outlets / aggregators — false positives cost
# one un-suggested source, so the heuristic errs toward under-filtering).
LEGIT_HOSTS = [
    "reuters.com",
    "theguardian.com",
    "news.google.com",       # a content aggregator on google.com — NOT a policy/asset subdomain
    "lemonde.fr",
    "apnews.com",
    "propublica.org",
    "static-news.com",       # "static-news" registrable name, not a "static." label
    "assetmanagement.com",   # contains "asset" but is one word / different label
    "en.wikipedia.org",
    # Skeptic finding: a real 2-label registrable ORG whose NAME is an infra word must NOT be
    # filtered by the leftmost-label rule (that rule is for SUBDOMAINS only). These are exactly
    # the advocacy/policy/legal orgs a journalism corpus cites.
    "policy.org",
    "legal.io",
    "consent.org",
    "cookies.org",
    "analytics.io",
    "ads.net",
    "pixel.com",
    "static.com",
    "assets.co",
    # Real content publishers trimmed from the exact set (err-under-filter):
    "w3.org",
    "gnu.org",
    "cloudflare.com",
]


@pytest.mark.parametrize("host", INFRA_HOSTS)
def test_infrastructure_hosts_are_filtered(host: str) -> None:
    assert is_infrastructure_domain(host) is True, f"{host} should be treated as infrastructure"


@pytest.mark.parametrize("host", LEGIT_HOSTS)
def test_legitimate_hosts_pass_through(host: str) -> None:
    assert is_infrastructure_domain(host) is False, f"{host} must NOT be filtered (false positive)"


def test_degenerate_input_is_safe() -> None:
    assert is_infrastructure_domain("") is False
    assert is_infrastructure_domain(None) is False
    assert is_infrastructure_domain("localhost") is False  # single label


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
        s.add(
            ArticleLink(
                article_id=a.id,
                url=f"https://{domain}/story-{i}",
                normalized_url=f"https://{domain}/story-{i}",
                link_type="external",
            )
        )
    s.flush()


def test_citation_channel_skips_noise_keeps_journalism(db) -> None:
    """End-to-end at the real chokepoint: the five field offenders (CDN, legal boilerplate,
    two socials) are never staged even though each is cited by many articles; a real news
    domain is."""
    noise = [
        "fonts.googleapis.com",   # infrastructure
        "policies.google.com",    # boilerplate legal
        "creativecommons.org",    # license footer
        "bsky.app",               # social (the citation channel now calls is_social)
        "t.me",                   # social
    ]
    legit = f"news-{uuid.uuid4().hex[:6]}.example"
    for d in (*noise, legit):
        _seed_citations(db, d, 5)  # all well above the min_citations of 3

    created = citation_channel(db, cap=50)

    assert legit in created
    for bad in noise:
        assert bad not in created, f"{bad} must not be suggested"
        assert db.query(SourceCandidate).filter_by(domain=bad).first() is None


def test_prune_removes_pre_existing_noise_but_keeps_real_and_dismissed(db) -> None:
    """Forward-only filtering leaves earlier noise staged; prune_noise_candidates self-cleans
    the PENDING noise on the next pass, and never touches a real pending candidate nor a
    remembered dismissal."""
    from src.discovery.channels import prune_noise_candidates

    def _cand(dom: str, status: str = "candidate") -> None:
        db.add(SourceCandidate(domain=dom, channel="citation", status=status))

    _cand("fonts.googleapis.com")   # infra noise, pending -> removed
    _cand("bsky.app")               # social noise, pending -> removed
    _cand("shop.popsci.com")        # commerce noise, pending -> removed
    _cand("realnews.example")       # a legit pending candidate -> kept
    _cand("t.me", status="dismissed")  # a REMEMBERED dismissal -> never touched
    db.flush()

    removed = prune_noise_candidates(db)
    assert removed == 3
    remaining = {c.domain for c in db.query(SourceCandidate).all()}
    assert "realnews.example" in remaining
    assert "t.me" in remaining  # dismissed rows are preserved (never re-suggested anyway)
    for gone in ("fonts.googleapis.com", "bsky.app", "shop.popsci.com"):
        assert gone not in remaining
