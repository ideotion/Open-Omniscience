"""Temporal-map API: space-time signals on one zoomable map + time axis.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Read-only and offline by default. Returns normalised signals — curated anchors,
the recurring-events agenda, geocoded corpus — each with a coordinate and a
fractional-year ``t`` so the front-end slider can sweep from antiquity to the near
future. Live geophysical hazards are layered in best-effort *only when asked*
(``hazards=true``), and any fetch failure is reported, never hidden.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.database.session import get_db
from src.timemap.collect import (
    KNOWN_KINDS,
    article_mentions_to_signals,
    articles_to_signals,
    collect,
    time_range,
)

router = APIRouter(prefix="/api/timemap", tags=["timemap"])

_CAVEAT = (
    "Each pin needs BOTH a place and a date. Signals without a coordinate are absent, "
    "not plotted at (0,0); a missing pin means 'not located', never 'did not happen'. "
    "Country-level pins (geocode=country) are approximate stand-in points, not the exact "
    "spot. Future entries are scheduled/astronomical dates and can still change."
)


def _kinds_param(kinds: str | None) -> set[str] | None:
    if not kinds:
        return None
    want = {k.strip() for k in kinds.split(",") if k.strip()}
    return want or None


def _hazard_signals(db: Session | None = None) -> tuple[list[dict], list[str]]:
    """Hazards as map signals, from the LOCAL snapshot — ZERO network on render
    (2026-07-24 field-feedback A6, ruled: never a live fetch for map use; the
    consented refresh action is what populates the snapshot, elsewhere).
    Returns (signals, failures) — an absent/stale snapshot is an honest empty
    result with a note, never a fabricated fetch-error."""
    try:
        from datetime import datetime

        from src.hazards.store import load_snapshot
        from src.timemap import year_float
    except Exception:
        return [], ["hazards module not installed"]
    snap = load_snapshot()
    if not snap.get("available"):
        return [], ["no local hazard snapshot yet — refresh it in Settings to see hazards here"]
    failures: list[str] = ["hazard snapshot is stale"] if snap.get("stale") else []

    # Batch-resolve the internal Article id per event (one query, never N+1) so a
    # click can deep-link to the local reader (item 2's "INTERNAL article/reader
    # link"), when the record has already been ingested as a corpus Article.
    article_by_url: dict[str, int] = {}
    if db is not None:
        try:
            from src.database.models import Article
            from src.hazards.ingest import hazard_canonical_url

            urls = [
                hazard_canonical_url(str(r.get("source")), str(r.get("id")))
                for r in (snap.get("records") or [])
                if isinstance(r, dict) and r.get("source") and r.get("id")
            ]
            if urls:
                rows = (
                    db.query(Article.canonical_url, Article.id)
                    .filter(Article.canonical_url.in_(urls))
                    .all()
                )
                article_by_url = {u: aid for u, aid in rows}
        except Exception:  # noqa: BLE001 - the article-id link is a bonus, never load-bearing
            article_by_url = {}

    sigs: list[dict] = []
    for h in snap.get("records") or []:
        if not isinstance(h, dict):
            continue
        if h.get("lat") is None or h.get("lon") is None or not h.get("time"):
            continue
        try:
            d = datetime.fromisoformat(str(h["time"]).replace("Z", "+00:00")).date()
        except (TypeError, ValueError):
            continue
        event_url = None
        if h.get("source") and h.get("id"):
            from src.hazards.ingest import hazard_canonical_url

            # str() defensively -- the snapshot body is an unvalidated posted dict
            # (HazardSnapshotBody.records: list[dict]), so a non-string source/id
            # must never crash this whole loop (a skeptic-caught defect: this call
            # used to pass the raw values straight through).
            event_url = hazard_canonical_url(str(h["source"]), str(h["id"]))
        sigs.append(
            {
                "id": "hazard:" + str(h.get("id") or h.get("url") or h.get("place")),
                "title": h.get("place") or h.get("type") or "Hazard",
                "kind": "hazard",
                "lat": float(h["lat"]),
                "lon": float(h["lon"]),
                "t": round(year_float(d), 3),
                "date": d.isoformat(),
                "year": d.year,
                "date_precision": "day",
                "confirmed": True,
                "place": h.get("place"),
                "country": None,
                "url": h.get("url"),
                "note": h.get("severity"),
                "source": "hazards",
                "geocode": "exact",
                "severity": h.get("severity"),
                "magnitude": h.get("magnitude"),
                # The internal reader link (None until the record is ingested as a
                # corpus Article — never fabricated).
                "article_id": article_by_url.get(event_url) if event_url else None,
                "hazard_type": h.get("type"),
            }
        )
    return sigs, failures


def _article_signals(db: Session, days: int | None, limit: int) -> list[dict]:
    """Recent corpus articles (with a publication date + geocodable source) as signals."""
    from datetime import datetime, timedelta

    from src.database.models import Article

    q = db.query(Article).filter(Article.published_at.isnot(None))
    if days:
        q = q.filter(Article.published_at >= datetime.utcnow() - timedelta(days=days))
    rows = []
    for a in q.order_by(Article.published_at.desc()).limit(limit).all():
        src = getattr(a, "source", None)
        meta = getattr(src, "source_metadata", None) if src else None
        rows.append(
            {
                "title": a.title,
                "url": a.url,
                "published": a.published_at,
                "language": a.language,
                "country": a.country or (getattr(src, "country", None) if src else None),
                "city": getattr(meta, "city", None) if meta else None,
            }
        )
    return articles_to_signals(rows)


def _mention_signals(db: Session, days: int | None, limit: int) -> list[dict]:
    """Explicit dates mentioned in recent article *text* (extracted, unconfirmed)."""
    from datetime import datetime, timedelta

    from src.database.models import Article

    # Scanning full text is heavier than reading a timestamp; bound the article count.
    scan = min(limit, 600)
    q = db.query(Article).filter(Article.published_at.isnot(None))
    if days:
        q = q.filter(Article.published_at >= datetime.utcnow() - timedelta(days=days))
    rows = []
    for a in q.order_by(Article.published_at.desc()).limit(scan).all():
        src = getattr(a, "source", None)
        meta = getattr(src, "source_metadata", None) if src else None
        rows.append(
            {
                "title": a.title,
                "url": a.url,
                "content": a.content,
                "country": a.country or (getattr(src, "country", None) if src else None),
                "city": getattr(meta, "city", None) if meta else None,
            }
        )
    return article_mentions_to_signals(rows)


@router.get("")
def list_signals(
    kinds: str | None = Query(None, description="comma-separated kinds to keep"),
    start: float | None = Query(None, description="earliest fractional year, e.g. 1900"),
    end: float | None = Query(None, description="latest fractional year, e.g. 2030"),
    hazards: bool = Query(
        False,
        description="layer in geophysical hazards from the LOCAL snapshot (zero network — "
        "refresh the snapshot separately, in Settings)",
    ),
    articles: bool = Query(
        False, description="layer in geocoded corpus articles (publication date)"
    ),
    mentions: bool = Query(
        False, description="layer in dates mentioned in article text (extracted)"
    ),
    days: int | None = Query(
        None, ge=1, le=36500, description="only articles from the last N days"
    ),
    limit: int = Query(2000, ge=1, le=10000),
    db: Session = Depends(get_db),
) -> dict:
    """Space-time signals within an optional time window and kind filter."""
    extra: list[dict] = []
    failures: list[str] = []
    if hazards:
        extra, failures = _hazard_signals(db)
    if articles:
        try:
            extra += _article_signals(db, days, limit)
        except Exception as exc:  # pragma: no cover - DB guard
            failures.append(f"corpus articles unavailable: {exc}")
    if mentions:
        try:
            extra += _mention_signals(db, days, limit)
        except Exception as exc:  # pragma: no cover - DB guard
            failures.append(f"mentioned dates unavailable: {exc}")
    sig = collect(kinds=_kinds_param(kinds), start=start, end=end, extra=extra)
    if len(sig) > limit:
        # Cap the payload without discarding the curated backbone or the *recent* end:
        # keep every anchor, then the newest of everything else (collect sorts ascending,
        # so naive sig[:limit] would have dropped the recent corpus the caller asked for).
        anchors = [s for s in sig if s.get("source") == "anchor"]
        rest = [s for s in sig if s.get("source") != "anchor"]
        rest = sorted(rest, key=lambda s: s["t"], reverse=True)[: max(0, limit - len(anchors))]
        sig = sorted(anchors + rest, key=lambda s: s["t"])
    return {
        "signals": sig,
        "count": len(sig),
        "range": time_range(sig),
        "kinds": list(KNOWN_KINDS),
        "failures": failures,
        "caveat": _CAVEAT,
    }


@router.get("/range")
def full_range(hazards: bool = Query(False)) -> dict:
    """The full time extent + per-kind counts across all sources (sets the slider)."""
    extra: list[dict] = []
    if hazards:
        extra, _ = _hazard_signals()
    return time_range(collect(extra=extra))
