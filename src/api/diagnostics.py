"""
Diagnostics log: shareable, on-demand syntheses of back-end state.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer↔developer feedback channel (CLAUDE.md ruling 2026-06-10): the
corpus is private and local by design, so improving data-shaped behaviour
(keyword grouping first) needs an export the operator can *choose* to share.
Precedent: ``data/source_preflight.jsonl`` plays this role for sources.

Honesty constraints (FUTURE_DEVELOPMENTS design):
- generated ON DEMAND only — nothing is written or sent automatically;
- carries date, app version and corpus size so the reader knows the context;
- synthesizes, never editorialises: counts and structures, no scores;
- bounded (the same discipline as every other scan) and says so when capped.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.analytics import queries as q
from src.analytics.families import build_families
from src.database.models import (
    Article,
    Keyword,
    KeywordMention,
    KeywordSuperGroup,
    Source,
)
from src.database.session import get_db
from src.utils.export_envelope import envelope

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])

# Bounded scan: more than enough vocabulary to diagnose grouping, never unbounded.
_MAX_KEYWORDS = 5000


@router.get("/keywords")
def keyword_log(db: Session = Depends(get_db)) -> JSONResponse:
    """The keyword diagnostics log: every gathered keyword (bounded, mentions-desc)
    with its counts, plus the computed families, the user's merge/split overrides
    and the super-groups — exactly the structures the grouping logic works on."""
    rows = (
        db.query(
            Keyword,
            func.coalesce(func.sum(KeywordMention.count), 0).label("mentions"),
            func.count(func.distinct(KeywordMention.article_id)).label("articles"),
            func.min(KeywordMention.observed_on).label("first_seen"),
            func.max(KeywordMention.observed_on).label("last_seen"),
        )
        .outerjoin(KeywordMention, KeywordMention.keyword_id == Keyword.id)
        .group_by(Keyword.id)
        .order_by(func.coalesce(func.sum(KeywordMention.count), 0).desc())
        .limit(_MAX_KEYWORDS + 1)
        .all()
    )
    capped = len(rows) > _MAX_KEYWORDS
    rows = rows[:_MAX_KEYWORDS]

    # The stoplist verdict is part of the diagnosis: leaked function words the
    # operator hid are exactly what grouping fixes need to see — flag, not omit.
    is_hidden = q._hidden_predicate()
    keywords = [
        {
            "term": k.term,
            "normalized": k.normalized_term,
            "kind": q.kind_of(k),
            "language": k.language,
            "mentions": int(m),
            "articles": int(a),
            "first_seen": first.isoformat() if first else None,
            "last_seen": last.isoformat() if last else None,
            "hidden": bool(is_hidden(k.normalized_term)),
        }
        for k, m, a, first, last in rows
    ]

    overrides = q.load_overrides(db)
    fam_items = [
        {
            "term": kw["term"],
            "normalized": kw["normalized"],
            "kind": kw["kind"],
            "mentions": kw["mentions"],
            "articles": kw["articles"],
        }
        for kw in keywords
        if not kw["hidden"]
    ]
    families = [f.to_dict() for f in build_families(fam_items, overrides)]

    supergroups = [
        {
            "name": sg.name,
            "members": sorted(m.normalized_term for m in sg.members),
        }
        for sg in db.query(KeywordSuperGroup).order_by(KeywordSuperGroup.name).all()
    ]

    payload = {
        "corpus": {
            "articles": int(db.query(func.count(Article.id)).scalar() or 0),
            "sources": int(db.query(func.count(Source.id)).scalar() or 0),
            "keywords_total": int(db.query(func.count(Keyword.id)).scalar() or 0),
            "keywords_exported": len(keywords),
            "capped": capped,
        },
        "method": (
            f"All gathered keywords (top {_MAX_KEYWORDS} by total mentions) with real "
            "counts; families computed by the live grouping logic incl. the user's "
            "merge/split overrides; super-groups as curated. No scores, no inference."
        ),
        "keywords": keywords,
        "families": families,
        "overrides": [
            {"normalized_term": term, **data} for term, data in sorted(overrides.items())
        ],
        "supergroups": supergroups,
    }
    body = envelope(
        kind="keyword-diagnostics", query={}, count=len(keywords), payload=payload
    )
    fname = f"oo-keyword-log-{datetime.now().strftime('%Y%m%d')}.json"
    return JSONResponse(
        body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )


@router.get("/network")
def network_preflight_log() -> JSONResponse:
    """The network-targets diagnostics log (maintainer↔developer channel):
    source preflight verdicts + feed/calendar preflight verdicts + the full
    calendar verdict store — everything needed to optimize the default
    install's source/feed/calendar lists from REAL verdicts."""
    from src.events.feeds import load_verdicts
    from src.monitoring import feed_preflight
    from src.monitoring.preflight import recent_results as source_results

    payload = {
        "sources": source_results(),
        "feeds": feed_preflight.recent_results(),
        "calendar_verdicts": load_verdicts(),
        "method": (
            "Verbatim verdict logs: data/source_preflight.jsonl + "
            "data/feed_preflight.jsonl + the per-feed calendar checks. "
            "Robots verdicts use the standard taxonomy (allowed/disallowed/"
            "blocked/missing/unreachable); nothing is inferred."
        ),
    }
    count = len(payload["sources"]) + len(payload["feeds"]) + len(payload["calendar_verdicts"])
    body = envelope(kind="network-preflight", query={}, count=count, payload=payload)
    fname = f"oo-network-preflight-{datetime.now().strftime('%Y%m%d')}.json"
    return JSONResponse(
        body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )


