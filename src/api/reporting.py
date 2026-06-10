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
from src.reporting.methods import METHODS_SCHEMA, build_methods_markdown

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


class MethodsRequest(BaseModel):
    article_ids: list[int] | None = None
    query: str | None = None
    case_name: str | None = None
    notes: str | None = None
    include_bundle: bool = False


def _select_articles(req, db) -> list:
    """Shared selection: explicit ids, or a Boolean FTS query (same as evidence)."""
    if req.article_ids:
        return db.query(Article).filter(Article.id.in_(req.article_ids)).all()
    if req.query:
        try:
            ids = search_ids(db, req.query)
        except SearchQueryError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid query: {exc}") from exc
        return db.query(Article).filter(Article.id.in_(ids or [])).all()
    raise HTTPException(status_code=400, detail="Provide article_ids or query.")


@router.post("/methods")
def export_methods(req: MethodsRequest, db: Session = Depends(get_db)) -> dict:
    """Export a Markdown methods appendix for a selection (0.0.9 WP1 / RM-07).

    Records the *how* -- verbatim query, app version, counts, per-article
    provenance -- as a document. Computes nothing new, concludes nothing.
    With ``include_bundle`` the response also carries the signed evidence
    bundle for the same selection, so one response holds document + proof.
    """
    from sqlalchemy import func

    articles = _select_articles(req, db)
    if not articles:
        raise HTTPException(status_code=404, detail="No matching articles.")

    corpus_total = db.query(func.count(Article.id)).scalar() or 0
    row = db.query(func.min(Article.published_at), func.max(Article.published_at)).first()
    lo, hi = row if row is not None else (None, None)
    markdown = build_methods_markdown(
        articles,
        query=req.query,
        case_name=req.case_name,
        notes=req.notes,
        corpus_total=corpus_total,
        corpus_range=(
            lo.date().isoformat() if lo else None,
            hi.date().isoformat() if hi else None,
        ),
    )
    out: dict = {
        "schema": METHODS_SCHEMA,
        "case_name": req.case_name,
        "article_count": len(articles),
        "markdown": markdown,
    }
    if req.include_bundle:
        key = load_or_create_signing_key()
        out["bundle"] = build_signed_bundle(articles, key, case_name=req.case_name)
    return out
