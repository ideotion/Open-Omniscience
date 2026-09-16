"""
The date-extraction diagnostic log.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Part of the mechanical ``src/api/diagnostics.py`` -> package split (Q1139 = a,
2026-09-16): this file is lines 2305-2493 of the pre-split module, verbatim. The
routes, their paths, their methods and their order are unchanged; ``__init__``
imports the submodules in the original file order so the decorators still
register on one router in that order.
"""

from __future__ import annotations

from fastapi import Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.database.models import Article
from src.database.session import get_db
from src.utils.export_envelope import envelope

from ._base import router


@router.get("/dates")
def date_extraction_log(
    db: Session = Depends(get_db),
    scan: int = Query(1500, ge=1, le=10000, description="Max articles to scan for the aggregates (recent first)."),
    sample: int = Query(60, ge=1, le=400, description="How many articles to include in the detailed sample (worst misses first)."),
    days: int | None = Query(None, ge=1, le=36500, description="Only articles published within the last N days."),
    lang: str | None = Query(None, description="Only articles whose language starts with this code (e.g. 'fr')."),
    content_chars: int = Query(1200, ge=0, le=8000, description="Per-sampled-article content excerpt budget."),
) -> JSONResponse:
    """The date-extraction diagnostics log (maintainer↔developer channel): for a
    bounded scan of articles, what the date extractor CAUGHT versus what the text
    LOOKS LIKE — so the extractor can be optimized from real corpus evidence.

    Per article it pairs the live extractor (run exactly as ingest does — the
    article's own publication date as anchor + its language) with a permissive
    recall probe (bare years, CJK 年月日 dates, numeric d/m/y, month/weekday/
    relative words). The probe deliberately OVER-matches: the date-like text it
    flags that the extractor did not turn into a tag is the material for spotting a
    missing pattern. Probe hits are CANDIDATES, never confirmed dates.

    The aggregates cover the whole scan; the per-language table (with
    ``in_month_vocab``) is the clearest signal of a vocabulary gap — a language the
    extractor has no month names for shows near-zero coverage. The detailed sample
    is sorted worst-actionable-miss first. ``stored_tags`` shows what is actually
    persisted for each sampled article, which can differ from the live extractor if
    the article was indexed before an extractor change (re-index to refresh).
    Bounded, on-demand, local; nothing is transmitted. No scores.
    """
    from datetime import date as _date
    from datetime import datetime as _dt
    from datetime import timedelta, timezone

    from src.timemap import datediag, datestore

    today = _date.today()
    # First pass scans only what the aggregates need (title is re-queried for the
    # small sample), so the heavy content column is the only large read here.
    rows = db.query(
        Article.id,
        Article.language,
        Article.published_at,
        Article.created_at,
        Article.content,
    )
    if days:
        rows = rows.filter(Article.published_at >= _dt.now(timezone.utc) - timedelta(days=days))
    if lang:
        rows = rows.filter(Article.language.like(f"{lang}%"))
    rows = rows.order_by(Article.published_at.desc()).limit(scan)

    total_articles = int(db.query(func.count(Article.id)).scalar() or 0)
    scanned = with_extracted = extracted_total = datelike_no_extract = 0
    prec = {"day": 0, "month": 0}
    hist = {"0": 0, "1": 0, "2": 0, "3": 0, "4": 0, "5+": 0}
    per_lang: dict[str, dict] = {}
    probe_kinds: dict[str, int] = {}
    # Light candidates only (id + the three sort keys) so a large scan stays
    # memory-cheap; the heavy per-article records are rebuilt for the sample alone.
    light: list[tuple] = []

    for aid, language, pub, created, content in rows.yield_per(200):
        scanned += 1
        anchor_dt = pub or created
        anchor = anchor_dt.date() if anchor_dt else None
        a = datediag.analyze_article(content, language=language, anchor=anchor, today=today)
        ne = a["n_extracted"]
        extracted_total += ne
        with_extracted += 1 if ne else 0
        for c in a["extracted"]:
            if c.get("precision") in prec:
                prec[c["precision"]] += 1
        hist["5+" if ne >= 5 else str(ne)] += 1
        for k, n in a["probe_by_kind"].items():
            probe_kinds[k] = probe_kinds.get(k, 0) + n
        if a["n_date_like"] and ne == 0:
            datelike_no_extract += 1
        bl = datediag.base_language(language)
        pl = per_lang.setdefault(
            bl,
            {
                "articles": 0,
                "with_extracted": 0,
                "extracted_total": 0,
                "date_like_total": 0,
                "in_month_vocab": bl in datediag.MONTH_VOCAB_LANGS,
            },
        )
        pl["articles"] += 1
        pl["with_extracted"] += 1 if ne else 0
        pl["extracted_total"] += ne
        pl["date_like_total"] += a["n_date_like"]
        light.append((a["actionable_gap"], a["n_date_like"], -ne, aid))

    # Worst actionable miss first (then most date-like text, then fewest extracted).
    light.sort(reverse=True)
    chosen_ids = [t[3] for t in light[:sample]]

    sample_rows: list[dict] = []
    if chosen_ids:
        by_id = {
            r.id: r
            for r in db.query(
                Article.id,
                Article.title,
                Article.language,
                Article.published_at,
                Article.created_at,
                Article.content,
            ).filter(Article.id.in_(chosen_ids))
        }
        for aid in chosen_ids:  # preserve the worst-first order
            r = by_id.get(aid)
            if r is None:
                continue
            anchor_dt = r.published_at or r.created_at
            anchor = anchor_dt.date() if anchor_dt else None
            a = datediag.analyze_article(r.content, language=r.language, anchor=anchor, today=today)
            sample_rows.append(
                {
                    "id": r.id,
                    "title": r.title,
                    "language": r.language,
                    "published_at": r.published_at.isoformat() if r.published_at else None,
                    "anchor": anchor.isoformat() if anchor else None,
                    "actionable_gap": a["actionable_gap"],
                    "n_extracted": a["n_extracted"],
                    "n_date_like": a["n_date_like"],
                    "extracted": a["extracted"],
                    "stored_tags": datestore.for_article(db, r.id),
                    "date_like_in_text": a["date_like_in_text"],
                    "content_excerpt": (r.content or "")[:content_chars],
                    "content_truncated": bool(r.content and len(r.content) > content_chars),
                }
            )

    per_language = {
        lg: {
            **v,
            "coverage_pct": (
                round(100.0 * v["with_extracted"] / v["articles"], 1) if v["articles"] else 0.0
            ),
        }
        for lg, v in sorted(per_lang.items(), key=lambda kv: -kv[1]["articles"])
    }

    payload = {
        "corpus": {
            "articles_total": total_articles,
            "scanned": scanned,
            "articles_with_extracted_dates": with_extracted,
            "coverage_pct": round(100.0 * with_extracted / scanned, 1) if scanned else 0.0,
            "extracted_dates_total": extracted_total,
            "precision_distribution": prec,
            "dates_per_article": hist,
            "articles_with_datelike_text_but_no_extraction": datelike_no_extract,
        },
        "per_language": per_language,
        "date_like_text_by_kind": probe_kinds,
        "sample": sample_rows,
        "method": (
            "Per article: 'extracted' = the live extractor run exactly as ingest does "
            "(the article's publication date as anchor + its language); "
            "'date_like_in_text' = a PERMISSIVE recall probe (bare years, CJK 年月日, "
            "numeric d/m/y, month/weekday/relative words) that over-matches so its "
            "difference from 'extracted' shows what the extractor missed; 'stored_tags' "
            "= what is actually persisted (can lag the extractor until a re-index). "
            "per_language coverage + in_month_vocab is the vocabulary-gap signal (a "
            "language with no month table shows near-zero coverage). Sample sorted "
            "worst-actionable-miss first (bare years excluded from 'actionable' — the "
            "extractor skips them by design). Aggregates over the whole scan; counts only."
        ),
        "caveat": (
            "The recall probe is HIGH recall, LOW precision — a hit is a candidate, not a "
            "confirmed date (a '2020' may be a quantity; a weekday may be generic). Low "
            "coverage for an out-of-vocabulary language is the expected signal, not a bug. "
            "Bounded scan/sample (says so via 'scanned' vs 'articles_total'); on-demand, "
            "local, never transmitted."
        ),
    }
    body = envelope(
        kind="date-diagnostics",
        query={"scan": scan, "sample": sample, "days": days, "lang": lang},
        count=len(sample_rows),
        payload=payload,
    )
    fname = f"oo-date-diagnostics-{_dt.now().strftime('%Y%m%d')}.json"
    return JSONResponse(body, headers={"Content-Disposition": f'attachment; filename="{fname}"'})
