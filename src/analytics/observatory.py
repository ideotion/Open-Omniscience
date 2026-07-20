"""The Observatory data spine — S0 (the ``domain`` scaffold field) + S1 (the
payload endpoint), 2026-07-20.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Full design of record: ``docs/design/OBSERVATORY_DESIGN.md``. Ruled 2026-07-18:
the keyword hierarchy rendered as a deterministic night sky (universe = the
corpus, galaxy cluster = a scaffold domain, galaxy = a super-group, star system
= a group/ring, star = a keyword family). Build sequencing (design §9) gates
the actual ``ooSky`` canvas renderer behind a maintainer browser click-through
("browser-verify-GATED... NOT conservative-flaggable") — so THIS module is
backend-only: S0 (the ``configs/keyword_supergroups.yml`` ``domain:`` field,
read here) + S1 (this module's ``observatory_payload``, the universe+galaxy
tiers only). The arm-tag / star-system / top-star / nebula-of-keywords tiers
the design's §8 describes for the endpoint's EVENTUAL full shape are DEFERRED
to their own S3/S5 frontend-paired slices (design §9) — building them now,
with no renderer to validate the shape against, would risk getting it wrong
and redoing it (the same measure-before-build discipline this project applies
to persisted rollups / page-size benches / everything else that is expensive
to get wrong).

Reuses — never duplicates — the sibling super-groups brief's S1 stats core
(``supergroup_stats.py``): the SAME dedup-first discipline this module applies
one level up (a keyword covered by two galaxies of the SAME domain must count
once at the cluster level, never twice — the identical row-3 double-counting
trap the S1 core exists to fix, one tier up).

Counts and ratios only. NO composite score (the no-score key-walkers must pass
on every payload this module returns).
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

from src.analytics.supergroup_stats import (
    _distinct_source_count,
    _language_breakdown,
    _per_id_mentions,
    distinct_ids,
    group_rate,
    resolve_member_keyword_ids,
    supergroup_stats,
)

_PATH = Path(__file__).resolve().parents[2] / "configs" / "keyword_supergroups.yml"
UNCATEGORIZED = "Uncategorized"


@lru_cache(maxsize=1)
def domain_of_group() -> dict[str, str]:
    """Bundled super-group NAME -> its configured ``domain`` (the universe-tier
    cluster label), read straight from ``configs/keyword_supergroups.yml``.

    Config-only metadata, never persisted to the ``KeywordSuperGroup`` row: a
    group the user renames simply falls out of this name-keyed lookup and
    degrades honestly into the ``UNCATEGORIZED`` bucket at call time (see
    ``observatory_payload``) — never re-derived by guessing, the same
    skip-not-crash convention ``supergroup_seed.py`` already applies to an
    unknown ``ring_id``. Cached for the process lifetime (the
    ``equivalence.load_rings`` convention — a bundled file read once)."""
    if not _PATH.exists():
        return {}
    data = yaml.safe_load(_PATH.read_text(encoding="utf-8")) or {}
    out: dict[str, str] = {}
    for g in data.get("supergroups", []):
        name = str(g.get("name", "")).strip()
        domain = str(g.get("domain", "")).strip()
        if name and domain:
            out[name] = domain
    return out


def _galaxy_measures(stats: dict) -> dict:
    """The four switchable dimension-picker measures (design §3c) computed for
    ONE galaxy from its already-resolved ``supergroup_stats`` payload — no
    extra query. ``distinct_sources`` is the default breadth/independence
    measure (the same anti-single-source-flooding rationale the briefing
    cards use); ``mentions`` is the brightness/size measure; the other two
    ride fields ``supergroup_stats`` already computes for free."""
    return {
        "mentions": stats["group_total"]["mentions"],
        "distinct_sources": stats["distinct_sources"],
        "distinct_languages": len(stats["languages"]),
        "distinct_keywords": stats["group_total"]["distinct_keywords"],
    }


def observatory_payload(
    db,
    *,
    window_days: int = 7,
    baseline_days: int = 30,
    today: date | None = None,
) -> dict:
    """The Observatory's universe (cluster) + galaxy (super-group) tiers.

    Returns ``{clusters: [...], galaxies: [...], nebula: {...}, method,
    caveat}``. ``clusters`` are the ~12 scaffold domains, each a PROPERLY
    DEDUPED union of its member galaxies' keyword ids (never a naive sum of
    each galaxy's own already-deduped total — that would silently
    double-count a keyword covered by two galaxies of the same domain, the
    exact row-3 trap the S1 core was built to fix, recurring one tier up).
    ``galaxies`` is every ``KeywordSuperGroup`` with its S1 stats (dominance +
    both overlap disclosures) plus the four dimension-picker measures. A
    galaxy whose name is not in the bundled scaffold's ``domain:`` map (a
    user-created group, or a bundled one the user renamed) is honestly
    bucketed under ``UNCATEGORIZED`` — never guessed. ``nebula`` discloses how
    much of the corpus's keyword vocabulary is NOT covered by any galaxy (the
    un-curated long tail) — the anti-capping disclosure named on the payload
    itself, per the design's own "N stars shown, M in the nebula" rule."""
    from sqlalchemy import func

    from src.database.models import Keyword, KeywordSuperGroup

    sgs = db.query(KeywordSuperGroup).order_by(KeywordSuperGroup.name).all()
    domain_map = domain_of_group()
    other_groups = [
        (sg.name, [(m.normalized_term, m.ring_id) for m in sg.members]) for sg in sgs
    ]

    galaxies: list[dict] = []
    domain_ids: dict[str, set[int]] = {}
    covered_ids: set[int] = set()
    for sg in sgs:
        stats = supergroup_stats(
            db, sg, other_groups=other_groups,
            window_days=window_days, baseline_days=baseline_days, today=today,
        )
        domain = domain_map.get(sg.name, UNCATEGORIZED)
        galaxies.append(
            {
                "id": sg.id,
                "name": sg.name,
                "domain": domain,
                "measures": _galaxy_measures(stats),
                "dominance": stats["dominance"],
                "rate": stats["rate"],
                "languages": stats["languages"],
                "cross_group_overlap": stats["cross_group_overlap"],
                "within_group_overlap": stats["within_group_overlap"],
            }
        )
        member_rows = [(m.normalized_term, m.ring_id) for m in sg.members]
        g_ids = distinct_ids(resolve_member_keyword_ids(db, member_rows))
        domain_ids.setdefault(domain, set()).update(g_ids)
        covered_ids |= g_ids

    clusters: list[dict] = []
    for domain in sorted(domain_ids):
        ids = domain_ids[domain]
        per_id = _per_id_mentions(db, ids)
        clusters.append(
            {
                "domain": domain,
                "galaxy_count": sum(1 for g in galaxies if g["domain"] == domain),
                "measures": {
                    "mentions": sum(per_id.values()),
                    "distinct_sources": _distinct_source_count(db, ids),
                    "distinct_languages": len(_language_breakdown(db, ids, per_id)),
                    "distinct_keywords": len(ids),
                },
                "rate": group_rate(db, ids, window_days=window_days, baseline_days=baseline_days, today=today),
            }
        )

    total_keywords = int(db.query(func.count(Keyword.id)).scalar() or 0)
    covered = len(covered_ids)
    nebula = {
        "covered_keywords": covered,
        "nebula_keywords": max(0, total_keywords - covered),
        "total_keywords": total_keywords,
    }

    return {
        "clusters": clusters,
        "galaxies": galaxies,
        "nebula": nebula,
        "method": (
            "Universe tier: the ~12 scaffold domains (configs/keyword_supergroups.yml's "
            "'domain' field), each a DEDUPED union of its member galaxies' resolved "
            "keyword ids — a keyword covered by two galaxies of the same domain counts "
            "once at the cluster level, never twice. Galaxy tier: the sibling super-groups "
            "brief's S1 stats core (supergroup_stats), unchanged — dominance + both overlap "
            "disclosures ride every galaxy. distinct_sources is the default breadth measure "
            "(the same anti-single-source-flooding independence rationale the briefing "
            "cards use); mentions/distinct_languages/distinct_keywords are the other "
            "switchable dimensions. Star-system / star / arm-tag / nova tiers are NOT in "
            "this payload yet — deferred to their own build slices (design §9)."
        ),
        "caveat": (
            "Counts and ratios only, no composite score. A galaxy not found in the bundled "
            "domain scaffold (user-created, or a bundled group the user renamed) is bucketed "
            "'Uncategorized' — never guessed. 'nebula' discloses how much of the corpus's "
            "keyword vocabulary sits outside every curated galaxy — the un-curated long tail, "
            "shown honestly rather than silently dropped."
        ),
    }
