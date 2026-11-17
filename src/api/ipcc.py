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

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
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
def spm_fetch(key: str, body: _FetchBody | None = None) -> dict:
    """Fetch one SPM from www.ipcc.ch (EGRESSES), read it and store it as an Article."""
    from src.ingest import kill_switch_active
    from src.ingest.fetch_verdict import NETWORK_REFUSED
    from src.ingest.ipcc_spm import SPM_CATALOG

    if key not in {e.key for e in SPM_CATALOG}:
        raise HTTPException(status_code=404, detail="unknown IPCC report")
    if kill_switch_active():
        raise HTTPException(status_code=409, detail=NETWORK_REFUSED)
    if body is None or not body.consent:
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


# --- Row 121 (G4): suggested predictions, curated by the operator --------------------------------
#
# Both routes are LOCAL: they read the copy of the report already in the corpus and write a person's
# decision to the corpus file. Neither sends a request anywhere, so neither is consent-gated. The
# decision route is a POST (R694: a write is never a GET).

_DECISIONS = ("kept", "set_aside", "undecided")


class _DecideBody(BaseModel):
    sentence_hash: str
    decision: str


def _stored_spm(db: Session, key: str):
    from src.database.models import Article
    from src.ingest.ipcc_spm import SPM_CATALOG

    entry = next((e for e in SPM_CATALOG if e.key == key), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown IPCC report")
    art = db.query(Article).filter(Article.url == entry.url).order_by(Article.id).first()
    return entry, art


@router.get("/spm/{key}/predictions")
def spm_predictions(key: str, db: Session = Depends(get_db)) -> dict:
    """The sentences the wording rule suggests in one stored SPM, each with the operator's decision.

    Local only: reads the stored copy and this install's decisions; nothing is requested from the network.
    """
    from src.database.models import IpccPrediction
    from src.ingest.ipcc_predictions import (
        CAVEAT,
        METHOD,
        METHOD_VERSION,
        SENTENCE_MAX_CHARS,
        suggest,
    )
    from src.ingest.ipcc_spm import DISCLOSURE

    entry, art = _stored_spm(db, key)
    base = {
        "key": key,
        "title": entry.title,
        "caveat": CAVEAT,
        "method": METHOD,
        "method_version": METHOD_VERSION,
        "disclosure": DISCLOSURE,
    }
    decided = {
        r.sentence_hash: r
        for r in db.query(IpccPrediction).filter(IpccPrediction.spm_key == key).all()
    }
    if art is None:
        return {**base, "stored": False, "items": [], "not_suggested_now": _orphans(decided, set()),
                "counts": {"suggested": 0, "kept": 0, "set_aside": 0, "undecided": 0}}
    reading = suggest(art.get_content(), entry.approved)
    items = []
    for s in reading.suggestions:
        row = decided.get(s.hash)
        items.append({**s.as_dict(), "decision": row.decision if row else None})
    shown = {s.hash for s in reading.suggestions}
    kept = sum(1 for i in items if i["decision"] == "kept")
    aside = sum(1 for i in items if i["decision"] == "set_aside")
    return {
        **base,
        "stored": True,
        "article_id": art.id,
        "items": items,
        # Decisions on sentences this method no longer suggests (an older method, or a changed copy): kept in full.
        "not_suggested_now": _orphans(decided, shown),
        "counts": {
            "suggested": len(items),
            "kept": kept,
            "set_aside": aside,
            "undecided": len(items) - kept - aside,
            "sentences_read": reading.sentences_read,
            "too_long": reading.too_long,
        },
        "too_long_max_chars": SENTENCE_MAX_CHARS,
    }


def _orphans(decided: dict, shown: set[str]) -> list[dict]:
    return [
        {
            "hash": h,
            "sentence": r.sentence,
            "decision": r.decision,
            "method_version": r.method_version,
            "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        }
        for h, r in sorted(decided.items(), key=lambda kv: (kv[1].decided_at or datetime.min, kv[0]))
        if h not in shown
    ]


@router.post("/spm/{key}/predictions/decide")
def spm_prediction_decide(key: str, body: _DecideBody, db: Session = Depends(get_db)) -> dict:
    """Keep a suggested sentence as a prediction, set it aside, or take the decision back (``undecided``).

    The sentence is named by its hash; the text stored is the server's own copy, never the caller's. A hash that is
    neither a current suggestion nor an existing decision is refused, so nothing but the report's own sentences is kept.
    """
    from src.database.models import IpccPrediction
    from src.ingest.ipcc_predictions import METHOD_VERSION, suggest

    if body.decision not in _DECISIONS:
        raise HTTPException(status_code=422, detail="decision must be kept, set_aside or undecided")
    h = (body.sentence_hash or "").strip().lower()
    if len(h) != 64 or any(c not in "0123456789abcdef" for c in h):
        raise HTTPException(status_code=422, detail="sentence_hash must be 64 hexadecimal characters")
    entry, art = _stored_spm(db, key)
    row = (
        db.query(IpccPrediction)
        .filter(IpccPrediction.spm_key == key, IpccPrediction.sentence_hash == h)
        .first()
    )
    if body.decision == "undecided":
        if row is not None:
            db.delete(row)
            db.commit()
        return {"key": key, "sentence_hash": h, "decision": None}
    if row is None:
        if art is None:
            raise HTTPException(status_code=404, detail="this IPCC report is not stored in your corpus")
        hit = next((s for s in suggest(art.get_content(), entry.approved).suggestions if s.hash == h), None)
        if hit is None:
            raise HTTPException(status_code=404, detail="no such suggested sentence in the stored report")
        db.add(
            IpccPrediction(
                spm_key=key,
                sentence_hash=h,
                sentence=hit.sentence,
                decision=body.decision,
                method_version=METHOD_VERSION,
                decided_at=datetime.now(UTC),
            )
        )
    else:
        row.decision = body.decision
        row.decided_at = datetime.now(UTC)
    try:
        db.commit()
    except IntegrityError:
        # Two clicks raced to insert the same sentence: the other one's row is there now, so this decision updates it.
        db.rollback()
        db.query(IpccPrediction).filter(
            IpccPrediction.spm_key == key, IpccPrediction.sentence_hash == h
        ).update({"decision": body.decision, "decided_at": datetime.now(UTC)})
        db.commit()
    return {"key": key, "sentence_hash": h, "decision": body.decision}
