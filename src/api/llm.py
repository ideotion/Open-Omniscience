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


def active_model() -> str:
    """The operator's chosen default model — the STORED UI setting (maintainer Q10)
    if set, else ``DEFAULT_MODEL`` (env ``OO_LLM_MODEL`` / built-in). A per-request
    ``model`` still overrides it. Never fatal: any settings error falls back."""
    try:
        from src.config.app_settings import load_settings

        return load_settings().llm_model or DEFAULT_MODEL
    except Exception:  # noqa: BLE001 - a settings hiccup must not break inference
        return DEFAULT_MODEL


def _llm_settings():
    """The stored app settings, or None if unreadable (never fatal)."""
    try:
        from src.config.app_settings import load_settings

        return load_settings()
    except Exception:  # noqa: BLE001 - settings must never break inference
        return None


def _effective_keep_alive() -> str | None:
    """How long Ollama keeps the model loaded after a call (stored UI setting)."""
    s = _llm_settings()
    return s.llm_keep_alive if s else None


def _apply_target(template: str, target: str) -> str:
    """Insert the target language into a translate prompt. The built-in default uses a
    ``{target}`` placeholder; a custom prompt without one gets an explicit instruction
    appended (so the target is always conveyed, whatever the operator wrote)."""
    if "{target}" in template:
        return template.replace("{target}", target)
    return f"{template}\n\nTranslate into {target}."


def _build_prompting(op: str, *, target: str | None = None) -> tuple[str, str, str]:
    """Resolve ``(system_prompt, prompt_version, prompt_text)`` for an op.

    Prompts are operator-editable (Settings → Models). A non-empty stored override is
    used verbatim, else the built-in default; the version flags default-vs-custom, and
    ``prompt_text`` is the EXACT system text used (recorded per result so provenance
    stays honest even after the operator edits a prompt). Evaluated at call time, so
    the synthesis constants defined later in this module are available.
    """
    s = _llm_settings()
    overrides = {
        "summary": (s.llm_prompt_summary if s else ""),
        "translate": (s.llm_prompt_translate if s else ""),
        "synthesis": (s.llm_prompt_synthesis if s else ""),
    }
    defaults = {
        "summary": _SUMMARY_SYSTEM,
        "translate": _TRANSLATE_SYSTEM,
        "synthesis": _SYNTHESIS_SYSTEM,
    }
    override = (overrides.get(op) or "").strip()
    is_custom = bool(override)
    template = override or defaults[op]
    if op == "translate":
        tgt = (target or "English")
        system = _apply_target(template, tgt)
        base = "translate-custom" if is_custom else TRANSLATE_PROMPT_VERSION
        version = f"{base}:{tgt}"
    elif op == "synthesis":
        system = template
        version = "synthesis-custom" if is_custom else SYNTHESIS_PROMPT_VERSION
    else:  # summary
        system = template
        version = "summary-custom" if is_custom else SUMMARY_PROMPT_VERSION
    return system, version, system


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
        "active": active_model(),  # the stored UI choice (Q10), or the default
        "total_ram_gb": total_ram_gb(),
        "catalog_as_of": CATALOG_AS_OF,
        "catalog": annotate_catalog(),
        "installed": installed,
    }


@router.get("/prompts")
def llm_prompts() -> dict:
    """The local-LLM behaviour the operator can tune (maintainer 2026-06-17): the
    keep-alive duration and the three editable SYSTEM PROMPTS, each with its built-in
    default and the current override ("" = using the default). Read by Settings → Models.

    There are three system prompts in total — ``summary`` (used for one OR many
    articles), ``translate`` (one OR many; ``{target}`` is the target language), and
    ``synthesis`` (one combined output across several). Bulk reuses the single-article
    summary/translate prompt per article — there is no separate "several" prompt.
    """
    from src.config.app_settings import AppSettings

    s = _llm_settings()
    return {
        "keep_alive": (s.llm_keep_alive if s else AppSettings().llm_keep_alive),
        "keep_alive_default": AppSettings().llm_keep_alive,
        "prompts": {
            "summary": {
                "default": _SUMMARY_SYSTEM,
                "current": (s.llm_prompt_summary if s else "") or "",
                "version": SUMMARY_PROMPT_VERSION,
            },
            "translate": {
                "default": _TRANSLATE_SYSTEM,
                "current": (s.llm_prompt_translate if s else "") or "",
                "version": TRANSLATE_PROMPT_VERSION,
            },
            "synthesis": {
                "default": _SYNTHESIS_SYSTEM,
                "current": (s.llm_prompt_synthesis if s else "") or "",
                "version": SYNTHESIS_PROMPT_VERSION,
            },
        },
        "note": (
            "Empty = use the built-in default. The exact prompt used is recorded with "
            "each result (provenance). The translate prompt may contain {target} for the "
            "target language. Save changes via Settings (PUT /api/settings)."
        ),
    }


