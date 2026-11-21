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


#: The targets file's read state (row 289): ``present``, ``absent`` (no file), ``empty`` (read, sets no usable target) or
#: ``unreadable`` (the error named by its class or a shape fact, never the path). Targets that were not read are never
#: "no target set": the report says which, and every comparison is None with the state beside it.
TARGET_STATES = ("present", "absent", "empty", "unreadable")
_REGION_KEYS = ("min_sources", "min_countries")
_SHARE_KEYS = ("max_country_share_pct", "min_located_share_pct")


def _count_value(v: object) -> int | None:
    """A whole, non-negative target count, or None. A bool is not a count; a float is one only when whole."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v if v >= 0 else None
    if isinstance(v, float) and v.is_integer() and v >= 0:
        return int(v)
    return None


def _share_value(v: object) -> float | int | None:
    """A share between 0 and 100 inclusive, or None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v if 0 <= v <= 100 else None


def _clean_targets(data: dict) -> tuple[dict, dict, list[dict]]:
    """``(regions, concentration, refused)`` from a parsed targets mapping. A value that is not a usable target is
    REFUSED with a token, never coerced: a coerced floor ("lots" read as 0) would be met by every region."""
    refused: list[dict] = []
    regions: dict[str, dict] = {}
    raw_regions = data.get("regions")
    if raw_regions is not None and not isinstance(raw_regions, dict):
        refused.append({"region": None, "key": "regions", "refused": "not_a_mapping"})
        raw_regions = {}
    for name, row in (raw_regions or {}).items():
        if name not in CONTINENTS:
            refused.append({"region": str(name), "key": None, "refused": "not_a_region"})
            continue
        if not isinstance(row, dict):
            refused.append({"region": name, "key": None, "refused": "not_a_mapping"})
            continue
        kept: dict = {}
        for key in row:
            if key not in _REGION_KEYS:
                refused.append({"region": name, "key": str(key), "refused": "unknown_key"})
        for key in _REGION_KEYS:
            if row.get(key) is None:
                continue
            val = _count_value(row[key])
            if val is None:
                refused.append({"region": name, "key": key, "refused": "not_a_whole_number"})
            else:
                kept[key] = val
        if kept:
            regions[name] = kept
    concentration: dict = {}
    raw_conc = data.get("concentration")
    if raw_conc is not None and not isinstance(raw_conc, dict):
        refused.append({"region": None, "key": "concentration", "refused": "not_a_mapping"})
    if not isinstance(raw_conc, dict):
        raw_conc = {}
    for key in raw_conc:
        if key not in _SHARE_KEYS:
            refused.append({"region": None, "key": str(key), "refused": "unknown_key"})
    for key in _SHARE_KEYS:
        if raw_conc.get(key) is None:
            continue
        share = _share_value(raw_conc[key])
        if share is None:
            refused.append({"region": None, "key": key, "refused": "not_a_percentage"})
        else:
            concentration[key] = share
    return regions, concentration, refused


def _judge(regions: dict, concentration: dict, refused: list[dict], read: dict) -> dict:
    """The final state once the values are cleaned: a read file with no usable target is ``empty`` -- or
    ``unreadable`` when values were there and every one was refused, since that file is not a file of nothing."""
    if read.get("state") != "present" or regions or concentration:
        return read
    if refused:
        return {"state": "unreadable", "error": f"no usable target ({len(refused)} refused)"}
    return {"state": "empty"}


def load_targets(path: Path | None = None) -> dict:
    """Read the per-region balance targets (user-editable aspirational floors), with the read's state. Never raises.

    Returns ``{"regions", "concentration", "read", "refused"}``. Read on every call, never cached here, so a file the
    operator fixes is seen by the next compute. The coverage route's cache re-stamps an entry while nothing is written to
    the database, so a payload whose targets were not read whole carries its own TTL there (``__ttl_s__``) and is
    recomputed once that ends, written to or not.
    """
    p = path or _TARGETS_PATH
    empty: dict = {"regions": {}, "concentration": {}, "refused": []}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {**empty, "read": {"state": "absent"}}
    except (OSError, UnicodeDecodeError, ValueError, RecursionError, yaml.YAMLError) as exc:
        return {**empty, "read": {"state": "unreadable", "error": type(exc).__name__}}
    if data is None:
        return {**empty, "read": {"state": "empty"}}
    if not isinstance(data, dict):
        return {**empty, "read": {"state": "unreadable", "error": f"not a mapping ({type(data).__name__})"}}
    regions, concentration, refused = _clean_targets(data)
    read = _judge(regions, concentration, refused, {"state": "present"})
    if read["state"] != "present":
        return {**empty, "refused": refused, "read": read}
    return {"regions": regions, "concentration": concentration, "refused": refused, "read": read}


def _normalised_targets(targets: dict) -> dict:
    """A targets dict as :func:`load_targets` returns it. A hand-built one (no ``read`` block) is cleaned the same
    way and judged by what survives, so a bad value never raises out of the report."""
    if isinstance(targets.get("read"), dict):
        return {"refused": [], **targets}
    regions, concentration, refused = _clean_targets(targets)
    read = _judge(regions, concentration, refused, {"state": "present"})
    return {"regions": regions, "concentration": concentration, "refused": refused, "read": read}


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
    reported rather than hidden. ``targets`` is the targets file's read state (row 289) and ``targets_refused`` every
    value it refused: when the file was not read, no region is compared with a floor and that says why, never "no
    target set".
    """
    targets = _normalised_targets(targets if targets is not None else load_targets())
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
        row["sources_met"] = None if t.get("min_sources") is None else row["sources"] >= t["min_sources"]
        row["countries_met"] = (
            None if t.get("min_countries") is None else row["countries_covered"] >= t["min_countries"]
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
        # Row 289: whether the targets were read, and every value refused; a None comparison then says why.
        "targets": targets["read"],
        "targets_refused": targets["refused"],
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
