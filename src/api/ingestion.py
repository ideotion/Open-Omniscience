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

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.database.models import Source
from src.database.session import get_db
from src.ingest import EthicalFetcher  # noqa: F401 (kept for type/back-compat)
from src.ingest.email import fetch_imap, fetch_mailbox, ingest_emails
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
            results.append(
                {"source_id": sid, "source": source.name, "status": "ok", "tally": tally}
            )
            ingested += 1
            for k, v in tally.items():
                if isinstance(v, int):
                    aggregate[k] = aggregate.get(k, 0) + v
        except Exception as exc:  # noqa: BLE001 - one bad feed must not abort the batch
            db.rollback()
            results.append(
                {"source_id": sid, "source": source.name, "status": "error", "detail": str(exc)}
            )
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
    try:
        raws = fetch_imap(
            req.host,
            req.user,
            req.password,
            folder=req.folder,
            limit=req.limit,
            use_ssl=req.use_ssl,
        )
    except RuntimeError as exc:  # the airplane-mode refusal (ruling #11 kill-switch gate)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    tally = ingest_emails(db, source, raws)
    return {"source_id": source_id, "source": source.name, "fetched": len(raws), "tally": tally}


# A single dedicated, FILTERABLE provenance bucket for locally-imported .eml
# newsletters (email-vs-web stays separable, like the DDG-discovered class). It is
# DISABLED so the scheduler never touches it — these articles arrive ONLY by explicit
# local file import, never the network. (Per-publisher eTLD+1 source resolution — the
# S2 design — is a deliberate follow-up; v1 never fuzzy-merges, the conservative call.)
_NEWSLETTER_DOMAIN = "newsletters.import.local"
_NEWSLETTER_NAME = "Imported newsletters (.eml)"


def _get_newsletter_source(db: Session) -> Source:
    src = db.query(Source).filter_by(domain=_NEWSLETTER_DOMAIN).first()
    if src is None:
        src = Source(name=_NEWSLETTER_NAME, domain=_NEWSLETTER_DOMAIN, enabled=False)
        db.add(src)
        db.commit()
        db.refresh(src)
    return src


@router.post("/newsletters/import")
def import_newsletters(
    files: list[UploadFile] = File(..., description="local .eml files to import"),
    db: Session = Depends(get_db),
) -> dict:
    """Import local ``.eml`` newsletter files into the unified corpus, ANONYMISED at
    ingest. **ZERO network**: each file is parsed, de-tracked and stored locally —
    nothing is ever fetched (tracker pixels / wrapped links are NEVER followed, so an
    import can never confirm an open or a click). The recipient is never stored; the
    returned tally reports exactly what anonymisation stripped (recipient echoes
    redacted, tracker query-params removed, server-side tracker wrappers flagged) so
    the user sees it honestly. Local-only, single-user, loopback by design.
    """
    raws: list[bytes] = []
    skipped_non_eml = 0
    for f in files:
        name = (f.filename or "").lower()
        if not name.endswith(".eml"):
            skipped_non_eml += 1
            continue
        try:
            raws.append(f.file.read())
        except Exception:
            skipped_non_eml += 1
    source = _get_newsletter_source(db)
    tally = ingest_emails(db, source, raws)
    tally["skipped_non_eml"] = skipped_non_eml
    return {
        "source": source.name,
        "source_id": source.id,
        "received": len(files),
        "tally": tally,
    }


# A dedicated, FILTERABLE provenance bucket for LIVE mailbox (IMAP/POP3) imports —
# DISTINCT from the file-.eml bucket so live-vs-file provenance stays separable (the
# ledger's email-vs-web separability principle). DISABLED: the scheduler never touches
# it; mail arrives only by explicit, consented pull.
_MAILBOX_DOMAIN = "mailbox.import.local"
_MAILBOX_NAME = "Imported mailbox (IMAP/POP3)"


def _get_mailbox_source(db: Session) -> Source:
    src = db.query(Source).filter_by(domain=_MAILBOX_DOMAIN).first()
    if src is None:
        src = Source(name=_MAILBOX_NAME, domain=_MAILBOX_DOMAIN, enabled=False)
        db.add(src)
        db.commit()
        db.refresh(src)
    return src


class MailboxFetchRequest(BaseModel):
    protocol: str = "imap"  # "imap" | "pop3"
    host: str
    user: str
    password: str
    port: int = 0  # 0 = protocol default (993/995 SSL, 143/110 plain)
    folder: str = "INBOX"  # IMAP only
    limit: int = 50
    use_ssl: bool = True


@router.post("/newsletters/mailbox")
def import_mailbox(req: MailboxFetchRequest, db: Session = Depends(get_db)) -> dict:
    """Pull newsletters LIVE from a mailbox (IMAP/POP3), ANONYMISED at ingest (ruling #11).

    The maintainer reversed the local-.eml-only stance: this fetches messages directly so
    you do not have to export .eml files. Each message goes through the SAME anonymise-at-
    ingest core as the file import — the recipient is NEVER stored, no raw message is
    retained, and tracking links are de-toxed (pixels/wrapped links are NEVER followed, so
    a pull can never confirm an open/click). Credentials are used for this one fetch and
    NOT stored.

    NETWORK + HONESTY: this is a consented network action — it is REFUSED under airplane
    mode (409, no socket). The connection egresses to your mail provider directly over TLS
    (like any email client), revealing your IP to that provider; it is NOT routed through
    Tor (IMAP/POP3 is not the HTTP guarded path). The returned tally reports exactly what
    anonymisation stripped, so you see it honestly.
    """
    kwargs: dict = {"limit": req.limit, "use_ssl": req.use_ssl}
    if req.port:
        kwargs["port"] = req.port
    if (req.protocol or "").lower() == "imap":
        kwargs["folder"] = req.folder
    try:
        raws = fetch_mailbox(req.protocol, req.host, req.user, req.password, **kwargs)
    except RuntimeError as exc:  # airplane-mode refusal (kill switch)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:  # unknown protocol / missing host
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # transport / auth failure -> degrade loudly
        raise HTTPException(status_code=502, detail=f"mailbox fetch failed: {exc}") from exc
    source = _get_mailbox_source(db)
    tally = ingest_emails(db, source, raws)
    return {
        "source": source.name,
        "source_id": source.id,
        "protocol": (req.protocol or "imap").lower(),
        "fetched": len(raws),
        "tally": tally,
        "disclosure": (
            "Pulled live from your mailbox over TLS and anonymised at ingest: the "
            "recipient is never stored, no raw message is retained, tracking links are "
            "de-toxed and never followed. Your IP is visible to the mail provider (not "
            "via Tor). Stored under a disabled, filterable 'mailbox' source."
        ),
    }


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
