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

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from src.analytics import queries as q
from src.analytics.families import build_families
from src.database.maintenance import StatementTimeout, statement_deadline
from src.database.models import (
    Article,
    Keyword,
    KeywordSuperGroup,
    Source,
)
from src.database.session import get_db
from src.utils.export_envelope import envelope

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])

# Bounded scan — PER LANGUAGE (maintainer-ruled 2026-06-11): a single global
# mentions-ranked cap structurally anglicised the export (English keywords
# crowded out every other language, excluding them from the equivalence/family
# analysis). Each keyword counts against the quota of its DOMINANT signature
# language, so French/German/… vocabularies are exported in full alongside
# English. Bounded per language, biased against none.
_MAX_KEYWORDS_PER_LANG = 5000


def _in_batches(ids: list[int], size: int = 800):
    for i in range(0, len(ids), size):
        yield ids[i : i + size]


@router.get("/keywords")
def keyword_log(db: Session = Depends(get_db)) -> StreamingResponse:
    """The keyword diagnostics log: every gathered keyword (bounded, mentions-desc)
    with its counts, plus the computed families, the user's merge/split overrides
    and the super-groups — exactly the structures the grouping logic works on.

    Performance batch 2026-06-12 (failed live at 228k keywords): the per-language
    cap now bounds the WORK, not just the output — totals scan the covering
    index as plain tuples, the dominant language is computed in SQL, and the
    full language signatures / keyword metadata are fetched only for the
    keywords that survive the quota. The body is STREAMED, so memory stays
    bounded and the download starts immediately. Same envelope, same fields,
    same cap semantics as before (contract-tested).
    """
    try:
        with statement_deadline(db):
            # Article -> language, ONCE, via the covering index (verified plan:
            # idx_article_country_language) — joining mentions to articles in
            # SQL would drag article rows through the SQLCipher codec for every
            # batch (measured 26 s of the 32 s encrypted-profile wall time).
            art_lang: dict[int, str] = {
                aid: (lang or "?")
                for aid, lang in db.execute(text("SELECT id, language FROM articles"))
            }

            # Dominant signature language per keyword from ONE index-only scan
            # of (keyword_id, article_id), ordered so each keyword's counts can
            # be reduced and freed as the scan passes it. Ties: language asc
            # (matching the previous argmax over language-asc grouped rows).
            dom_lang: dict[int, str] = {}
            _cur_kid: int | None = None
            _counts: dict[str, int] = {}

            def _finalize(kid: int | None, counts: dict[str, int]) -> None:
                if kid is not None and counts:
                    dom_lang[kid] = min(counts, key=lambda lg: (-counts[lg], lg))

            for kid, aid in db.execute(
                text("SELECT keyword_id, article_id FROM keyword_mentions ORDER BY keyword_id")
            ):
                if kid != _cur_kid:
                    _finalize(_cur_kid, _counts)
                    _cur_kid, _counts = kid, {}
                lg = art_lang.get(aid, "?")
                _counts[lg] = _counts.get(lg, 0) + 1
            _finalize(_cur_kid, _counts)

            # Stored-language fallback for keywords with no mentions (kept from
            # the previous contract: they export with zero counts, quota applies).
            stored_lang: dict[int, str | None] = dict(
                db.execute(text("SELECT id, language FROM keywords")).fetchall()
            )

            # Totals, mentions-desc — an index-only scan of ix_mention_covering,
            # iterated as tuples; the quota decides survivors ON THE FLY, so the
            # 228k-keyword aggregation never materialises as ORM objects.
            per_lang_taken: dict[str, int] = {}
            capped_langs: set[str] = set()
            survivors: list[tuple[int, int, int, str | None, str | None]] = []
            seen: set[int] = set()
            totals_sql = text(
                "SELECT keyword_id, COALESCE(SUM(count), 0) AS m,"
                " COUNT(DISTINCT article_id) AS a,"
                " MIN(observed_on) AS first_seen, MAX(observed_on) AS last_seen"
                " FROM keyword_mentions GROUP BY keyword_id"
                " ORDER BY m DESC, keyword_id ASC"
            )
            for kid, m, a, first, last in db.execute(totals_sql):
                seen.add(kid)
                dom = dom_lang.get(kid) or stored_lang.get(kid) or "?"
                taken = per_lang_taken.get(dom, 0)
                if taken >= _MAX_KEYWORDS_PER_LANG:
                    capped_langs.add(dom)
                    continue
                per_lang_taken[dom] = taken + 1
                survivors.append((kid, int(m), int(a), first, last))
            for kid in sorted(set(stored_lang) - seen):  # zero-mention keywords
                dom = stored_lang.get(kid) or "?"
                taken = per_lang_taken.get(dom, 0)
                if taken >= _MAX_KEYWORDS_PER_LANG:
                    capped_langs.add(dom)
                    continue
                per_lang_taken[dom] = taken + 1
                survivors.append((kid, 0, 0, None, None))

            survivor_ids = [s[0] for s in survivors]
            # Metadata + full language signatures for SURVIVORS only.
            meta: dict[int, tuple] = {}
            lang_sig: dict[int, dict[str, int]] = {}
            for batch in _in_batches(survivor_ids):
                marks = ",".join(str(int(i)) for i in batch)
                for kid, term, norm, lang, is_ent, ent_type in db.execute(
                    text(
                        "SELECT id, term, normalized_term, language, is_entity,"
                        f" entity_type FROM keywords WHERE id IN ({marks})"
                    )
                ):
                    meta[kid] = (term, norm, lang, bool(is_ent), ent_type)
                # Full signatures via index-only probes + the art_lang map —
                # mention rows are unique per (keyword, article), so each row
                # contributes exactly one distinct article to its language.
                for kid, aid in db.execute(
                    text(
                        "SELECT keyword_id, article_id FROM keyword_mentions"
                        f" WHERE keyword_id IN ({marks})"
                    )
                ):
                    sig = lang_sig.setdefault(kid, {})
                    lg = art_lang.get(aid, "?")
                    sig[lg] = sig.get(lg, 0) + 1

            corpus = {
                "articles": int(db.query(func.count(Article.id)).scalar() or 0),
                "sources": int(db.query(func.count(Source.id)).scalar() or 0),
                "keywords_total": len(stored_lang),
                "keywords_exported": len(survivors),
                "exported_per_language": per_lang_taken,
                "capped_languages": sorted(capped_langs),
            }
            overrides = q.load_overrides(db)
            supergroups = [
                {
                    "name": sg.name,
                    "members": sorted(m.normalized_term for m in sg.members),
                }
                for sg in db.query(KeywordSuperGroup).order_by(KeywordSuperGroup.name).all()
            ]
    except StatementTimeout as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # The stoplist verdict is part of the diagnosis: leaked function words the
    # operator hid are exactly what grouping fixes need to see — flag, not omit.
    is_hidden = q._hidden_predicate()

    def _entry(s: tuple) -> dict:
        kid, m, a, first, last = s
        term, norm, lang, is_ent, ent_type = meta.get(kid, ("?", "?", None, False, None))
        return {
            "term": term,
            "normalized": norm,
            "kind": (ent_type or "entity") if is_ent else "term",
            "language": lang,
            "mentions": m,
            "articles": a,
            "first_seen": str(first) if first else None,
            "last_seen": str(last) if last else None,
            "hidden": bool(is_hidden(norm)),
            "language_signature": lang_sig.get(kid, {}),
        }

    fam_items = []
    for s in survivors:
        kw = _entry(s)
        if not kw["hidden"]:
            fam_items.append(
                {
                    "term": kw["term"],
                    "normalized": kw["normalized"],
                    "kind": kw["kind"],
                    "mentions": kw["mentions"],
                    "articles": kw["articles"],
                }
            )
    families = [f.to_dict() for f in build_families(fam_items, overrides)]

    method = (
        f"All gathered keywords (top {_MAX_KEYWORDS_PER_LANG} PER dominant signature "
        "language — a global cap would anglicise the export) with real "
        "counts; language_signature = distinct articles per ARTICLE language "
        "(the trans-language disambiguation evidence); families computed by the "
        "live grouping logic incl. the user's merge/split overrides; super-groups "
        "as curated. No scores, no inference."
    )

    def _stream():
        head = envelope(
            kind="keyword-diagnostics", query={}, count=len(survivors), payload=None
        )
        del head["data"]
        yield json.dumps(head, separators=(",", ":"))[:-1] + ', "data": {'
        yield '"corpus": ' + json.dumps(corpus, separators=(",", ":"))
        yield ', "method": ' + json.dumps(method, separators=(",", ":"))
        yield ', "keywords": ['
        for i in range(0, len(survivors), 1000):
            chunk = survivors[i : i + 1000]
            prefix = "" if i == 0 else ","
            yield prefix + ",".join(json.dumps(_entry(s), separators=(",", ":")) for s in chunk)
        yield '], "families": ' + json.dumps(families, separators=(",", ":"))
        yield ', "overrides": ' + json.dumps(
            [{"normalized_term": term, **data} for term, data in sorted(overrides.items())],
            separators=(",", ":"),
        )
        yield ', "supergroups": ' + json.dumps(supergroups, separators=(",", ":"))
        yield "}}"

    fname = f"oo-keyword-log-{datetime.now().strftime('%Y%m%d')}.json"
    return StreamingResponse(
        _stream(),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
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
