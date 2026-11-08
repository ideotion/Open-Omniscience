"""The IPCC AR6 Summaries for Policymakers: what is stored, and the one click that fetches one.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

ONE route egresses, and it is the only one gated: ``POST /spm/{key}/fetch`` downloads one
SPM PDF from ``www.ipcc.ch`` (``src/ingest/ipcc_spm.py``). It refuses with a 409 that NAMES
airplane mode (invariant #14e's corollary) and with a 400 unless the caller says
``consent: true``: the UI passes the ONE network consent first, and a caller that never opened
the UI meets the same refusal (invariant #14f). The fetch runs as a background job, so the task
manager shows it and one run at a time is a fact of the job kind, not of a lock somebody can
forget: two simultaneous clicks cannot both insert (``Article.url`` is not unique). The listing
route reads the local database and makes no request.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.database.session import get_db
from src.jobs.background import BackgroundJob, register_job

router = APIRouter(prefix="/api/ipcc", tags=["ipcc"])


def _spm_worker(ctx, *, key: str) -> dict:
    from src.database.session import session_scope
    from src.ingest.ipcc_spm import fetch_spm, ingest_spm

    ctx.set_progress(done=0, total=2, detail="fetching")
    data = fetch_spm(key)
    ctx.set_progress(done=1, total=2, detail="reading")
    with session_scope() as db:
        return ingest_spm(db, key, data)


#: A WRITER: ``ingest_spm`` commits one Article and its keyword rows to the corpus file, so the
#: offline maintenance hold-off must see it. NOT cancellable, honestly: the download is one
#: blocking GET with no stop flag to check, and a Cancel button that did nothing would be theater.
_SPM_JOB = register_job(
    BackgroundJob(
        "ipcc-spm", "Fetching an IPCC report", _spm_worker, is_writer=True, cancellable=False
    )
)


class _FetchBody(BaseModel):
    consent: bool = False


@router.get("/spm")
def spm_list(db: Session = Depends(get_db)) -> dict:
    """The catalog and what this install already holds. Local only: no request leaves the machine."""
    from src.database.models import Article
    from src.ingest.ipcc_spm import DISCLOSURE, IPCC_AS_OF, IPCC_HOST, SPM_CATALOG

    urls = [e.url for e in SPM_CATALOG]
    stored = {
        url: (aid, ts)
        for aid, url, ts in db.query(Article.id, Article.url, Article.created_at)
        .filter(Article.url.in_(urls))
        .all()
    }
    items = []
    for e in SPM_CATALOG:
        hit = stored.get(e.url)
        items.append(
            {
                "key": e.key,
                "title": e.title,
                "working_group": e.working_group,
                "approved": e.approved,
                "stored": hit is not None,
                "article_id": hit[0] if hit else None,
                "stored_at": hit[1].isoformat() if hit and hit[1] else None,
            }
        )
    return {
        "items": items,
        "host": IPCC_HOST,
        "catalog_as_of": IPCC_AS_OF,
        "disclosure": DISCLOSURE,
        "method": "Read from this install's own database; nothing is requested from the network.",
    }


@router.post("/spm/{key}/fetch")
def spm_fetch(key: str, body: _FetchBody) -> dict:
    """Fetch one SPM from www.ipcc.ch (EGRESSES), read it and store it as an Article."""
    from src.ingest import kill_switch_active
    from src.ingest.fetch_verdict import NETWORK_REFUSED
    from src.ingest.ipcc_spm import SPM_CATALOG

    if key not in {e.key for e in SPM_CATALOG}:
        raise HTTPException(status_code=404, detail="unknown IPCC report")
    if kill_switch_active():
        raise HTTPException(status_code=409, detail=NETWORK_REFUSED)
    if not body.consent:
        raise HTTPException(
            status_code=400, detail="consent required: this sends a request to www.ipcc.ch"
        )
    try:
        return {"started": True, "job": _SPM_JOB.start(key=key)}
    except RuntimeError:
        # Already running: the live status, not an error, so a double click is harmless.
        return {"started": False, "job": _SPM_JOB.status()}


@router.get("/spm/status")
def spm_status() -> dict:
    """Live status of the IPCC fetch job (state, progress, result, error)."""
    return _SPM_JOB.status()
