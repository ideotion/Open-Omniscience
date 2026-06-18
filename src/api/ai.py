"""
AI-layer API: LLM keyword extraction into the SEPARATE AI store + a read-only lens.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

These endpoints READ articles from the main corpus (allowed) and WRITE only to the
AI store (src.ai_layer) — never the trusted keyword index in the main DB (the
maintainer-ruled strict separation). The AI keywords are a parallel, labelled,
disposable lens: no score, full model provenance, unconfirmed until a user curates.

Ollama is loopback (no network egress for generation), so — like the existing
summarize/translate/bulk endpoints — extraction is not behind the network-consent
popup; airplane mode (the kill switch) still refuses it at the client, surfaced as an
aborted run.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.ai_layer import store as ai_store
from src.ai_layer.db import ai_db_path, ai_session_scope, init_ai_db
from src.ai_layer.jobs import ArticleWork, extract_for_articles
from src.api.llm import active_model, get_llm_client
from src.database.models import Article
from src.database.session import get_db
from src.llm.ollama import OllamaClient

router = APIRouter(prefix="/api/ai", tags=["ai"])

# Bound the fan-out: a local CPU model over a large set is slow, and this is a
# convenience batch, not an unbounded crawl.
_AI_EXTRACT_MAX = 500

_LENS_NOTE = (
    "AI-derived keywords — a separate, model-generated lens, NOT the trusted keyword "
    "index. Unconfirmed until you confirm them; nothing here feeds the main analytics."
)


class AiExtractRequest(BaseModel):
    article_ids: list[int] | None = None
    query: str | None = None
    source: str | None = None
    language: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    kind: str = "keyword"
    max_terms: int = 20
    model: str | None = None
    skip_existing: bool = True
    limit: int = 200


@router.post("/keywords/extract")
def extract_keywords(
    req: AiExtractRequest,
    db: Session = Depends(get_db),
    client: OllamaClient = Depends(get_llm_client),
):
    """Extract salient keywords/entities for a matched article set with the local
    model, storing them in the AI store. Selection mirrors the analysis window: an
    explicit ``article_ids`` set wins, else the search filters resolve the set.
    Streams NDJSON honest progress (invariant #20)."""
    cap = max(1, min(req.limit or 200, _AI_EXTRACT_MAX))

    if req.article_ids:
        seen: set[int] = set()
        ids: list[int] = []
        for v in req.article_ids:
            if isinstance(v, int) and v not in seen:
                seen.add(v)
                ids.append(v)
        ids = ids[:cap]
        by_id = {a.id: a for a in db.query(Article).filter(Article.id.in_(ids)).all()}
        articles = [by_id[i] for i in ids if i in by_id]
    elif any([req.query, req.source, req.language, req.start_date, req.end_date]):
        from src.api.main import _query_articles

        arts, _total = _query_articles(
            db, query=req.query, source=req.source, start_date=req.start_date,
            end_date=req.end_date, language=req.language, tags=None, limit=cap, offset=0,
        )
        articles = list(arts)
    else:
        raise HTTPException(status_code=400, detail="Provide article_ids or a query/filter.")

    work = [
        ArticleWork(a.id, a.title or "(untitled)", a.content or "", a.language)
        for a in articles
        if a.content
    ]
    if not work:
        raise HTTPException(status_code=404, detail="No matching articles with content.")

    model = req.model or active_model()
    max_terms = max(1, min(req.max_terms or 20, 100))
    init_ai_db()  # ensure the AI store exists (we are about to write to it)

    # Visible in the task manager while it runs ("are keywords being extracted?").
    from src.monitoring import tasks as _bgtasks

    _tok = _bgtasks.register(
        "analytics", f"Extracting AI keywords · {len(work)} article(s)",
        detail=f"model {model}", total=len(work),
    )

    def _stream():
        try:
            done = 0
            for event in extract_for_articles(
                work, client, model=model, kind=req.kind, max_terms=max_terms,
                skip_existing=req.skip_existing,
            ):
                if isinstance(event, dict) and event.get("event") == "item":
                    done += 1
                    _bgtasks.update(_tok, done=done)
                yield json.dumps(event, separators=(",", ":")) + "\n"
        finally:
            _bgtasks.finish(_tok)

    return StreamingResponse(_stream(), media_type="application/x-ndjson")


@router.get("/articles/{article_id}/keywords")
def article_ai_keywords(
    article_id: int, kind: str | None = None, confirmed_only: bool = False
) -> dict:
    """The AI-derived keywords stored for one article (the read-only lens).

    Side-effect-free: if no AI feature has ever run (the store file does not exist),
    return an empty lens WITHOUT creating the file."""
    if not ai_db_path().exists():
        return {"article_id": article_id, "count": 0, "keywords": [], "note": _LENS_NOTE}
    with ai_session_scope() as s:
        rows = ai_store.keywords_for_article(
            s, article_id, kind=kind, confirmed_only=confirmed_only
        )
        keywords = [
            {
                "id": r.id,
                "term": r.term,
                "kind": r.kind,
                "language": r.language,
                "model": r.model,
                "prompt_version": r.prompt_version,
                "confirmed": r.confirmed,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    return {
        "article_id": article_id,
        "count": len(keywords),
        "keywords": keywords,
        "note": _LENS_NOTE,
    }


class AiConfirmRequest(BaseModel):
    id: int
    confirmed: bool = True


@router.post("/keywords/confirm")
def confirm_ai_keyword(req: AiConfirmRequest) -> dict:
    """Curate the AI lens IN PLACE: confirm/unconfirm one AI keyword. The row stays in
    the AI store either way — a confirmed item never crosses into the trusted index."""
    if not ai_db_path().exists():
        raise HTTPException(status_code=404, detail="No AI keywords yet.")
    with ai_session_scope() as s:
        ok = ai_store.set_confirmed(s, req.id, req.confirmed)
    if not ok:
        raise HTTPException(status_code=404, detail=f"AI keyword {req.id} not found.")
    return {"id": req.id, "confirmed": req.confirmed, "ok": True}
