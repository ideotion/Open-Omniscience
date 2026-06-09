"""
Ingestion API: trigger ethical scraping of a source feed or a single URL.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Endpoints are synchronous (`def`) so they run in Starlette's threadpool: fetching
is blocking, rate-limited I/O and must not block the event loop. A single module
level EthicalFetcher is shared so per-host rate-limit / robots state persists
across requests.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.database.models import Source
from src.database.session import get_db
from src.ingest import EthicalFetcher  # noqa: F401 (kept for type/back-compat)
from src.ingest.email import fetch_imap, ingest_emails
from src.ingest.pipeline import ingest_source, ingest_url
from src.ingest.seed_sources import seed_default_sources
from src.safety.fetcher import make_fetcher

router = APIRouter(prefix="/api", tags=["ingestion"])

# Shared fetcher: keeps robots cache + per-host rate-limit timers across requests.
_fetcher = make_fetcher()


def get_fetcher() -> EthicalFetcher:
    """Dependency returning the shared fetcher (overridable in tests)."""
    return _fetcher


class IngestUrlRequest(BaseModel):
    source_id: int
    url: str


class BatchIngestRequest(BaseModel):
    source_ids: list[int]


class IngestEmailRequest(BaseModel):
    host: str
    user: str
    password: str
    folder: str = "INBOX"
    limit: int = 50
    use_ssl: bool = True


def _get_source(db: Session, source_id: int) -> Source:
    source = db.query(Source).filter_by(id=source_id).first()
    if source is None:
        raise HTTPException(status_code=404, detail=f"Source id {source_id} not found.")
    return source


@router.post("/sources/seed-defaults")
def seed_defaults_endpoint(db: Session = Depends(get_db)) -> dict:
    """Register the curated starter sources (idempotent; nothing is fetched)."""
    result = seed_default_sources(db)
    return {"seeded": result}


@router.post("/sources/{source_id}/ingest")
def ingest_source_endpoint(
    source_id: int,
    db: Session = Depends(get_db),
    fetcher: EthicalFetcher = Depends(get_fetcher),
) -> dict:
    """Ingest a source's RSS/Atom feed through the ethical fetch path.

    Returns a tally of outcomes (stored / duplicate / blocked_robots / ...).
    """
    source = _get_source(db, source_id)
    if not source.rss_url:
        raise HTTPException(
            status_code=400,
            detail=f"Source '{source.name}' has no rss_url; use POST /api/ingest for single URLs.",
        )
    tally = ingest_source(db, source, fetcher=fetcher)
    return {"source_id": source_id, "source": source.name, "tally": tally}


@router.post("/sources/ingest-batch")
def ingest_batch_endpoint(
    req: BatchIngestRequest,
    db: Session = Depends(get_db),
    fetcher: EthicalFetcher = Depends(get_fetcher),
) -> dict:
    """Fetch the RSS/Atom feeds of many sources in one run (the batch picker).

    Best-effort: each selected source is fetched through the same ethical path
    (robots fail-closed, rate-limited) and reported individually — one bad feed
    never aborts the batch. Bounded to 50 sources per call so a click can't kick
    off an unbounded crawl; sources without a feed are skipped with a clear status.
    Synchronous (runs in the threadpool); a queued/background variant is a future
    step for very large batches.
    """
    ids = list(dict.fromkeys(req.source_ids))[:50]  # de-dup, cap
    if not ids:
        raise HTTPException(status_code=400, detail="No source_ids provided.")
    results: list[dict] = []
    aggregate: dict[str, int] = {}
    ingested = 0
    for sid in ids:
        source = db.query(Source).filter_by(id=sid).first()
        if source is None:
            results.append({"source_id": sid, "status": "not_found"})
            continue
        if not source.rss_url:
            results.append({"source_id": sid, "source": source.name, "status": "no_feed"})
            continue
        try:
            tally = ingest_source(db, source, fetcher=fetcher)
            results.append({"source_id": sid, "source": source.name, "status": "ok", "tally": tally})
            ingested += 1
            for k, v in tally.items():
                if isinstance(v, int):
                    aggregate[k] = aggregate.get(k, 0) + v
        except Exception as exc:  # noqa: BLE001 - one bad feed must not abort the batch
            db.rollback()
            results.append({"source_id": sid, "source": source.name, "status": "error", "detail": str(exc)})
    return {"requested": len(ids), "ingested": ingested, "aggregate": aggregate, "results": results}


@router.post("/sources/{source_id}/ingest-email")
def ingest_email_endpoint(
    source_id: int,
    req: IngestEmailRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Fetch emails from an IMAP mailbox and fold them into the corpus.

    Credentials are used transiently (not stored). Emails become searchable
    Article rows under the given source. Single-user, loopback-only by design.
    """
    source = _get_source(db, source_id)
    raws = fetch_imap(
        req.host, req.user, req.password,
        folder=req.folder, limit=req.limit, use_ssl=req.use_ssl,
    )
    tally = ingest_emails(db, source, raws)
    return {"source_id": source_id, "source": source.name, "fetched": len(raws), "tally": tally}


@router.post("/ingest")
def ingest_url_endpoint(
    req: IngestUrlRequest,
    db: Session = Depends(get_db),
    fetcher: EthicalFetcher = Depends(get_fetcher),
) -> dict:
    """Ingest a single article URL under the given source."""
    source = _get_source(db, req.source_id)
    outcome = ingest_url(db, source, req.url, fetcher=fetcher)
    return {
        "url": outcome.url,
        "result": outcome.result.value,
        "article_id": outcome.article_id,
        "detail": outcome.detail,
    }
