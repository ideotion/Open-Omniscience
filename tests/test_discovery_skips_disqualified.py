"""A disqualified domain must never be re-proposed by a discovery funnel.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

RULING 2026-07-20 clause (d): "a re-import or a fresh citation of a disqualified domain
(a mis-interpreted marketplace, a video blog) must never re-register or re-trial it".
The clock is the only re-trigger -- that is what the re-qualification ladder is for.

WHAT WAS ACTUALLY WRONG, verified live before anything was changed: the property already
HELD. Both funnels dedupe against every existing ``Source`` domain, disqualified ones
included, so a disqualified domain never reached the staging call. What was missing was
that nothing SAID so and nothing tested it -- a ruled guarantee resting on a dedup set
whose purpose is something else. Narrowing that set (scoping it to enabled sources, the
shape the open `enabled`-vs-qualified question would take) would have reopened the hole
in silence, and no test in the tree would have noticed.

So these tests pin the guarantee at two levels, and each says which one it is:

  * end-to-end through the public funnels -- passes today, and its value is that it
    KEEPS passing when the dedup changes underneath;
  * directly against the ``_add_candidate`` chokepoint, which is the only level where
    the new refusal is discriminating, because through a channel the dedup gets there
    first.

Both directions are covered: a qualified and a never-judged domain in the same batch
must still be proposed, or "never re-propose" would have quietly become "never propose".
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog.qualification import (
    STATUS_DISQUALIFIED,
    STATUS_QUALIFIED,
    STATUS_UNQUALIFIED,
)
from src.database.models import Article, ArticleLink, Base, Source, SourceCandidate
from src.discovery.channels import _add_candidate, citation_channel, is_disqualified_domain
from src.discovery.cited_sources import promote_cited_sources

_NOW = datetime.now(UTC).replace(tzinfo=None)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()


def _judged(s, domain: str, status: str) -> None:
    s.add(Source(name=domain, domain=domain, status=status))


def _cited_by_three_outlets(s, *domains: str) -> None:
    """Three independent citing outlets, so every target clears both funnels' gates."""
    for i in range(3):
        src = Source(name=f"outlet{i}", domain=f"outlet{i}.example", status=STATUS_QUALIFIED)
        s.add(src)
        s.flush()
        art = Article(
            url=f"https://outlet{i}.example/a", canonical_url=f"https://outlet{i}.example/a",
            source_id=src.id, content="body", hash=f"h{i}", created_at=_NOW,
        )
        s.add(art)
        s.flush()
        for dom in domains:
            url = f"https://{dom}/page"
            s.add(ArticleLink(article_id=art.id, url=url, normalized_url=url,
                              link_type="external"))
    s.commit()


# --------------------------------------------------------------------------- #
#  End-to-end through the public funnels
# --------------------------------------------------------------------------- #
def test_promote_cited_sources_refuses_a_disqualified_domain_by_name(session):
    _judged(session, "junk.example", STATUS_DISQUALIFIED)
    _cited_by_three_outlets(session, "junk.example", "fresh.example")

    result = promote_cited_sources(session, dry_run=True)

    assert [c["domain"] for c in result["candidates"]] == ["fresh.example"]
    # The reason is reported apart: "we judged this and refused it" is not the same
    # fact as "we already collect this", and one counter for both hid the ruling.
    assert result["skipped"]["disqualified"] == 1
    assert result["skipped"]["already_a_source"] == 0


def test_citation_channel_stages_no_candidate_for_a_disqualified_domain(session):
    _judged(session, "junk.example", STATUS_DISQUALIFIED)
    _cited_by_three_outlets(session, "junk.example", "fresh.example")

    proposed = citation_channel(session, cap=10, min_citations=2)

    assert proposed == ["fresh.example"]
    assert [c.domain for c in session.query(SourceCandidate).all()] == ["fresh.example"]


def test_a_never_judged_and_a_qualified_domain_are_still_proposed(session):
    """The negative twin. A refusal widened to every judged domain -- or to every
    domain with a Source row -- would satisfy the tests above and turn the funnels off."""
    _judged(session, "known-good.example", STATUS_QUALIFIED)
    _cited_by_three_outlets(session, "known-good.example", "brand-new.example")

    result = promote_cited_sources(session, dry_run=True)

    # A qualified source we already hold is a duplicate, not a refusal.
    assert result["skipped"]["disqualified"] == 0
    assert result["skipped"]["already_a_source"] == 1
    assert [c["domain"] for c in result["candidates"]] == ["brand-new.example"]


# --------------------------------------------------------------------------- #
#  The chokepoint itself -- the only level where the new refusal is discriminating
# --------------------------------------------------------------------------- #
def test_the_staging_chokepoint_refuses_a_disqualified_domain(session):
    """Driven directly, because through a channel the dedup gets there first. This is
    what makes the ruling hold independently of a dedup set that exists for another
    purpose -- and what a channel added later inherits without writing a check."""
    _judged(session, "junk.example", STATUS_DISQUALIFIED)
    session.commit()

    staged = _add_candidate(
        session, domain="junk.example", name=None, channel="citation", evidence={}
    )

    assert staged is False
    assert session.query(SourceCandidate).count() == 0


def test_the_staging_chokepoint_admits_an_unjudged_domain(session):
    _judged(session, "pending.example", STATUS_UNQUALIFIED)
    session.commit()

    staged = _add_candidate(
        session, domain="pending.example", name=None, channel="citation", evidence={}
    )

    assert staged is True
    assert [c.domain for c in session.query(SourceCandidate).all()] == ["pending.example"]


def test_is_disqualified_domain_reads_the_verdict_not_the_row(session):
    for domain, status in (
        ("bad.example", STATUS_DISQUALIFIED),
        ("good.example", STATUS_QUALIFIED),
        ("new.example", STATUS_UNQUALIFIED),
    ):
        _judged(session, domain, status)
    session.commit()

    assert is_disqualified_domain(session, "bad.example") is True
    assert is_disqualified_domain(session, "BAD.EXAMPLE") is True  # case-folded
    assert is_disqualified_domain(session, "good.example") is False
    assert is_disqualified_domain(session, "new.example") is False
    assert is_disqualified_domain(session, "never-seen.example") is False
