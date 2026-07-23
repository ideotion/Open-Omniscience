"""
AI-layer API: LLM keyword extraction into the SEPARATE AI store + a read-only lens.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

These endpoints READ articles from the main corpus and WRITE only to the AI-derived
``ai_keyword`` table in the MAIN DB (maintainer ruling 2026-06-18) — NEVER the trusted
``keyword_mentions`` index, which reads only ``articles.content``. The AI keywords are a
parallel, labelled, disposable lens: no score, full model provenance, unconfirmed until
a user curates.

Ollama is loopback (no network egress for generation), so — like the existing
summarize/translate/bulk endpoints — extraction is not behind the network-consent
popup; airplane mode (the kill switch) still refuses it at the client, surfaced as an
aborted run.
"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.ai_layer import store as ai_store
from src.ai_layer.jobs import ArticleWork, extract_for_articles
from src.api.llm import active_model, get_llm_client
from src.database.models import AiCustomPrompt, Article
from src.database.session import get_db
from src.llm.ollama import OllamaClient

router = APIRouter(prefix="/api/ai", tags=["ai"])

# UNCAPPED (maintainer 2026-06-20): the extractor runs over the WHOLE matched set. The run
# is a visible, abortable task-manager job, so the (slow) fan-out is the user's choice; an
# explicit positive `limit` is an optional bound, the default (<=0) means no cap.

_LENS_NOTE = (
    "AI-derived keywords — a separate, model-generated lens, NOT the trusted keyword "
    "index. Unconfirmed until you confirm them; nothing here feeds the main analytics."
)

# A custom-prompt's output_kind = the metadata TYPE; keep it a short, lowercase token so
# it reads cleanly as an AiKeyword.kind and carries no surprises.
_KIND_RE = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_PROMPT_MAX = 4000


def _resolve_work(
    db: Session,
    *,
    article_ids: list[int] | None,
    query: str | None,
    source: str | None,
    language: str | None,
    start_date: str | None,
    end_date: str | None,
    cap: int | None,
) -> list[ArticleWork]:
    """Shared article selection (mirrors the analysis window): an explicit ``article_ids``
    set wins, else the search filters resolve the set. Returns ArticleWork snapshots for
    articles WITH content; raises 400/404 like the endpoints expect."""
    if article_ids:
        seen: set[int] = set()
        ids: list[int] = []
        for v in article_ids:
            if isinstance(v, int) and v not in seen:
                seen.add(v)
                ids.append(v)
        if cap is not None:
            ids = ids[:cap]
        by_id = {a.id: a for a in db.query(Article).filter(Article.id.in_(ids)).all()}
        articles = [by_id[i] for i in ids if i in by_id]
    elif any([query, source, language, start_date, end_date]):
        from src.api.main import _query_articles

        arts, _total = _query_articles(
            db, query=query, source=source, start_date=start_date,
            end_date=end_date, language=language, tags=None, limit=cap, offset=0,
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
    return work


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
    limit: int = 0  # 0 = no cap (process the whole matched set)


@router.post("/keywords/extract")
def extract_keywords(
    req: AiExtractRequest,
    db: Session = Depends(get_db),
    client: OllamaClient = Depends(get_llm_client),
):
    """Extract salient keywords/entities for a matched article set with the local
    model, storing them in the ``ai_keyword`` table. Selection mirrors the analysis
    window: an explicit ``article_ids`` set wins, else the search filters resolve the
    set. Streams NDJSON honest progress (invariant #20)."""
    cap = req.limit if (req.limit and req.limit > 0) else None  # uncapped by default (2026-06-20)
    work = _resolve_work(
        db, article_ids=req.article_ids, query=req.query, source=req.source,
        language=req.language, start_date=req.start_date, end_date=req.end_date, cap=cap,
    )
    model = req.model or active_model()
    max_terms = max(1, min(req.max_terms or 20, 100))

    # Part B: the built-in extraction prompt is tunable (Settings → Models). An operator
    # override replaces _EXTRACT_SYSTEM; "" = the built-in. Recorded as a distinct
    # provenance version so a result's prompt is never ambiguous after an edit.
    from src.ai_layer.extract import EXTRACT_PROMPT_VERSION
    from src.config.app_settings import load_settings

    try:
        _override = (load_settings().llm_prompt_ai_keywords or "").strip()
    except Exception:  # noqa: BLE001 - a settings hiccup must not break extraction
        _override = ""
    system = _override or None
    pv = "ai-keywords-custom" if system else EXTRACT_PROMPT_VERSION

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
                skip_existing=req.skip_existing, system=system, prompt_version=pv,
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
    article_id: int,
    kind: str | None = None,
    confirmed_only: bool = False,
    db: Session = Depends(get_db),
) -> dict:
    """The AI-derived keywords stored for one article (the read-only lens).

    Returns an empty list when an article has no AI keywords yet — the ``ai_keyword``
    table always exists in the main DB, and a read never writes anything."""
    rows = ai_store.keywords_for_article(
        db, article_id, kind=kind, confirmed_only=confirmed_only
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
def confirm_ai_keyword(req: AiConfirmRequest, db: Session = Depends(get_db)) -> dict:
    """Curate the AI lens IN PLACE: confirm/unconfirm one AI keyword. The row stays
    AI-derived either way — a confirmed item never crosses into the trusted index."""
    ok = ai_store.set_confirmed(db, req.id, req.confirmed)
    if not ok:
        raise HTTPException(status_code=404, detail=f"AI keyword {req.id} not found.")
    db.commit()
    return {"id": req.id, "confirmed": req.confirmed, "ok": True}


# --------------------------------------------------------------------------- #
#  TENTATIVE keyword translation (Phase 4 of language-aware keywords): the
#  fallback for keywords no VERIFIED ring covers. Output is labelled unreliable,
#  cached, never written to any store, loopback-only; airplane mode refuses it.
# --------------------------------------------------------------------------- #
class AiTranslateItem(BaseModel):
    term: str
    language: str | None = None


class AiTranslateRequest(BaseModel):
    terms: list[AiTranslateItem]
    target_lang: str


_TRANSLATE_TENTATIVE_NOTE = (
    "AI-generated TENTATIVE translation — unreliable, not verified, never stored. The "
    "verified cross-language ring translation always takes precedence."
)


@router.post("/translate-keywords")
def translate_keywords_ep(
    req: AiTranslateRequest,
    client: OllamaClient = Depends(get_llm_client),
) -> dict:
    """Tentative LLM translations for the keywords a verified ring does NOT cover.

    Verified ring terms are skipped (the verified tier wins). Loopback-only (no
    network-consent popup, like the other Ollama paths); when Ollama is unavailable —
    including airplane mode (the kill switch) — returns ``available: false`` with no
    translations and WITHOUT attempting a model call."""
    from src.ai_layer.translate import TRANSLATE_PROMPT_VERSION, translate_keywords

    tgt = (req.target_lang or "").strip().lower()
    base = {
        "source": "llm-tentative",
        "caveat": _TRANSLATE_TENTATIVE_NOTE,
        "prompt_version": TRANSLATE_PROMPT_VERSION,
    }
    if not tgt or len(tgt) > 3 or not tgt.isalpha():
        return {**base, "available": True, "translations": {}}
    if not client.is_available():  # Ollama down or airplane mode -> no socket, no fabrication
        return {**base, "available": False, "translations": {}}
    items = [{"term": it.term, "language": it.language} for it in req.terms]
    translations = translate_keywords(client, items, tgt, model=active_model())
    return {**base, "available": True, "translations": translations}


# --------------------------------------------------------------------------- #
#  User-defined AI extractors (maintainer ask 2026-06-18) — a managed list of
#  custom prompts, each an EXTENSION of the built-in who/where/when extractors:
#  it declares an output_kind (the metadata TYPE) and its results are stored as
#  AiKeyword rows of that kind — the UNIFIED, prompt-related AI-metadata store.
#  Definitions are config (no AI output here). A prompt runs ON DEMAND (below) and,
#  per run_on_ingest, also automatically at ingest (that hook is a follow-up slice).
# --------------------------------------------------------------------------- #


def _prompt_dict(p: AiCustomPrompt) -> dict:
    return {
        "id": p.id,
        "label": p.label,
        "output_kind": p.output_kind,
        "prompt_text": p.prompt_text,
        "run_on_ingest": p.run_on_ingest,
        "enabled": p.enabled,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


class AiPromptIn(BaseModel):
    label: str
    output_kind: str
    prompt_text: str
    run_on_ingest: bool = False
    enabled: bool = True


def _validate_prompt(label: str, output_kind: str, prompt_text: str) -> tuple[str, str, str]:
    label = (label or "").strip()
    kind = (output_kind or "").strip().lower()
    text = (prompt_text or "").strip()
    if not label or len(label) > 80:
        raise HTTPException(status_code=422, detail="label is required (<= 80 chars).")
    if not _KIND_RE.match(kind):
        raise HTTPException(
            status_code=422,
            detail="output_kind must be a short lowercase token [a-z][a-z0-9_-] (<= 40).",
        )
    if not text or len(text) > _PROMPT_MAX:
        raise HTTPException(
            status_code=422, detail=f"prompt_text is required (<= {_PROMPT_MAX} chars)."
        )
    return label, kind, text


@router.get("/prompts")
def list_custom_prompts(db: Session = Depends(get_db)) -> dict:
    """The managed list of user-defined AI extractors (config; no AI output here)."""
    rows = db.query(AiCustomPrompt).order_by(AiCustomPrompt.id).all()
    return {"prompts": [_prompt_dict(p) for p in rows], "note": _LENS_NOTE}


@router.post("/prompts")
def create_custom_prompt(req: AiPromptIn, db: Session = Depends(get_db)) -> dict:
    label, kind, text = _validate_prompt(req.label, req.output_kind, req.prompt_text)
    p = AiCustomPrompt(
        label=label, output_kind=kind, prompt_text=text,
        run_on_ingest=bool(req.run_on_ingest), enabled=bool(req.enabled),
    )
    db.add(p)
    db.commit()
    return _prompt_dict(p)


@router.put("/prompts/{prompt_id}")
def update_custom_prompt(prompt_id: int, req: AiPromptIn, db: Session = Depends(get_db)) -> dict:
    p = db.get(AiCustomPrompt, prompt_id)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Custom prompt {prompt_id} not found.")
    label, kind, text = _validate_prompt(req.label, req.output_kind, req.prompt_text)
    p.label, p.output_kind, p.prompt_text = label, kind, text
    p.run_on_ingest, p.enabled = bool(req.run_on_ingest), bool(req.enabled)
    db.commit()
    return _prompt_dict(p)


@router.delete("/prompts/{prompt_id}")
def delete_custom_prompt(prompt_id: int, db: Session = Depends(get_db)) -> dict:
    p = db.get(AiCustomPrompt, prompt_id)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Custom prompt {prompt_id} not found.")
    db.delete(p)
    db.commit()
    return {"id": prompt_id, "deleted": True}


class AiPromptRunRequest(BaseModel):
    article_ids: list[int] | None = None
    query: str | None = None
    source: str | None = None
    language: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    model: str | None = None
    max_terms: int = 20
    skip_existing: bool = True
    limit: int = 0  # 0 = no cap (process the whole matched set)


@router.post("/prompts/{prompt_id}/run")
def run_custom_prompt(
    prompt_id: int,
    req: AiPromptRunRequest,
    db: Session = Depends(get_db),
    client: OllamaClient = Depends(get_llm_client),
):
    """Run a user-defined extractor over a matched article set, storing its results as
    ``ai_keyword`` rows of the prompt's ``output_kind`` (the unified AI-metadata store) —
    NEVER the trusted index. Same selection + NDJSON streaming + task-manager visibility
    as the keyword extractor; provenance is recorded as ``custom:<id>``."""
    p = db.get(AiCustomPrompt, prompt_id)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Custom prompt {prompt_id} not found.")
    cap = req.limit if (req.limit and req.limit > 0) else None  # uncapped by default (2026-06-20)
    work = _resolve_work(
        db, article_ids=req.article_ids, query=req.query, source=req.source,
        language=req.language, start_date=req.start_date, end_date=req.end_date, cap=cap,
    )
    model = req.model or active_model()
    max_terms = max(1, min(req.max_terms or 20, 100))
    system, out_kind, pv, label = p.prompt_text, p.output_kind, f"custom:{p.id}", p.label

    from src.monitoring import tasks as _bgtasks

    _tok = _bgtasks.register(
        "analytics", f"AI: {label} · {len(work)} article(s)",
        detail=f"model {model}", total=len(work),
    )

    def _stream():
        try:
            done = 0
            for event in extract_for_articles(
                work, client, model=model, kind=out_kind, max_terms=max_terms,
                skip_existing=req.skip_existing, system=system, prompt_version=pv,
            ):
                if isinstance(event, dict) and event.get("event") == "item":
                    done += 1
                    _bgtasks.update(_tok, done=done)
                yield json.dumps(event, separators=(",", ":")) + "\n"
        finally:
            _bgtasks.finish(_tok)

    return StreamingResponse(_stream(), media_type="application/x-ndjson")


# --------------------------------------------------------------------------- #
# B15: OPT-IN local-LLM language detection for articles STILL unknown after the
# offline detector. A THIRD, labelled "AI-derived · unreliable" language class in
# ai_keyword — NEVER Article.language / Article.detected_language. Detector-first,
# validated (garbage stores nothing), cancellable, visible in /api/jobs, never on
# the scrape hot path. Local loopback only; airplane mode refuses it at the client.
# --------------------------------------------------------------------------- #
from src.ai_layer.langdetect_llm import detect_for_articles, unknown_language_work  # noqa: E402
from src.database.session import session_scope  # noqa: E402
from src.jobs.background import BackgroundJob, register_job  # noqa: E402

_LANGDETECT_LIMIT = 500  # per-BATCH bound (an internal chunk size, not a run cap — see below)


def _langdetect_candidate_count(session) -> int:
    """Same predicate as unknown_language_work (without a limit): how many articles are
    the job's actual worklist right now. Counts only, no score — used as the continuous-mode
    progress bar's initial total estimate."""
    from sqlalchemy import func, or_, select

    from src.ai_layer.langdetect_llm import _already_labelled

    unset = lambda col: or_(col.is_(None), col == "")  # noqa: E731
    n = session.execute(
        select(func.count(Article.id)).where(
            unset(Article.language), unset(Article.detected_language), ~_already_labelled()
        )
    ).scalar() or 0
    return int(n)


def _langdetect_worker(
    ctx, *, model: str | None = None, limit: int = _LANGDETECT_LIMIT, continuous: bool = False
) -> dict:
    """Detect a language label for articles the offline detector could not classify.
    Opt-in + cancellable; writes ONLY ai_keyword(kind=language). No-op (never a wall of
    failed events) when the local model is unavailable.

    ``continuous=False`` (the default) runs exactly ONE bounded batch of at most ``limit``
    articles, unchanged from before this option existed — the user re-triggers the job to
    continue the tail.

    ``continuous=True`` (maintainer ask 2026-07-23: "an on/off switch that allows for the
    continuous analysis of articles until none are left, or the leftovers are those articles
    whose languages could not be deduced") chains internal batches — each still capped at
    ``limit`` for bounded per-query cost — until the worklist genuinely comes back empty or
    the job is cancelled. Every attempted article id (whether it ended up stored, skipped,
    failed, or an unclassifiable "none") is tracked in an in-memory ``attempted`` set for the
    DURATION OF THIS RUN and excluded from every subsequent batch query via
    ``exclude_ids`` — without this, a "none" result writes no ai_keyword row, so the SAME
    newest-first unclassifiable articles would re-occupy every batch's query window forever
    and the rest of the backlog would never be reached. Once the query returns empty, every
    currently-unknown article has been attempted this run: whatever remains unlabelled in the
    DB at that point IS exactly the residue whose language could not be deduced."""
    tally: dict = {"total": 0, "stored": 0, "skipped": 0, "failed": 0, "none": 0, "ran": False}
    client = OllamaClient()
    try:
        if not client.is_available():
            tally["reason"] = "the local model is unavailable (Ollama down or airplane mode)"
            return tally
    except Exception:  # noqa: BLE001
        tally["reason"] = "the local model is unavailable"
        return tally
    mdl = model or active_model()
    bound = max(1, min(int(limit or _LANGDETECT_LIMIT), 5000))
    tally["ran"] = True

    attempted: set[int] = set()
    done = 0
    with session_scope() as session:
        estimate_total = _langdetect_candidate_count(session)
    ctx.set_progress(done=0, total=estimate_total, detail=f"model {mdl}")

    while True:
        if ctx.stopping:
            tally["aborted"] = True
            break
        with session_scope() as session:  # read the worklist, then release the session
            work = unknown_language_work(session, bound, exclude_ids=attempted)
        if not work:
            break  # nothing left to attempt this run (stored, or the undeducible residue)
        tally["total"] += len(work)
        for event in detect_for_articles(work, client, model=mdl, should_stop=lambda: ctx.stopping):
            ev = event.get("event")
            if ev == "item":
                done += 1
                attempted.add(event["article_id"])
                st = event.get("status")
                if st in ("stored", "skipped", "failed", "none"):
                    tally[st] += 1
                ctx.set_progress(
                    done=done, total=max(estimate_total, done), detail=f"{tally['stored']} labelled"
                )
            elif ev == "done" and event.get("aborted"):
                tally["aborted"] = True
        if not continuous or tally.get("aborted"):
            break
    tally["remaining_unclassified"] = tally["none"]
    return tally


_LANGDETECT_JOB = register_job(
    BackgroundJob(
        "ai-langdetect", "Detecting article languages (AI, unreliable)", _langdetect_worker,
        is_writer=True, cancellable=True,
    )
)


class LangDetectBody(BaseModel):
    model: str | None = None
    limit: int | None = None
    continuous: bool = False


@router.post("/detect-language")
def ai_detect_language_start(body: LangDetectBody | None = None) -> dict:
    """Start the OPT-IN local-LLM language-detection job. Writes a THIRD 'AI-derived ·
    unreliable' language class into ai_keyword — never the authoritative or offline-deduced
    channels. Cancellable + visible in /api/jobs; never the scrape hot path. 409-free: returns
    the current status if a run is already in flight.

    ``continuous`` (default False) chains internal batches until the whole backlog is
    exhausted or the job is cancelled, instead of stopping after one bounded batch."""
    b = body or LangDetectBody()
    try:
        return {
            "started": True,
            "job": _LANGDETECT_JOB.start(
                model=b.model, limit=b.limit or _LANGDETECT_LIMIT, continuous=b.continuous
            ),
        }
    except RuntimeError:
        return {"started": False, "job": _LANGDETECT_JOB.status()}


@router.get("/detect-language/status")
def ai_detect_language_status() -> dict:
    """Live status of the language-detection job (state, progress, and the final tally)."""
    return _LANGDETECT_JOB.status()


@router.post("/detect-language/cancel")
def ai_detect_language_cancel() -> dict:
    """Ask the running job to stop at its next article (cooperative; never kills a thread)."""
    _LANGDETECT_JOB.cancel()
    return _LANGDETECT_JOB.status()


@router.get("/detect-language/candidates")
def ai_detect_language_candidates(db: Session = Depends(get_db)) -> dict:
    """How many articles are the job's actual worklist — still unknown after the offline
    detector AND not yet AI-labelled (the SAME predicate as unknown_language_work, so the
    count falls as the job runs and reaches 0 when the reachable tail is done). Counts only,
    no score."""
    return {"candidates": _langdetect_candidate_count(db)}