@router.post("/generate")
def llm_generate(req: GenerateRequest, client: OllamaClient = Depends(get_llm_client)) -> dict:
    """Single-shot generation. 503 if Ollama/model unavailable."""
    model = req.model or active_model()
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

    model = req.model or active_model()
    system, prompt_version, prompt_text = _build_prompting("summary")
    prompt = f"Article title: {article.title or '(untitled)'}\n\n{article.content[:_MAX_CHARS]}"
    try:
        result = client.generate(
            prompt, model=model, system=system, keep_alive=_effective_keep_alive()
        )
    except LLMUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    analysis = ArticleAnalysis(
        article_id=article.id,
        kind="summary",
        result=result.text,
        model=result.model,
        prompt_version=prompt_version,
        prompt_text=prompt_text,
        created_at=datetime.now(UTC),
    )
    db.add(analysis)
    db.commit()
    return {
        "analysis_id": analysis.id,
        "article_id": article.id,
        "kind": "summary",
        "model": result.model,
        "prompt_version": prompt_version,
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

    model = req.model or active_model()
    system, prompt_version, prompt_text = _build_prompting("translate", target=req.target_language)
    prompt = f"Title: {article.title or '(untitled)'}\n\n{article.content[:_MAX_CHARS]}"
    try:
        result = client.generate(
            prompt, model=model, system=system, keep_alive=_effective_keep_alive()
        )
    except LLMUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    analysis = ArticleAnalysis(
        article_id=article.id,
        kind="translation",
        result=result.text,
        model=result.model,
        prompt_version=prompt_version,
        prompt_text=prompt_text,
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


def _parse_target_language(prompt_version: str | None) -> str | None:
    """The translation target language is stored INSIDE the prompt version as
    ``translate-v1:French`` (or ``translate-custom:French``) — provenance with no extra
    column. Recover it for display, covering both the default and custom prompt cases."""
    if prompt_version and prompt_version.startswith("translate-") and ":" in prompt_version:
        return prompt_version.split(":", 1)[1] or None
    return None


@router.get("/articles/{article_id}/analyses")
def list_article_analyses(
    article_id: int,
    kind: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """List the stored LLM analyses (summaries / translations / …) for an article.

    Newest first. EVERY past result is kept — a new summary/translation never
    replaces an old one (maintainer-ruled), so the reader shows the latest and folds
    the rest. Each row carries its full provenance (model, prompt version, date) so
    no generated text is ever shown without its origin.

    Read-only by construction: these rows live in ``article_analyses``, NOT in
    ``articles``, and the keyword indexer only ever reads ``articles.content`` — so a
    summary or translation is NEVER keyword-indexed or fed into the analytics (the
    maintainer-agreed contract). This endpoint only reads them back.
    """
    article = db.query(Article).filter_by(id=article_id).first()
    if article is None:
        raise HTTPException(status_code=404, detail=f"Article {article_id} not found.")
    qy = db.query(ArticleAnalysis).filter(ArticleAnalysis.article_id == article_id)
    if kind:
        qy = qy.filter(ArticleAnalysis.kind == kind)
    rows = qy.order_by(ArticleAnalysis.created_at.desc(), ArticleAnalysis.id.desc()).all()
    return {
        "article_id": article_id,
        "source_language": article.language,
        "count": len(rows),
        "analyses": [
            {
                "id": r.id,
                "kind": r.kind,
                "result": r.result,
                "model": r.model,
                "prompt_version": r.prompt_version,
                "prompt_text": r.prompt_text,
                "target_language": _parse_target_language(r.prompt_version),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
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
    model = req.model or active_model()
    system, prompt_version, prompt_text = _build_prompting("synthesis")

    try:
        result = client.generate(
            prompt, model=model, system=system, keep_alive=_effective_keep_alive()
        )
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
                prompt_version=prompt_version,
                prompt_text=prompt_text,
                created_at=datetime.now(UTC),
            )
        )
    db.commit()

    return {
        "kind": "synthesis",
        "model": result.model,
        "prompt_version": prompt_version,
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


# --------------------------------------------------------------------------- #
#  Bulk summarize / translate over a matched article set (streaming progress)
# --------------------------------------------------------------------------- #
#
# Unlike /synthesize (ONE combined output), bulk runs the local model over EACH
# article independently and stores a per-article result. A local CPU model over many
# articles is slow by nature, so we:
#   * cap the set (no unbounded fan-out),
#   * stream HONEST per-article progress as NDJSON (invariant #20 — never a fabricated
#     bar/ETA; only what actually completed),
#   * rely on the client's per-call kill-switch check (airplane mode aborts loudly),
#   * store each result as its OWN ArticleAnalysis row — kept forever, NEVER replacing
#     a prior one (the latest is shown first; older ones fold away in the reader).
# These rows are NOT keyword-indexed (they live in article_analyses, never in
# articles.content), so bulk output never pollutes the keyword analytics.
_BULK_MAX_ARTICLES = 500


class BulkLLMRequest(BaseModel):
    op: str  # "summarize" | "translate"
    article_ids: list[int] | None = None
    query: str | None = None
    source: str | None = None
    language: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    target_language: str = "English"
    model: str | None = None
    skip_existing: bool = True
    limit: int = 200


@router.post("/bulk")
def bulk_llm(
    req: BulkLLMRequest,
    db: Session = Depends(get_db),
    client: OllamaClient = Depends(get_llm_client),
):
    """Summarize OR translate every article in a matched set with the local model.

    Selection mirrors the analysis window: an explicit ``article_ids`` set wins,
    otherwise the search filters (query/source/language/dates) resolve the set. The
    response streams NDJSON: one ``start`` object, one ``item`` per article
    (status = stored | skipped | failed), and a final ``done`` (or an aborted ``done``
    if the local model becomes unavailable mid-run — it won't recover, so we stop).
    """
    op = (req.op or "").strip().lower()
    if op not in {"summarize", "translate"}:
        raise HTTPException(status_code=400, detail="op must be 'summarize' or 'translate'.")
    cap = max(1, min(req.limit or 200, _BULK_MAX_ARTICLES))

    # Resolve the article set (the analysis window's own selection logic).
    if req.article_ids:
        seen: set[int] = set()
        ordered: list[int] = []
        for v in req.article_ids:
            if isinstance(v, int) and v not in seen:
                seen.add(v)
                ordered.append(v)
        requested = len(ordered)
        ids = ordered[:cap]
        by_id = {a.id: a for a in db.query(Article).filter(Article.id.in_(ids)).all()}
        articles = [by_id[i] for i in ids if i in by_id]
    elif any([req.query, req.source, req.language, req.start_date, req.end_date]):
        from src.api.main import _query_articles

        arts, total = _query_articles(
            db, query=req.query, source=req.source, start_date=req.start_date,
            end_date=req.end_date, language=req.language, tags=None, limit=cap, offset=0,
        )
        articles = list(arts)
        requested = total
    else:
        raise HTTPException(status_code=400, detail="Provide article_ids or a query/filter.")

    # Snapshot the plain fields the stream needs, so it never depends on the request's
    # ORM session staying open while the (slow) model runs.
    work = [
        (a.id, a.title or "(untitled)", a.content or "")
        for a in articles
        if a.content
    ]
    if not work:
        raise HTTPException(status_code=404, detail="No matching articles with content.")

    model = req.model or active_model()
    target = (req.target_language or "English").strip() or "English"
    keep_alive = _effective_keep_alive()
    if op == "summarize":
        kind = "summary"
        system, prompt_version, prompt_text = _build_prompting("summary")
    else:
        kind = "translation"
        system, prompt_version, prompt_text = _build_prompting("translate", target=target)

    # skip_existing tops up only what's missing: which of these already have THIS exact
    # result (same kind, and for a translation the same target language)? We never
    # delete or replace — we just avoid recomputing what is already stored.
    already: set[int] = set()
    if req.skip_existing:
        ex = db.query(ArticleAnalysis.article_id).filter(
            ArticleAnalysis.article_id.in_([w[0] for w in work]),
            ArticleAnalysis.kind == kind,
        )
        if op == "translate":
            ex = ex.filter(ArticleAnalysis.prompt_version == prompt_version)
        already = {r[0] for r in ex.all()}

    total = len(work)
    capped = requested > total

    def _stream():
        import json as _json

        def emit(obj: dict) -> str:
            return _json.dumps(obj, separators=(",", ":")) + "\n"

        yield emit({
            "event": "start", "op": op, "total": total, "requested": requested,
            "capped": capped, "model": model,
            "target_language": target if op == "translate" else None,
        })
        stored = skipped = failed = 0
        from src.database.session import SessionLocal

        with SessionLocal() as s:
            for i, (aid, title, content) in enumerate(work, 1):
                if req.skip_existing and aid in already:
                    skipped += 1
                    yield emit({"event": "item", "i": i, "total": total,
                                "article_id": aid, "title": title, "status": "skipped"})
                    continue
                if op == "summarize":
                    prompt = f"Article title: {title}\n\n{content[:_MAX_CHARS]}"
                else:
                    prompt = f"Title: {title}\n\n{content[:_MAX_CHARS]}"
                try:
                    result = client.generate(
                        prompt, model=model, system=system, keep_alive=keep_alive
                    )
                except LLMUnavailable as exc:
                    # Ollama down / model missing / airplane mode — won't recover mid-run.
                    yield emit({"event": "done", "total": total, "stored": stored,
                                "skipped": skipped, "failed": failed,
                                "aborted": True, "reason": str(exc)[:200]})
                    return
                except LLMError as exc:
                    failed += 1
                    yield emit({"event": "item", "i": i, "total": total,
                                "article_id": aid, "title": title, "status": "failed",
                                "error": str(exc)[:200]})
                    continue
                s.add(ArticleAnalysis(
                    article_id=aid, kind=kind, result=result.text, model=result.model,
                    prompt_version=prompt_version, prompt_text=prompt_text,
                    created_at=datetime.now(UTC),
                ))
                s.commit()
                stored += 1
                yield emit({"event": "item", "i": i, "total": total,
                            "article_id": aid, "title": title, "status": "stored",
                            "chars": len(result.text)})
        yield emit({"event": "done", "total": total, "stored": stored,
                    "skipped": skipped, "failed": failed, "aborted": False})

    return StreamingResponse(_stream(), media_type="application/x-ndjson")
