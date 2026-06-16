"""
Ingest the official-statistics agency directory as DISABLED, controversial Source
rows (Group N, official-statistics ingestion — first "ingest as sources" slice).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The curated directory (src/stats/agencies.py) lists WHO publishes official
statistics. This module REGISTERS each producer in the source catalog so it can be
managed alongside every other source — but does NOT enable it: an official figure
is a STANCED source (a producing state has interests; ``controversial=True`` on
every agency by ruling), and official MACHINE endpoints (SDMX / APIs) are preferred
over scraping, so the rows land DISABLED and are wired up in a later slice. The
controversial nature is carried by a TAG (there is no "controversial" column).

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
    """Register every curated statistical agency as a DISABLED, controversial Source.

    Additive and idempotent: a Source whose ``domain`` already exists is skipped
    (never modified), so this is safe to call repeatedly. New rows are created
    DISABLED (``enabled=False`` — never auto-scraped; SDMX/API-before-scraping is a
    later slice), low ``priority``, ``source_type="statistics"``, with the
    controversial nature carried by a tag. ``reliability_score`` is deliberately
    left NULL — no fabricated score, ever.

    The caller owns the transaction (e.g. ``session_scope()``): this only
    ``session.add(...)`` new rows; the single-writer gate serialises the commit.

    Returns a tally dict with a ``method`` + ``caveat`` (no score field).
    """
    agencies = list_agencies()
    created = 0
    skipped_existing = 0
    skipped_no_domain = 0

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

        tags = ["official-statistics", "controversial", _region_slug(agency.region)]
        session.add(
            Source(
                name=agency.name,
                domain=domain,
                enabled=False,  # registered, not scraped (SDMX/API before scraping)
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
        "total_agencies": len(agencies),
        "method": (
            "Curated official-statistics directory registered as DISABLED Source "
            "rows by registrable domain; idempotent (existing domains untouched)."
        ),
        "caveat": (
            "Official producers are STANCED sources (a producing state has "
            "interests); created DISABLED — registered, not scraped. No "
            "credibility score."
        ),
    }
