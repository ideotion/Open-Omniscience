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
from src.catalog.wikidata import WDQS_ENDPOINT, build_query, iso3_crosscheck
from src.ingest import DEFAULT_USER_AGENT, kill_switch_active

_TIMEOUT_S = 90
_PROVENANCE = "wikidata-discovery"


def _guarded_run_query(
    cfg: dict, iso3_checks: list[dict] | None = None
) -> Callable[[str, list[str]], dict]:
    """Production transport: a guarded GET to the WDQS SPARQL endpoint per country.

    ``iso3_checks``, when given, collects the P298 cross-check verdict for each
    country the run reaches (ruling Q311 = a). It is an out-parameter rather than a
    return value because the transport's shape is fixed by ``generate_catalog``,
    which owns the loop; a second pass would double every request, and this fact
    arrives free in a response the run already paid for.
    """
    from src.safety.fetcher import guarded_session

    def run_query(cc: str, type_qids: list[str]) -> dict:
        q = build_query(cc, type_qids, label_lang=cfg["label_lang"], limit=cfg["limit"])
        url = f"{WDQS_ENDPOINT}?" + urllib.parse.urlencode({"query": q, "format": "json"})
        resp = guarded_session(user_agent=DEFAULT_USER_AGENT, isolation_token=cc).get(
            url, timeout=_TIMEOUT_S
        )
        try:
            payload = resp.json()
        except ValueError as exc:
            # S5 item 4 (field-feedback 2026-07-23): a non-JSON response body (a
            # rate-limit page, an error page, a truncated response) used to
            # surface as a bare parse exception ("Expecting value: line 1 column
            # 1 (char 0)") recorded by generate_catalog with no way to tell a 429
            # rate-limit from a genuinely broken query. Carry the REAL HTTP
            # status + a short first-bytes snippet so a diagnostics reader can
            # classify it at a glance — observability only, no retry-policy
            # change (still recorded + skipped by the caller, same as before).
            snippet = (resp.text or "")[:120].replace("\n", " ")
            raise RuntimeError(
                f"non-JSON response (HTTP {resp.status_code}): {snippet!r}"
            ) from exc
        if iso3_checks is not None:
            # Recorded per COUNTRY, not per spec: one country is queried once per
            # spec, and every one of those responses carries the same `?iso3`
            # (it is bound off `?country`). Appending each would report one fact
            # N times and make a single disagreement look like N of them.
            if not any(r.get("country") == cc.strip().upper() for r in iso3_checks):
                iso3_checks.append(iso3_crosscheck(payload, country_code=cc))
        return payload

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
    iso3_checks: list[dict] = []
    runq = run_query or _guarded_run_query(cfg, iso3_checks)

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
    # The cross-check REPORTS and never repairs (Q311 = a). Only disagreements ride
    # in the summary: an `agree` is the expected case and an `absent` is Wikidata
    # being quiet, and a diagnostic that always says something is one nobody reads.
    # `iso3_checked` carries the DENOMINATOR, because "0 disagreements" over 0
    # checks and over 200 are different facts.
    disagreements = [r for r in iso3_checks if r.get("verdict") == "disagree"]
    return {
        "added": added,
        "countries": codes,
        "iso3_checked": len(iso3_checks),
        "iso3_disagreements": disagreements,
        **result["stats"],
    }
