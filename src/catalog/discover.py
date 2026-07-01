"""
In-app source DISCOVERY from Wikidata — add NEW sources to scrape (enabled:false).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Distinct from the ENRICHMENT passes (which only label sources you already have):
this queries Wikidata per country for news orgs / institutions with an official
website (the same forward query the offline catalog builder uses) and inserts any
NEW ones as DISABLED sources for the user to review and enable. It never enables or
scrapes anything on its own -- discovering sources is a bigger decision (coverage
balance, review-before-enable), so the result is inert until the user opts in.

Networked + consented: refuses up front under airplane mode (no socket), egresses
through the guarded factory (kill switch + proxy + per-country Tor circuit). The
pure query/parse/dedup lives in src/catalog/{wikidata,build,normalize}.py; this only
performs the guarded GETs and writes disabled rows, so it is testable with an
injected ``run_query``.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Callable, Iterable

from src.catalog.build import generate_catalog, load_query_config
from src.catalog.wikidata import WDQS_ENDPOINT, build_query
from src.ingest import DEFAULT_USER_AGENT, kill_switch_active

_TIMEOUT_S = 90
_PROVENANCE = "wikidata-discovery"


def _guarded_run_query(cfg: dict) -> Callable[[str, list[str]], dict]:
    """Production transport: a guarded GET to the WDQS SPARQL endpoint per country."""
    from src.safety.fetcher import guarded_session

    def run_query(cc: str, type_qids: list[str]) -> dict:
        q = build_query(cc, type_qids, label_lang=cfg["label_lang"], limit=cfg["limit"])
        url = f"{WDQS_ENDPOINT}?" + urllib.parse.urlencode({"query": q, "format": "json"})
        resp = guarded_session(user_agent=DEFAULT_USER_AGENT, isolation_token=cc).get(
            url, timeout=_TIMEOUT_S
        )
        return resp.json()

    return run_query


def discover_sources(
    session,
    country_codes: Iterable[str],
    *,
    run_query: Callable[[str, list[str]], dict] | None = None,
    per_spec_limit: int | None = None,
) -> dict:
    """Discover + insert NEW disabled sources for the given countries.

    Refuses up front under airplane mode. New sources are inserted with
    ``enabled=False`` and a ``via:wikidata-discovery`` provenance tag (a filterable
    class), deduped by domain against the existing catalog. Returns a summary
    ``{"added", "countries", ...generate_catalog stats}``.
    """
    if kill_switch_active():
        raise RuntimeError("network refused: airplane mode is engaged")

    from src.database.models import Source
    from src.database.writer import write_lock
    from src.ingest.seed_sources import _to_source_kwargs

    codes = [c.strip().lower() for c in country_codes if c and c.strip()]
    cfg = load_query_config()
    if per_spec_limit:
        cfg["limit"] = int(per_spec_limit)
    runq = run_query or _guarded_run_query(cfg)

    existing = {d for (d,) in session.query(Source.domain).all()}
    result = generate_catalog(runq, codes, cfg["specs"], existing_domains=existing)

    added = 0
    with write_lock():
        seen = set(existing)
        for entry in result["sources"]:
            dom = entry.get("domain")
            if not dom or dom in seen:
                continue
            entry["_provenance"] = _PROVENANCE
            kwargs = _to_source_kwargs(entry)
            kwargs["enabled"] = False  # review-before-enable — never auto-scraped
            session.add(Source(**kwargs))
            seen.add(dom)
            added += 1
        session.commit()
    return {"added": added, "countries": codes, **result["stats"]}
