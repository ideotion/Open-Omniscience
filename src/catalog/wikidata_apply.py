"""
In-app Wikidata source_type enrichment — the consented, airplane-gated networked pass.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Fills ``Source.source_type`` from Wikidata for sources that have only the default
``news`` type. Unlike the LOCAL corpus topic pass (which runs automatically), this
EGRESSES to Wikidata over clearnet, so it is a one-time Diagnostics ACTION behind
the app's single network consent, and it REFUSES UP FRONT while airplane mode is
engaged (no socket) — the same contract as the stats fetchers.

Pure reconciliation logic + the anti-fabrication domain gate live in
src/catalog/wikidata_enrich.py. This module only performs the guarded GETs and
writes the results, so it stays testable with an injected getter.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.catalog.wikidata_enrich import (
    parse_search_qids,
    reconcile,
    wbentities_url,
    wbsearch_url,
)
from src.ingest import DEFAULT_USER_AGENT, kill_switch_active

_TIMEOUT_S = 20
Getter = Callable[[str], Any]


def _default_getter(url: str) -> Any:
    """Production getter: a guarded GET (kill switch + protected-mode proxy).

    A per-URL isolation token gives each request its own Tor circuit (no-op without
    a SOCKS proxy), so distinct lookups are unlinkable over Tor.
    """
    from src.safety.fetcher import guarded_session

    return guarded_session(user_agent=DEFAULT_USER_AGENT, isolation_token=url).get(
        url, timeout=_TIMEOUT_S
    )


def apply_source_types(session, *, limit: int = 200, get: Getter | None = None) -> dict:
    """Fill ``source_type`` from Wikidata for up to ``limit`` untyped sources.

    "Untyped" = ``source_type`` is NULL or the bare default ``news`` (a curated
    non-default type is never touched). Refuses up front under airplane mode. Each
    source's failure is isolated (one bad lookup never aborts the batch). Returns
    ``{"scanned", "sources_typed"}``.
    """
    # Defense in depth: refuse before any socket, so the refusal is testable offline.
    if kill_switch_active():
        raise RuntimeError("network refused: airplane mode is engaged")

    from sqlalchemy import or_

    from src.database.models import Source
    from src.database.writer import write_lock

    getter = get or _default_getter
    todo = (
        session.query(Source)
        .filter(or_(Source.source_type.is_(None), Source.source_type == "news"))
        .limit(limit)
        .all()
    )
    pending: list[tuple[Any, str]] = []
    for s in todo:
        if not s.name or not s.domain:
            continue
        try:
            qids = parse_search_qids(getter(wbsearch_url(s.name)).json())
            if not qids:
                continue
            payload = getter(wbentities_url(qids)).json()
            row = next(
                (r for r in (reconcile(payload, q, expected_domain=s.domain) for q in qids) if r),
                None,
            )
            if row and row["source_type"] != s.source_type:
                pending.append((s, row["source_type"]))
        except Exception:  # noqa: BLE001 - one source's failure never aborts the batch
            continue

    with write_lock():
        for s, new_type in pending:
            s.source_type = new_type
        session.commit()
    return {"scanned": len(todo), "sources_typed": len(pending)}
