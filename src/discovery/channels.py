"""Offline discovery channels (see package docstring). DB-only by contract."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import UTC, datetime

_LOG = logging.getLogger(__name__)

_CITATION_MIN = 3  # distinct citing articles before a domain becomes a candidate


def _existing_domains(session) -> set[str]:
    from src.database.models import Source, SourceCandidate

    src = {d.lower() for (d,) in session.query(Source.domain).all() if d}
    cand = {d.lower() for (d,) in session.query(SourceCandidate.domain).all() if d}
    return src | cand


def _add_candidate(session, *, domain: str, name: str | None, channel: str, evidence: dict):
    from src.database.models import SourceCandidate

    session.add(
        SourceCandidate(
            domain=domain.lower(),
            suggested_name=name,
            channel=channel,
            evidence=json.dumps(evidence, sort_keys=True, default=str),
            status="candidate",
            first_seen=datetime.now(UTC).replace(tzinfo=None),
            last_seen=datetime.now(UTC).replace(tzinfo=None),
        )
    )


def citation_channel(session, *, cap: int, min_citations: int = _CITATION_MIN) -> list[str]:
    """Suggest external domains that >= min_citations distinct stored articles cite."""
    from src.database.models import ArticleLink
    from src.catalog.normalize import registrable_domain

    known = _existing_domains(session)
    pairs = session.query(ArticleLink.normalized_url, ArticleLink.article_id).distinct().all()
    by_domain: dict[str, set[int]] = defaultdict(set)
    for nu, aid in pairs:
        dom = registrable_domain(nu)
        if dom:
            by_domain[dom.lower()].add(aid)

    created: list[str] = []
    for dom, ids in sorted(by_domain.items(), key=lambda kv: -len(kv[1])):
        if len(created) >= cap:
            break
        if len(ids) < min_citations or dom in known:
            continue
        _add_candidate(
            session,
            domain=dom,
            name=None,
            channel="citation",
            evidence={
                "reason": "frequently cited by your stored articles",
                "distinct_citing_articles": len(ids),
                "sample_article_ids": sorted(ids)[:5],
            },
        )
        created.append(dom)
    if created:
        session.flush()  # autoflush is off app-wide; make the rows visible to callers
    return created


def catalog_channel(session, *, cap: int, thin_threshold: int = 3) -> list[str]:
    """Suggest packaged-catalog entries for countries where coverage is thin."""
    from src.catalog.coverage import country_counts_from_session, coverage_report
    from src.ingest.seed_sources import load_sources_from_yaml

    known = _existing_domains(session)
    report = coverage_report(
        country_counts_from_session(session), thin_threshold=thin_threshold
    )
    targets = set(report.get("thin", []) or []) | set(report.get("missing", []) or [])
    if not targets:
        return []
    try:
        catalog = load_sources_from_yaml()  # the packaged configs/sources.yml
    except Exception:  # noqa: BLE001 - a catalog problem must not break a scrape
        _LOG.warning("could not load the packaged catalog for discovery", exc_info=True)
        return []

    created: list[str] = []
    for entry in catalog:
        if len(created) >= cap:
            break
        dom = str(entry.get("domain") or "").lower()
        country = str(entry.get("country") or "").lower()
        if not dom or dom in known or country not in targets:
            continue
        n_there = country_counts_from_session(session).get(country, 0)
        _add_candidate(
            session,
            domain=dom,
            name=entry.get("name"),
            channel="catalog",
            evidence={
                "reason": "packaged-catalog entry for a country your corpus covers thinly",
                "country": country,
                "your_sources_there": n_there,
                "thin_threshold": thin_threshold,
            },
        )
        created.append(dom)
    if created:
        session.flush()  # autoflush is off app-wide; make the rows visible to callers
    return created


def run_discovery(session, *, per_run: int = 10) -> dict:
    """Run the offline channels under the operator's budget. Returns the report
    that goes into the scheduler run log (the visible record of what happened)."""
    if per_run <= 0:
        return {"enabled": False, "created": 0}
    half = max(1, per_run // 2)
    cited = citation_channel(session, cap=half)
    remaining = per_run - len(cited)
    catalogd = catalog_channel(session, cap=remaining) if remaining > 0 else []
    session.flush()
    return {
        "enabled": True,
        "budget": per_run,
        "created": len(cited) + len(catalogd),
        "citation": cited,
        "catalog": catalogd,
    }
