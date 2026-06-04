"""
Local LLM API (Ollama, HTTP only).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Endpoints are synchronous (`def`) so blocking httpx calls run in the threadpool.
If Ollama is unreachable or the model isn't installed, these return HTTP 503 with
a clear message -- never a fabricated result. LLM outputs are persisted with
provenance (model + prompt version + timestamp) as ArticleAnalysis rows.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.database.models import Article, ArticleAnalysis
from src.database.session import get_db
from src.llm.ollama import (
    DEFAULT_MODEL,
    MODEL_CATALOG,
    LLMError,
    LLMUnavailable,
    OllamaClient,
)

router = APIRouter(prefix="/api/llm", tags=["llm"])

# Prompt versions are part of provenance: bump when a prompt changes.
SUMMARY_PROMPT_VERSION = "summary-v1"
_SUMMARY_SYSTEM = (
    "You are a careful research assistant for an investigative journalist. "
    "Summarize the article factually and neutrally in 3-5 sentences. Do not add "
    "information that is not in the text. If the text is not a coherent article, say so."
)
# Keep prompts within a small CPU model's context.
_MAX_CHARS = 6000

_client: OllamaClient | None = None


def get_llm_client() -> OllamaClient:
    """Dependency returning a shared OllamaClient (overridable in tests)."""
    global _client
    if _client is None:
        _client = OllamaClient()
    return _client


class GenerateRequest(BaseModel):
    prompt: str
    model: str | None = None
    system: str | None = None


class SummarizeRequest(BaseModel):
    model: str | None = None


@router.get("/health")
def llm_health(client: OllamaClient = Depends(get_llm_client)) -> dict:
    """Report whether Ollama is reachable and which models are installed."""
    try:
        installed = client.list_installed()
        return {"available": True, "base_url": client.base_url, "installed_models": installed}
    except LLMUnavailable as exc:
        return {"available": False, "base_url": client.base_url, "installed_models": [], "detail": str(exc)}


@router.get("/models")
def llm_models(client: OllamaClient = Depends(get_llm_client)) -> dict:
    """Recommended (real) model catalog plus what is actually installed."""
    try:
        installed = client.list_installed()
        available = True
    except LLMUnavailable:
        installed, available = [], False
    return {"available": available, "default": DEFAULT_MODEL,
            "catalog": MODEL_CATALOG, "installed": installed}


@router.post("/generate")
def llm_generate(req: GenerateRequest, client: OllamaClient = Depends(get_llm_client)) -> dict:
    """Single-shot generation. 503 if Ollama/model unavailable."""
    model = req.model or DEFAULT_MODEL
    try:
        result = client.generate(req.prompt, model=model, system=req.system)
    except LLMUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"model": result.model, "text": result.text}


@router.post("/articles/{article_id}/summarize")
def summarize_article(
    article_id: int,
    req: SummarizeRequest,
    db: Session = Depends(get_db),
    client: OllamaClient = Depends(get_llm_client),
) -> dict:
    """Summarize a stored article with a local model and persist it with provenance."""
    article = db.query(Article).filter_by(id=article_id).first()
    if article is None:
        raise HTTPException(status_code=404, detail=f"Article {article_id} not found.")
    if not article.content:
        raise HTTPException(status_code=400, detail="Article has no content to summarize.")

    model = req.model or DEFAULT_MODEL
    prompt = f"Article title: {article.title or '(untitled)'}\n\n{article.content[:_MAX_CHARS]}"
    try:
        result = client.generate(prompt, model=model, system=_SUMMARY_SYSTEM)
    except LLMUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    analysis = ArticleAnalysis(
        article_id=article.id,
        kind="summary",
        result=result.text,
        model=result.model,
        prompt_version=SUMMARY_PROMPT_VERSION,
        created_at=datetime.now(timezone.utc),
    )
    db.add(analysis)
    db.commit()
    return {
        "analysis_id": analysis.id,
        "article_id": article.id,
        "kind": "summary",
        "model": result.model,
        "prompt_version": SUMMARY_PROMPT_VERSION,
        "result": result.text,
        "created_at": analysis.created_at.isoformat(),
    }
