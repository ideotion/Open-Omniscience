"""
Monitoring API: real source health + corpus-volume anomalies.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.api.ingestion import get_fetcher
from src.database.models import Article, Source
from src.database.session import get_db
from src.ingest import EthicalFetcher
from src.monitoring.anomaly import volume_anomalies
from src.monitoring.health import check_source

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


@router.get("/health")
def sources_health(
    limit: int = Query(25, ge=1, le=200, description="Max sources to probe in one call"),
    db: Session = Depends(get_db),
    fetcher: EthicalFetcher = Depends(get_fetcher),
) -> dict:
    """Run a real reachability check against enabled sources.

    Checks run sequentially through the rate-limited fetcher, so a hard cap
    (``limit``) prevents an accidental very-long hang when the catalog is large
    (the seeded catalog has ~1,800 sources).
    """
    sources = (db.query(Source)
               .filter((Source.enabled.is_(True)) | (Source.enabled.is_(None)))
               .order_by(Source.priority, Source.id)
               .limit(limit).all())
    results = [check_source(s, fetcher=fetcher).to_dict() for s in sources]
    summary = Counter(r["status"] for r in results)
    return {"checked": len(results), "limit": limit, "summary": dict(summary), "sources": results}


@router.get("/anomalies")
def corpus_anomalies(
    z_threshold: float = Query(2.0, ge=0.5),
    db: Session = Depends(get_db),
) -> dict:
    """Flag days whose article volume deviates >= z_threshold SDs from the mean."""
    rows = db.query(Article.published_at).filter(Article.published_at.isnot(None)).all()
    daily = Counter(r[0].date() for r in rows)
    anomalies = volume_anomalies(dict(daily), z_threshold=z_threshold)
    return {
        "days_observed": len(daily),
        "z_threshold": z_threshold,
        "anomalies": [a.to_dict() for a in anomalies],
    }
