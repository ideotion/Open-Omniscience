"""
World-law API: tracked legal documents, change feed, and on-demand tracking.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Read endpoints list tracked documents (coverage by jurisdiction) and the flagged-change
feed; ``track`` fetches watched documents now through the ethical fetcher. A research
mirror, never legal advice — every record links back to its official source.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.database.models import LawDocument, LawRevision
from src.database.session import get_db

router = APIRouter(prefix="/api/law", tags=["law"])

_CAVEAT = ("A research mirror, not the authoritative source and not legal advice. Every "
           "document links back to its official gazette; changes are surfaced, never judged.")


def _doc_dict(doc: LawDocument, *, revisions: int = 0, flagged: int = 0) -> dict:
    return {
        "id": doc.id, "jurisdiction": doc.jurisdiction, "title": doc.title,
        "url": doc.url, "official_url": doc.official_url, "category": doc.category,
        "consolidated": bool(doc.consolidated), "watched": bool(doc.watched),
        "has_baseline": doc.baseline_text is not None,
        "last_checked_at": doc.last_checked_at.isoformat() if doc.last_checked_at else None,
        "last_status": doc.last_status, "revisions": revisions, "flagged": flagged,
    }


@router.get("/status")
def law_status(db: Session = Depends(get_db)) -> dict:
    """Coverage overview: documents per jurisdiction + change/flag totals."""
    by_jur = dict(
        db.query(LawDocument.jurisdiction, func.count(LawDocument.id))
        .group_by(LawDocument.jurisdiction).all()
    )
    return {
        "documents": db.query(func.count(LawDocument.id)).scalar() or 0,
        "jurisdictions": {k: int(v) for k, v in sorted(by_jur.items())},
        "tracked": db.query(func.count(LawDocument.id)).filter(LawDocument.baseline_text.isnot(None)).scalar() or 0,
        "changes": db.query(func.count(LawRevision.id)).filter(LawRevision.delta_bytes != 0).scalar() or 0,
        "flagged": db.query(func.count(LawRevision.id)).filter_by(flagged=True).scalar() or 0,
        "caveat": _CAVEAT,
    }


@router.get("/documents")
def law_documents(
    jurisdiction: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """List tracked legal documents (optionally by jurisdiction)."""
    q = db.query(LawDocument)
    if jurisdiction:
        q = q.filter(LawDocument.jurisdiction == jurisdiction)
    docs = q.order_by(LawDocument.jurisdiction, LawDocument.id).all()
    rev_counts = dict(
        db.query(LawRevision.document_id, func.count(LawRevision.id))
        .group_by(LawRevision.document_id).all()
    )
    flag_counts = dict(
        db.query(LawRevision.document_id, func.count(LawRevision.id))
        .filter_by(flagged=True).group_by(LawRevision.document_id).all()
    )
    return {"caveat": _CAVEAT, "documents": [
        _doc_dict(d, revisions=rev_counts.get(d.id, 0), flagged=flag_counts.get(d.id, 0)) for d in docs
    ]}


@router.get("/changes")
def law_changes(
    flagged_only: bool = True,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    """Recent tracked legal changes (flagged by default), newest first."""
    q = db.query(LawRevision, LawDocument).join(LawDocument, LawDocument.id == LawRevision.document_id)
    q = q.filter(LawRevision.delta_bytes != 0)
    if flagged_only:
        q = q.filter(LawRevision.flagged.is_(True))
    rows = q.order_by(LawRevision.observed_at.desc(), LawRevision.id.desc()).limit(limit).all()
    return {"caveat": _CAVEAT, "changes": [
        {
            "document_id": doc.id, "jurisdiction": doc.jurisdiction, "title": doc.title,
            "official_url": doc.official_url or doc.url, "category": doc.category,
            "observed_at": rev.observed_at.isoformat() if rev.observed_at else None,
            "delta_bytes": rev.delta_bytes, "flagged": bool(rev.flagged),
            "flag_reasons": (rev.flag_reasons or "").split(",") if rev.flag_reasons else [],
            "diff": rev.diff or "",
        }
        for rev, doc in rows
    ]}


@router.post("/track")
def law_track(
    limit: int = Query(25, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    """Fetch all watched legal documents now (through the ethical fetcher)."""
    from src.ingest import EthicalFetcher
    from src.law.track import track_watched

    fetcher = EthicalFetcher(
        min_interval_s=float(os.getenv("OO_FETCH_MIN_INTERVAL", "1.0")),
        timeout=float(os.getenv("OO_FETCH_TIMEOUT", "30")),
    )
    return track_watched(db, fetcher, limit_documents=limit)


@router.post("/seed")
def law_seed(db: Session = Depends(get_db)) -> dict:
    """(Re)seed the worldwide legal catalog + register trackable documents (idempotent)."""
    from src.law.catalog import register_documents, seed_legal_sources

    sources = seed_legal_sources(db)
    documents = register_documents(db)
    return {"sources": sources, "documents": documents}


@router.get("/documents/{document_id}")
def law_document(document_id: int, db: Session = Depends(get_db)) -> dict:
    """One document with its change history (diffs)."""
    doc = db.query(LawDocument).filter_by(id=document_id).first()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    revs = (db.query(LawRevision).filter_by(document_id=doc.id)
            .order_by(LawRevision.observed_at.desc()).all())
    return {
        **_doc_dict(doc, revisions=len(revs)),
        "caveat": _CAVEAT,
        "revisions": [
            {"observed_at": r.observed_at.isoformat() if r.observed_at else None,
             "delta_bytes": r.delta_bytes, "flagged": bool(r.flagged),
             "flag_reasons": (r.flag_reasons or "").split(",") if r.flag_reasons else [],
             "diff": r.diff or ""}
            for r in revs
        ],
    }