@router.get("/debug-bundle")
def debug_bundle(db: Session = Depends(get_db)) -> JSONResponse:
    """ONE downloadable bundle with everything a developer needs to diagnose a
    live install remotely (maintainer-ruled 2026-06-10: "I'll click every
    download/scrape/refresh button and send you the log"). Sections:

    runtime · corpus shape · scheduler state + run history · every network
    verdict (sources / market feeds / calendars) · per-click import outcomes ·
    law + wiki tracking states · the rolling WARNING+ error log. Verbatim
    records, no inference; generated only on click.
    """
    import json as _json
    import platform
    import sys as _sys

    from src.events.feeds import load_imports, load_verdicts
    from src.monitoring import feed_preflight
    from src.monitoring.errorlog import recent_errors
    from src.monitoring.field_test import recent_results as _field_test_results
    from src.monitoring.preflight import recent_results as source_results
    from src.paths import data_dir as _data_dir
    from src.scheduler.runlog import recent_runs
    from src.scheduler.runner import get_scheduler

    # -- runtime ----------------------------------------------------------- #
    def _has(mod: str) -> bool:
        import importlib.util

        return importlib.util.find_spec(mod) is not None

    try:
        from sqlalchemy import text as _text

        schema_rev = db.execute(_text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:  # noqa: BLE001
        schema_rev = None
    llm: dict = {"available": False}
    try:
        from src.llm.ollama import OllamaClient

        client = OllamaClient()
        if client.is_available():
            llm = {"available": True, "models": client.list_installed()}
    except Exception as exc:  # noqa: BLE001 - loopback-only, best-effort
        llm = {"available": False, "error": str(exc)[:200]}
    from src.ingest import kill_switch_active

    db_file = _data_dir() / "open_omniscience.db"
    runtime = {
        "python": _sys.version.split()[0],
        "platform": platform.platform(),
        "schema_revision": schema_rev,
        "extras": {m: _has(m) for m in ("numpy", "scipy", "pandas", "zstandard", "lz4")},
        "llm": llm,
        "db_bytes": db_file.stat().st_size if db_file.exists() else None,
        "kill_switch": kill_switch_active(),
    }

    # -- corpus shape ------------------------------------------------------ #
    from src.database.models import CommodityPrice, LawDocument, WikiPage

    corpus = {
        "articles": int(db.query(func.count(Article.id)).scalar() or 0),
        "sources": int(db.query(func.count(Source.id)).scalar() or 0),
        "keywords": int(db.query(func.count(Keyword.id)).scalar() or 0),
        "price_points": int(db.query(func.count(CommodityPrice.id)).scalar() or 0),
    }

    # -- per-surface tracking states (real columns, verbatim) --------------- #
    law_docs = [
        {
            "title": d.title,
            "jurisdiction": d.jurisdiction,
            "url": d.url,
            "last_status": d.last_status,
            "last_checked_at": d.last_checked_at.isoformat() if d.last_checked_at else None,
        }
        for d in db.query(LawDocument).order_by(LawDocument.jurisdiction, LawDocument.title).all()
    ]
    wiki_pages = [
        {
            "wiki": p.wiki,
            "title": p.title,
            "missing": p.missing,
            "baseline": p.baseline_revid is not None,
            "last_checked_at": p.last_checked_at.isoformat() if p.last_checked_at else None,
        }
        for p in db.query(WikiPage).order_by(WikiPage.wiki, WikiPage.title).all()
    ]

    # -- per-click import outcomes ----------------------------------------- #
    imports_path = _data_dir() / "import_results.jsonl"
    import_results = []
    if imports_path.exists():
        for ln in imports_path.read_text(encoding="utf-8").splitlines()[-50:]:
            try:
                import_results.append(_json.loads(ln))
            except ValueError:
                continue

    payload = {
        "runtime": runtime,
        "corpus": corpus,
        "scheduler": {"status": get_scheduler().status(), "recent_runs": recent_runs(30)},
        "network": {
            "sources": source_results(),
            "feeds": feed_preflight.recent_results(),
            "calendar_verdicts": load_verdicts(),
        },
        "imports": import_results,
        "calendar_imports": {
            k: {"events": len(v.get("events", {})), "imported_at": v.get("imported_at")}
            for k, v in load_imports().items()
        },
        "law_documents": law_docs,
        "wiki_pages": wiki_pages,
        # TEMPORARY (0.0.8 live-test cycle): automated field-test outcomes —
        # see src/monitoring/field_test.py for purpose + the OO_FIELD_TEST=0
        # opt-out. Will be removed when the cycle ends.
        "field_test": _field_test_results(),
        "errors": recent_errors(300),
        "method": (
            "Verbatim runtime facts, tracking states, network verdicts, per-click "
            "import outcomes and the rolling WARNING+ error log. Nothing inferred; "
            "exported only on the operator's click."
        ),
    }
    body = envelope(kind="debug-bundle", query={}, count=len(payload["errors"]), payload=payload)
    fname = f"oo-debug-bundle-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    return JSONResponse(
        body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )
