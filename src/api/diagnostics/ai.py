"""
AI diagnostics and the qualification-assist endpoints.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Part of the mechanical ``src/api/diagnostics.py`` -> package split (Q1139 = a,
2026-09-16): this file is lines 6193-6302 of the pre-split module, verbatim. The
routes, their paths, their methods and their order are unchanged; ``__init__``
imports the submodules in the original file order so the decorators still
register on one router in that order.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.database.session import get_db

from ._base import router

# Language -> script, for sizing the context window in CHARACTERS. Only the
# scripts src.ai_layer.context knows a chars-per-word estimate for appear here; a
# language absent from this map falls back to "latin", which is the conservative
# direction (it over-estimates characters per word, so the window is sized a little
# large rather than a little short).
_SCRIPT_OF_LANG = {
    "ru": "cyrillic", "uk": "cyrillic", "bg": "cyrillic", "sr": "cyrillic", "mk": "cyrillic",
    "el": "greek", "ar": "arabic", "fa": "arabic", "ur": "arabic", "he": "hebrew",
    "hi": "devanagari", "mr": "devanagari", "ne": "devanagari", "bn": "bengali",
    "th": "thai", "zh": "cjk", "ja": "cjk", "ko": "cjk",
}


@router.get("/ai")
def ai_diagnostics(
    measure_corpus: bool = Query(False), db: Session = Depends(get_db)
) -> JSONResponse:
    """B7.1 (2026-07-24 Session B): a secret-safe, read-only snapshot of the whole
    dual-backend AI stack -- which backend is active and why (hardware detection
    facts), the active model, context/concurrency settings, and the last saved
    summary of every AI-layer background job. Never runs anything; rides the
    all-diagnostics bundle by default.

    ``measure_corpus`` (E-S4, 2026-08-01) additionally measures the article-length
    distribution so the Ollama context auto-tune can size the window to the corpus
    that actually exists. OFF by default and deliberately so: that measurement is a
    full-table pass, and a bundle member that quietly ran one would make reading the
    AI settings the most expensive click in diagnostics. Without it the auto-tune
    reports UNMEASURED and names this flag, rather than proposing a number from
    nothing."""
    from src.monitoring.ai_diagnostics import ai_diagnostics_report

    corpus = None
    if measure_corpus:
        from src.analytics.article_length import article_length_report

        report = article_length_report(db)
        by_lang = report.get("word_count_by_language") or {}
        # The dominant language's own p95, not the corpus-wide one: the window is
        # spent on characters, and a corpus-wide word figure mixes scripts whose
        # characters-per-word differ by more than the figure itself.
        top = max(by_lang.items(), key=lambda kv: (kv[1] or {}).get("n") or 0, default=None)
        if top and not (top[1] or {}).get("unsegmented"):
            corpus = {"p95_words": (top[1] or {}).get("p95"), "script": _SCRIPT_OF_LANG.get(top[0], "latin")}
    return JSONResponse(ai_diagnostics_report(corpus))


# ---------------------------------------------------------------------------
#  Qualification ASSIST -- propose-only LLM nav-soup/extraction-junk flagging
#  (B7.2, 2026-07-24 Session B, ruled "propose-only"). A bounded, SYNCHRONOUS
#  per-source run (mirrors /ir-eval's "bounded read-only eval" posture, not a
#  background job -- scoped to one source's small trial-fetch article set).
#  NEVER touches Source.status/Source.tags; composes with the qualification
#  lifecycle + the prose gate as an additional, human-reviewed signal.
# ---------------------------------------------------------------------------


class QualificationAssistBody(BaseModel):
    source_id: int = Field(..., description="the Source row to check")
    model: str | None = Field(default=None, description="defaults to the active model")
    max_articles: int = Field(default=20, ge=1, le=200)


@router.post("/qualification-assist/run")
def qualification_assist_run(body: QualificationAssistBody, db: Session = Depends(get_db)) -> JSONResponse:
    """Classify up to ``max_articles`` of ``source_id``'s STORED articles as
    genuine-article/nav-soup via the active model, and persist the dated
    PROPOSALS artifact -- a signal for the maintainer/Claude-verification loop
    to review BESIDE the auditor's own evidence, never applied automatically
    (``Source.status``/``Source.tags`` are never touched). 404 if the source
    does not exist."""
    from src.database.models import Source

    if db.get(Source, body.source_id) is None:
        raise HTTPException(status_code=404, detail=f"no source with id {body.source_id}")
    from src.ai_layer.qualification_assist import run_and_persist_qualification_assist

    out = run_and_persist_qualification_assist(
        db, body.source_id, model=body.model, max_articles=body.max_articles
    )
    return JSONResponse(out)


@router.get("/qualification-assist/last")
def qualification_assist_last(source_id: int | None = Query(None)) -> JSONResponse:
    """The newest saved qualification-assist proposals artifact -- optionally
    filtered to ONE ``source_id``. Read-only; never runs anything. Honest
    ``{available: false}`` when none exists (for that source, or at all)."""
    from src.ai_layer.qualification_assist import last_qualification_assist_report

    return JSONResponse(last_qualification_assist_report(source_id=source_id))


@router.get("/qualification-assist-selftest")
def qualification_assist_selftest(download: bool = Query(False)) -> JSONResponse:
    """Run the qualification-assist self-test -- the measure-before-trust GATE
    before any real run, mirroring ``/keyword-triage-selftest``/``/source-tags-
    selftest`` exactly. Proves the constrained one-word parser, canaries, and
    the classify-and-tally mechanism on a deterministic STUB -- no model, no
    network, no score. ``download=1`` returns a dated attachment."""
    from src.ai_layer.qualification_assist import run_qualification_assist_selftest

    log = run_qualification_assist_selftest()
    headers = {}
    if download:
        fname = f"oo-qualification-assist-selftest-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)
