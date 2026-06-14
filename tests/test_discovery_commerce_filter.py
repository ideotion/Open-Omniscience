"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Focused tests for the discovery commerce/storefront filter (field-log finding D,
2026-06-13): citation-based source discovery had surfaced shop.popsci.com,
store.popsci.com and popularscienceprints.com — merch, not journalism. The
maintainer ruling: "filter obvious commerce (shop./store./buy./*prints.com) from
discovery candidates; never auto-enable."

These tests pin BOTH directions: obvious storefronts are rejected, and — just as
important under the project's honesty stance — legitimate news domains and words
that merely CONTAIN a shop/store substring are NOT rejected (false positives only
cost one un-suggested domain, so the heuristic errs toward under-filtering). They
also assert the filter is wired at the real chokepoint (``citation_channel``) and
that nothing commercial is ever staged as a candidate.

A separate, additive file (no overlap with tests/test_discovery_channels.py) so
it cannot collide with concurrent branches. No network anywhere.
"""

from __future__ import annotations

import uuid

import pytest

from src.database.models import Article, ArticleLink, Source, SourceCandidate
from src.database.session import SessionLocal, init_db
from src.discovery.channels import citation_channel, is_commerce_domain

# Hosts the heuristic SHOULD treat as storefronts/merch (reject from discovery).
COMMERCE_HOSTS = [
    # The verbatim field-log offenders (2026-06-13).
    "shop.popsci.com",
    "store.popsci.com",
    "popularscienceprints.com",
    # Leftmost storefront labels named in the ruling.
    "buy.example.com",
    "cart.example.com",
    "checkout.example.com",
    "shopping.example.com",
    "merch.example.com",
    # Commercial gTLDs.
    "acme.shop",
    "brand.store",
    # Hyphen-delimited shop/store/merch suffix on the registrable name. The hyphen
    # is a deliberate boundary, so this stays clear of restore/workshop/bookstore.
    "acme-shop.com",
    "band-merch.com",
    "big-store.com",
    "daily-shopping.com",
    # A subdomain in front of a storefront registrable name is still a storefront.
    "www.acme-shop.com",
]

# Hosts the heuristic MUST let through — legitimate journalism, and the
# false-positive traps (a shop/store substring inside an unrelated word).
LEGIT_HOSTS = [
    "popsci.com",  # the journalism site, even though shop.popsci.com is merch
    "reuters.com",
    "lemonde.fr",
    "theguardian.com",
    "nation.africa",
    "en.wikipedia.org",
    "elpais.com",
    # The boundary traps: a substring, NOT a commerce label/suffix.
    "restore.com",  # "re-store" — not a storefront
    "workshop.com",  # ends in "shop" but is one word
    "bishopmagazine.com",  # contains "shop"
    "bookstore-review.org",  # a review site, not a store
    "superstore-news.com",  # a news site, not a store
    # A bare (un-hyphenated) suffix is DELIBERATELY not matched (would need a
    # dictionary to tell from workshop/restore — we under-filter on purpose).
    "bigbrandstore.com",
    "acmeshop.com",
]


@pytest.mark.parametrize("host", COMMERCE_HOSTS)
def test_commerce_hosts_are_filtered(host: str) -> None:
    assert is_commerce_domain(host) is True, f"{host} should be treated as commerce"


@pytest.mark.parametrize("host", LEGIT_HOSTS)
def test_legitimate_hosts_pass_through(host: str) -> None:
    assert is_commerce_domain(host) is False, f"{host} must NOT be filtered (false positive)"


def test_empty_and_none_and_bare_label_are_safe() -> None:
    # No crashes, never a positive, on degenerate input.
    assert is_commerce_domain("") is False
    assert is_commerce_domain(None) is False
    assert is_commerce_domain("localhost") is False  # single label, no TLD


def test_path_segments_do_not_trigger_the_filter() -> None:
    # The chokepoint feeds is_commerce_domain a HOST (registrable_domain output),
    # never a path. Boundary rules are host-only, so a "store" in a path is moot —
    # but assert the helper itself only ever looks at the host's own labels.
    assert is_commerce_domain("example.com") is False
    # A host whose name is exactly "store-news" (news outlet) still passes: the
    # suffix rule requires the token to be the trailing compound, "-news" is not it.
    assert is_commerce_domain("store-news.com") is False


# --- functional: the filter actually fires at the citation chokepoint ---------


@pytest.fixture()
def db():
    init_db()
    s = SessionLocal()
    yield s
    s.rollback()
    s.close()


def _seed_citations(s, domain: str, n_articles: int) -> None:
    """Create n distinct articles that each cite ``domain`` once (external link)."""
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


def test_citation_channel_skips_commerce_keeps_journalism(db) -> None:
    """A frequently-cited storefront is never staged; a frequently-cited news
    domain is. This is the field-log fix end-to-end at the real chokepoint."""
    shop = "shop.popsci.example"  # leftmost storefront label
    prints = "popularscienceprints.example"  # …prints name
    hyphen_store = "acme-store.example"  # hyphen-delimited suffix
    legit = f"news-{uuid.uuid4().hex[:6]}.example"
    for d in (shop, prints, hyphen_store, legit):
        _seed_citations(db, d, 4)  # all above the min_citations of 3

    created = citation_channel(db, cap=50)

    assert legit in created
    for bad in (shop, prints, hyphen_store):
        assert bad not in created
        # Degrades honestly: the commercial domain is simply not surfaced — no
        # SourceCandidate row was written for it (and nothing is auto-enabled).
        assert db.query(SourceCandidate).filter_by(domain=bad).first() is None
