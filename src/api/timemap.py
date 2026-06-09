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


def _hazard_signals() -> tuple[list[dict], list[str]]:
    """Best-effort live hazards as signals. Returns (signals, failures)."""
    try:
        from datetime import datetime

        from src.api.hazards import fetch_hazards  # type: ignore
        from src.timemap import year_float
    except Exception:
        return [], ["hazards module not installed"]
    sigs: list[dict] = []
    failures: list[str] = []
    try:
        raw, failures = fetch_hazards(source="all")
    except Exception as exc:  # pragma: no cover - network/runtime guard
        return [], [f"hazard fetch error: {exc}"]
    for h in raw or []:
        if h.get("lat") is None or h.get("lon") is None or not h.get("time"):
            continue
        try:
            d = datetime.fromisoformat(str(h["time"]).replace("Z", "+00:00")).date()
        except (TypeError, ValueError):
            continue
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
    hazards: bool = Query(False, description="layer in live geophysical hazards (network)"),
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
        extra, failures = _hazard_signals()
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
