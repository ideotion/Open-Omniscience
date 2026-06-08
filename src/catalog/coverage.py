"""
Coverage report: how many countries the source catalog reaches, and the gaps.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Computed entirely from the data (the country codes actually present on sources)
against the neutral ISO code set, so progress toward "every country" is measured,
not asserted. Drives the generator's targeting and a read-only UI panel.
"""

from __future__ import annotations

from src.catalog.countries import ISO_3166_1_ALPHA2

DEFAULT_THIN_THRESHOLD = 3


def coverage_report(
    country_counts: dict[str, int],
    *,
    all_codes: set[str] | frozenset[str] | None = None,
    thin_threshold: int = DEFAULT_THIN_THRESHOLD,
) -> dict:
    """Summarise coverage from ``{country_code: source_count}``.

    Returns counts of covered vs total countries, the sorted list of missing
    codes, and the "thin" codes (covered but with fewer than ``thin_threshold``
    sources) — the two lists that tell you exactly where to expand next.
    """
    codes = {c.lower() for c in (all_codes or ISO_3166_1_ALPHA2)}
    counts = {(c or "").lower(): int(n) for c, n in country_counts.items() if c}
    present = {c for c, n in counts.items() if n > 0}

    covered = present & codes
    missing = sorted(codes - present)
    thin = sorted(c for c in covered if counts.get(c, 0) < thin_threshold)
    # Codes that appear in the data but aren't in the reference set (e.g. legacy
    # values) — surfaced so they aren't silently ignored.
    extra = sorted(present - codes)

    return {
        "total_countries": len(codes),
        "covered": len(covered),
        "coverage_pct": round(100.0 * len(covered) / len(codes), 1) if codes else 0.0,
        "missing_count": len(missing),
        "missing": missing,
        "thin_threshold": thin_threshold,
        "thin": thin,
        "extra_codes": extra,
    }


def country_counts_from_session(session) -> dict[str, int]:
    """Tally enabled+disabled sources per country code from the DB."""
    from sqlalchemy import func

    from src.database.models import Source

    rows = session.query(Source.country, func.count(Source.id)).group_by(Source.country).all()
    return {(c or "").lower(): int(n) for c, n in rows if c}
