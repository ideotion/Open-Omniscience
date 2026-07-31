"""
Ingest the official-statistics agency directory as Source rows (Group N,
official-statistics ingestion).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The curated directory (src/stats/agencies.py) lists WHO publishes official
statistics. This module REGISTERS each producer in the source catalog so it can be
managed alongside every other source. A producer is ENABLED when the directory knows
where its news/press section is (``news_url``) and DISABLED when it does not — see
``ingest_agencies_as_sources`` for why that distinction, not a blanket default, is the
honest one. NO "controversial" verdict is attached (maintainer ruling 2026-06-19
#50 — "users should make their humble opinions"); the producer is filterable by the
``official-statistics`` tag + its region, and the user judges. Official MACHINE
endpoints (SDMX / APIs) remain the preferred path to the FIGURES themselves; enabling a
producer collects its written coverage, never its datasets.

HONESTY (project §0.5): no figures, no ranking, NO ``reliability_score`` is ever
written here (fabricating a credibility number is forbidden — it stays NULL). NO
network: ``agency.home_url`` is metadata reduced to a registrable domain locally,
never fetched. Idempotent: an already-present domain is left untouched (additive,
never clobbering an operator's curation).
"""

from __future__ import annotations

from sqlalchemy.orm import Session as SASession

from src.catalog.normalize import registrable_domain
from src.database.models import Source
from src.stats.agencies import list_agencies


def _region_slug(region: str) -> str:
    """Lowercase, space-collapsed tag form of an agency region (e.g. "North
    America" -> "north-america"). Deterministic; descriptive metadata only."""
    return "-".join((region or "").strip().lower().split())


def ingest_agencies_as_sources(session: SASession) -> dict:
    """Register every curated statistical agency as a Source.

    Additive and idempotent: a Source whose ``domain`` already exists is skipped
    (never modified), so this is safe to call repeatedly. Rows get low ``priority``,
    ``source_type="statistics"``, tagged ``official-statistics`` + region. NO
    "controversial" verdict tag (ruling #50). ``reliability_score`` is deliberately left
    NULL — no fabricated score, ever.

    ENABLED WHEN CRAWLABLE (maintainer ruling 9, 2026-07-31). These agencies carry no
    feed, and crawl-by-default is on, so "enabled" is not cosmetic — it makes a source
    crawl-eligible. An agency with a confirmed ``news_url`` is registered ENABLED, and the
    crawl starts there. An agency WITHOUT one is registered DISABLED, because its
    ``home_url`` is a dataset portal: crawling it would spend real bandwidth collecting
    PDFs and download pages, then rely on the non-article filter to throw them away. That
    is the harm ``news_url`` exists to prevent, so the honest default is to wait for the
    URL rather than guess one. The tally reports both counts, so an operator can see
    exactly how many producers are still waiting on a researched news URL.

    The caller owns the transaction (e.g. ``session_scope()``): this only
    ``session.add(...)`` new rows; the single-writer gate serialises the commit.

    Returns a tally dict with a ``method`` + ``caveat`` (no score field).
    """
    agencies = list_agencies()
    created = 0
    skipped_existing = 0
    skipped_no_domain = 0
    enabled_now = 0
    awaiting_news_url = 0

    for agency in agencies:
        domain = registrable_domain(agency.home_url)
        if not domain:
            skipped_no_domain += 1
            continue

        exists = session.query(Source).filter(Source.domain == domain).first()
        if exists is not None:
            # NEVER clobber an existing source — additive only.
            skipped_existing += 1
            continue

        # No "controversial" tag (ruling #50): filterable as official-statistics + by
        # region; the user judges — no verdict tag attached.
        tags = ["official-statistics", _region_slug(agency.region)]
        crawlable = bool((agency.news_url or "").strip())
        if crawlable:
            enabled_now += 1
        else:
            awaiting_news_url += 1
        session.add(
            Source(
                name=agency.name,
                domain=domain,
                enabled=crawlable,  # a known news section = a meaningful crawl entry point
                priority=3,  # low
                source_type="statistics",
                country=(agency.country.lower() if agency.country else None),
                region=agency.region,
                language=None,  # unknown is honestly NULL, never assumed
                tags=",".join(tags),
                # reliability_score intentionally NOT set — no fabricated score.
            )
        )
        created += 1

    return {
        "created": created,
        "skipped_existing": skipped_existing,
        "skipped_no_domain": skipped_no_domain,
        "enabled": enabled_now,
        "awaiting_news_url": awaiting_news_url,
        "total_agencies": len(agencies),
        "method": (
            "Curated official-statistics directory registered as Source rows by "
            "registrable domain; idempotent (existing domains untouched). A producer "
            "with a known news/press section is enabled and crawled from there; one "
            "without is registered and left disabled until that URL is researched."
        ),
        "caveat": (
            "Official producers are STANCED sources (a producing state has "
            "interests) — enabling one collects its written coverage, never its "
            "datasets, and implies no endorsement. No credibility score."
        ),
    }


def crawl_start_url_for(source) -> str | None:
    """The URL a crawl of ``source`` should START from, or None for the default.

    Only statistics sources get a non-default answer: their ``home_url`` is a dataset
    portal, so the crawl is pointed at the agency's confirmed news/press section instead
    (maintainer ruling 9, 2026-07-31). Returns None for every other source, and for a
    statistics source whose agency has no researched ``news_url`` -- in which case the
    caller's own default applies. This is where the stats catalog, which owns that fact,
    hands it to the collector; nothing else in the crawl path needs to know about it.
    """
    if (getattr(source, "source_type", None) or "") != "statistics":
        return None
    domain = (getattr(source, "domain", None) or "").lower()
    if not domain:
        return None
    for agency in list_agencies():
        if registrable_domain(agency.home_url) == domain:
            return (agency.news_url or "").strip() or None
    return None
