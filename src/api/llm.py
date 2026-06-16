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

import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.database.fts import SearchQueryError, search_ids
from src.database.models import Article, ArticleAnalysis
from src.database.session import get_db
from src.llm.ollama import (
    CATALOG_AS_OF,
    DEFAULT_MODEL,
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

TRANSLATE_PROMPT_VERSION = "translate-v1"
_TRANSLATE_SYSTEM = (
    "You are a faithful translator for an investigative journalist. Translate the "
    "article into {target} as accurately and literally as the language allows. "
    "Preserve names, numbers, quotes and meaning exactly; do NOT summarize, "
    "interpret, soften, or add anything. Output only the translation."
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


class TranslateRequest(BaseModel):
    target_language: str = "English"
    model: str | None = None


@router.get("/health")
def llm_health(client: OllamaClient = Depends(get_llm_client)) -> dict:
    """Report whether Ollama is reachable and which models are installed."""
    try:
        installed = client.list_installed()
        return {"available": True, "base_url": client.base_url, "installed_models": installed}
    except LLMUnavailable as exc:
        return {
            "available": False,
            "base_url": client.base_url,
            "installed_models": [],
            "detail": str(exc),
        }


@router.get("/models")
def llm_models(client: OllamaClient = Depends(get_llm_client)) -> dict:
    """What the operator actually has (live, local) + a suggested catalog.

    The picker should lead with `installed` (truth from Ollama). `catalog` is a
    hardware-annotated suggestion list with an honest `catalog_as_of` date --
    it goes stale fast; newer models may exist at https://ollama.com/library.
    """
    from src.llm.ollama import annotate_catalog, total_ram_gb

    try:
        installed = client.list_installed_detailed()
        available = True
    except LLMUnavailable:
        installed, available = [], False
    return {
        "available": available,
        "default": DEFAULT_MODEL,
        "total_ram_gb": total_ram_gb(),
        "catalog_as_of": CATALOG_AS_OF,
        "catalog": annotate_catalog(),
        "installed": installed,
    }


@router.post("/generate")
def llm_generate(req: GenerateRequest, client: OllamaClient = Depends(get_llm_client)) -> dict:
    """Single-shot generation. 503 if Ollama/model unavailable."""
    model = req.model or DEFAULT_MODEL
    try:
        result = client.generate(req.prompt, model=model, system=req.system)
    except LLMUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"model": result.model, "text": result.text}


# Ollama model tags: registry/name:tag with the usual punctuation. Validated so a
# user-supplied name can never inject into the Ollama request path.
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class ModelRequest(BaseModel):
    model: str


@router.post("/pull")
def llm_pull(req: ModelRequest, client: OllamaClient = Depends(get_llm_client)):
    """Pull (download + install) a model via the LOCAL Ollama process — STREAMS
    Ollama's real progress as NDJSON (invariant #20: never a fabricated bar).

    TRANSPORT HONESTY (maintainer Q9): the bytes egress via the Ollama process over
    CLEARNET, not the app's Tor proxy — the UI discloses this at consent. Airplane
    mode (kill switch) refuses the pull at the client. Gated by the ONE consent (#14)."""
    import json as _json

    if not _MODEL_RE.match(req.model or ""):
        raise HTTPException(status_code=400, detail="invalid model name")

    def _stream():
        try:
            for prog in client.pull(req.model):
                yield _json.dumps(prog, separators=(",", ":")) + "\n"
        except (LLMUnavailable, LLMError) as exc:
            yield _json.dumps({"error": str(exc)[:300]}, separators=(",", ":")) + "\n"

    return StreamingResponse(_stream(), media_type="application/x-ndjson")


@router.post("/remove")
def llm_remove(req: ModelRequest, client: OllamaClient = Depends(get_llm_client)) -> dict:
    """Remove an installed model via the LOCAL Ollama process."""
    if not _MODEL_RE.match(req.model or ""):
        raise HTTPException(status_code=400, detail="invalid model name")
    try:
        client.remove(req.model)
    except LLMUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)[:200]) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:200]) from exc
    return {"removed": req.model, "ok": True}


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
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    analysis = ArticleAnalysis(
        article_id=article.id,
        kind="summary",
        result=result.text,
        model=result.model,
        prompt_version=SUMMARY_PROMPT_VERSION,
        created_at=datetime.now(UTC),
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


@router.post("/articles/{article_id}/translate")
def translate_article(
    article_id: int,
    req: TranslateRequest,
    db: Session = Depends(get_db),
    client: OllamaClient = Depends(get_llm_client),
) -> dict:
    """Translate a stored article into a target language with a local model.

    A faithful translation (not a summary) is persisted with provenance so foreign
    sources become part of the searchable corpus -- widening world awareness without
    any text leaving the machine.
    """
    article = db.query(Article).filter_by(id=article_id).first()
    if article is None:
        raise HTTPException(status_code=404, detail=f"Article {article_id} not found.")
    if not article.content:
        raise HTTPException(status_code=400, detail="Article has no content to translate.")

    model = req.model or DEFAULT_MODEL
    system = _TRANSLATE_SYSTEM.format(target=req.target_language)
    prompt = f"Title: {article.title or '(untitled)'}\n\n{article.content[:_MAX_CHARS]}"
    try:
        result = client.generate(prompt, model=model, system=system)
    except LLMUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    analysis = ArticleAnalysis(
        article_id=article.id,
        kind="translation",
        result=result.text,
        model=result.model,
        prompt_version=f"{TRANSLATE_PROMPT_VERSION}:{req.target_language}",
        created_at=datetime.now(UTC),
    )
    db.add(analysis)
    db.commit()
    return {
        "analysis_id": analysis.id,
        "article_id": article.id,
        "kind": "translation",
        "source_language": article.language,
        "target_language": req.target_language,
        "model": result.model,
        "prompt_version": analysis.prompt_version,
        "result": result.text,
        "created_at": analysis.created_at.isoformat(),
    }


# --------------------------------------------------------------------------- #
#  Corpus-wide synthesis (0.0.8 part 2, WP4 / RM-12)
# --------------------------------------------------------------------------- #

SYNTHESIS_PROMPT_VERSION = "synthesis-v1"
_SYNTHESIS_SYSTEM = (
    "You are a careful research assistant for an investigative journalist. You will "
    "receive excerpts from SEVERAL stored articles, each numbered. Write a factual, "
    "neutral synthesis of what they collectively report: shared facts, points of "
    "disagreement between articles, and open questions. Refer to articles by their "
    "number, e.g. [3]. Do NOT add information that is not in the excerpts, do NOT "
    "resolve disagreements yourself, and do NOT speculate."
)
_SYNTHESIS_MAX_ARTICLES = 20
# Total prompt budget across all excerpts (keeps a small CPU model's context safe).
_SYNTHESIS_BUDGET_CHARS = 24_000


class SynthesizeRequest(BaseModel):
    article_ids: list[int] | None = None
    query: str | None = None
    model: str | None = None


@router.post("/synthesize")
def synthesize_articles(
    req: SynthesizeRequest,
    db: Session = Depends(get_db),
    client: OllamaClient = Depends(get_llm_client),
) -> dict:
    """Synthesize a bounded SET of stored articles with a local model.

    Bounded fan-out by construction: at most {max} articles, one generation call,
    a per-article excerpt budget. The response carries the member ids so the
    output is always traceable to its inputs; the synthesis is stored per member
    article (kind="synthesis") with model + prompt-version provenance. The
    output is assistance, never a verdict -- it cites article numbers, and the
    caveat travels in the response.
    """
    if req.article_ids and len(req.article_ids) > _SYNTHESIS_MAX_ARTICLES:
        raise HTTPException(
            status_code=400,
            detail=f"At most {_SYNTHESIS_MAX_ARTICLES} articles per synthesis "
            f"(got {len(req.article_ids)}). Narrow the selection.",
        )

    truncated = False
    if req.article_ids:
        articles = db.query(Article).filter(Article.id.in_(req.article_ids)).all()
    elif req.query:
        try:
            ids = search_ids(db, req.query) or []
        except SearchQueryError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid query: {exc}") from exc
        if len(ids) > _SYNTHESIS_MAX_ARTICLES:
            ids, truncated = ids[:_SYNTHESIS_MAX_ARTICLES], True
        articles = db.query(Article).filter(Article.id.in_(ids)).all()
    else:
        raise HTTPException(status_code=400, detail="Provide article_ids or query.")

    articles = [a for a in articles if a.content]
    if not articles:
        raise HTTPException(status_code=404, detail="No matching articles with content.")

    per_article = max(400, _SYNTHESIS_BUDGET_CHARS // len(articles))
    parts = []
    for i, a in enumerate(sorted(articles, key=lambda x: x.id), 1):
        src = a.source.name if a.source else "unknown source"
        pub = a.published_at.date().isoformat() if a.published_at else "undated"
        parts.append(
            f"[{i}] {a.title or '(untitled)'} ({src}, {pub})\n{a.content[:per_article]}"
        )
    prompt = "\n\n---\n\n".join(parts)
    model = req.model or DEFAULT_MODEL

    try:
        result = client.generate(prompt, model=model, system=_SYNTHESIS_SYSTEM)
    except LLMUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    member_ids = [a.id for a in sorted(articles, key=lambda x: x.id)]
    for a in articles:
        db.add(
            ArticleAnalysis(
                article_id=a.id,
                kind="synthesis",
                result=result.text,
                model=result.model,
                prompt_version=SYNTHESIS_PROMPT_VERSION,
                created_at=datetime.now(UTC),
            )
        )
    db.commit()

    return {
        "kind": "synthesis",
        "model": result.model,
        "prompt_version": SYNTHESIS_PROMPT_VERSION,
        "member_ids": member_ids,
        "member_count": len(member_ids),
        "truncated": truncated,
        "result": result.text,
        "caveat": (
            "A synthesis is reading assistance over the listed member articles only -- "
            "it asserts nothing beyond them and may miss nuance; verify against the "
            "stored copies before publication."
        ),
    }
