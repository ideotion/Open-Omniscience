"""
Reporting API: export signed, tamper-evident evidence bundles.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.database.fts import SearchQueryError, search_ids
from src.database.models import Article
from src.database.session import get_db
from src.reporting.evidence import build_signed_bundle, load_or_create_signing_key, verify_bundle

router = APIRouter(prefix="/api/reports", tags=["reporting"])


class EvidenceRequest(BaseModel):
    article_ids: list[int] | None = None
    query: str | None = None
    case_name: str | None = None


@router.post("/evidence")
def export_evidence(req: EvidenceRequest, db: Session = Depends(get_db)) -> dict:
    """Export a signed evidence bundle for selected articles.

    Selection is by explicit ``article_ids`` or by a Boolean ``query``. The
    returned bundle is independently verifiable (offline) with scripts/verify_evidence.py.
    """
    if req.article_ids:
        articles = db.query(Article).filter(Article.id.in_(req.article_ids)).all()
    elif req.query:
        try:
            ids = search_ids(db, req.query)
        except SearchQueryError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid query: {exc}") from exc
        articles = db.query(Article).filter(Article.id.in_(ids or [])).all()
    else:
        raise HTTPException(status_code=400, detail="Provide article_ids or query.")

    if not articles:
        raise HTTPException(status_code=404, detail="No matching articles to export.")

    key = load_or_create_signing_key()
    return build_signed_bundle(articles, key, case_name=req.case_name)


class VerifyRequest(BaseModel):
    bundle: dict
    trusted_public_key: str | None = None


@router.post("/evidence/verify")
def verify_evidence(req: VerifyRequest) -> dict:
    """Verify a previously-exported bundle (convenience; verification needs no DB).

    Pass ``trusted_public_key`` (the signer's known key) to prove provenance, not
    just integrity -- otherwise a valid signature only proves "signed by some key".
    """
    ok, reason = verify_bundle(req.bundle, trusted_public_key=req.trusted_public_key)
    return {"verified": ok, "reason": reason}
