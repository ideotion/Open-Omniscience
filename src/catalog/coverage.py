"""
Coverage report: how many countries the source catalog reaches, and the gaps.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Computed entirely from the data (the country codes actually present on sources)
against the neutral ISO code set, so progress toward "every country" is measured,
not asserted. Drives the generator's targeting and a read-only UI panel.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from src.catalog.countries import (
    CONTINENT_OF,
    CONTINENTS,
    ISO_3166_1_ALPHA2,
    SPECIAL_CODES,
)

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
    # Recognised non-country codes (EU institutions, international bodies, …)
    # are reported apart — neither junk nor part of the country denominator.
    special = sorted(c for c in (present - codes) if c in SPECIAL_CODES)
    # Codes that appear in the data but aren't recognised at all (legacy/junk
    # values) — surfaced so they aren't silently ignored.
    extra = sorted(c for c in (present - codes) if c not in SPECIAL_CODES)

    return {
        "total_countries": len(codes),
        "covered": len(covered),
        "coverage_pct": round(100.0 * len(covered) / len(codes), 1) if codes else 0.0,
        "missing_count": len(missing),
        "missing": missing,
        "thin_threshold": thin_threshold,
        "thin": thin,
        "special_codes": special,
        "extra_codes": extra,
    }


_TARGETS_PATH = Path(__file__).resolve().parents[2] / "configs" / "catalog_targets.yml"


def load_targets(path: Path | None = None) -> dict:
    """Read the per-region balance targets (user-editable aspirational floors).

    Absent/unreadable file degrades to empty targets — the regional report then
    simply reports actuals without target comparisons, never invented numbers.
    """
    p = path or _TARGETS_PATH
    try:
        data = yaml.safe_load(p.read_text()) or {}
    except OSError:
        return {"regions": {}, "concentration": {}}
    return {
        "regions": data.get("regions") or {},
        "concentration": data.get("concentration") or {},
    }


def regional_report(
    country_counts: dict[str, int],
    *,
    targets: dict | None = None,
    total_sources: int | None = None,
) -> dict:
    """Per-region balance: sources + countries covered vs the configured floors.

    The de-US-centring acceptance metric (0.09). Pure arithmetic over real
    counts; a target is a stated aspiration from ``catalog_targets.yml`` and
    each row says plainly whether it is met. ``unlocated`` counts sources with
    no resolvable country at all (only computable when ``total_sources`` is
    given) — they are invisible to every geographic analysis, so the share is
    reported rather than hidden.
    """
    targets = targets if targets is not None else load_targets()
    region_targets: dict = targets.get("regions") or {}
    counts = {(c or "").lower(): int(n) for c, n in country_counts.items() if c}

    per_region: dict[str, dict] = {
        r: {"region": r, "sources": 0, "countries_covered": 0, "countries_total": 0}
        for r in CONTINENTS
    }
    for code in ISO_3166_1_ALPHA2:
        region = CONTINENT_OF.get(code)
        if region in per_region:
            per_region[region]["countries_total"] += 1
    special_sources = 0
    for code, n in counts.items():
        if n <= 0:
            continue
        region = CONTINENT_OF.get(code)
        if region in per_region and code in ISO_3166_1_ALPHA2:
            per_region[region]["sources"] += n
            per_region[region]["countries_covered"] += 1
        elif code in SPECIAL_CODES:
            special_sources += n

    regions = []
    for r in CONTINENTS:
        row = per_region[r]
        t = region_targets.get(r) or {}
        row["min_sources"] = t.get("min_sources")
        row["min_countries"] = t.get("min_countries")
        row["sources_met"] = (
            None if t.get("min_sources") is None else row["sources"] >= int(t["min_sources"])
        )
        row["countries_met"] = (
            None
            if t.get("min_countries") is None
            else row["countries_covered"] >= int(t["min_countries"])
        )
        regions.append(row)

    located = sum(n for c, n in counts.items() if c in ISO_3166_1_ALPHA2)
    top_code, top_n = None, 0
    for c, n in counts.items():
        if c in ISO_3166_1_ALPHA2 and n > top_n:
            top_code, top_n = c, n
    conc = targets.get("concentration") or {}
    out: dict = {
        "regions": regions,
        "special_sources": special_sources,
        "located_sources": located,
        "top_country": {
            "code": top_code,
            "sources": top_n,
            "share_pct": round(100.0 * top_n / located, 1) if located else 0.0,
            "max_share_pct": conc.get("max_country_share_pct"),
        },
    }
    if total_sources is not None and total_sources > 0:
        out["total_sources"] = total_sources
        out["located_share_pct"] = round(100.0 * located / total_sources, 1)
        out["min_located_share_pct"] = conc.get("min_located_share_pct")
    return out


def country_counts_from_session(session) -> dict[str, int]:
    """Tally enabled+disabled sources per country code from the DB."""
    from sqlalchemy import func

    from src.database.models import Source

    rows = session.query(Source.country, func.count(Source.id)).group_by(Source.country).all()
    return {(c or "").lower(): int(n) for c, n in rows if c}
