"""Stopword review endpoints (R98, D11): list batches, decide, export.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Loopback and local: no network, no egress, so no consent gate (invariant #14 covers egress and
this reaches nothing outside the database and the shipped batch files). Nothing here changes a
stoplist or a keyword; see ``src/analytics/stopword_review.py`` for what the screen refuses.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.analytics import stopword_review as review
from src.database.session import get_db

router = APIRouter(prefix="/api/keywords/stopword-review", tags=["Keywords"])


class DecisionBody(BaseModel):
    language: str
    term: str
    decision: str | None = None  # accept | reject | clear


@router.get("/languages")
def review_languages() -> dict:
    """The languages with a shipped candidate batch, and how far each review has got."""
    data = review.load_batches()
    return {"languages": review.languages(), "errors": data["errors"]}


@router.get("")
def review_candidates(language: str = Query(..., min_length=2, max_length=10), db: Session = Depends(get_db)) -> dict:
    """The candidates for one language with their evidence and the decisions recorded so far."""
    return review.review_state(db, language)


@router.put("/decision")
def review_decide(body: DecisionBody) -> dict:
    """Accept, reject or clear one proposed word. A refusal is a 409 with the reason in words."""
    try:
        return review.record_decision(body.language, body.term, body.decision)
    except review.ReviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/export")
def review_export(language: str = Query(..., min_length=2, max_length=10), db: Session = Depends(get_db)) -> dict:
    """The language's decisions as a reviewed-batch YAML document to save. Applied nowhere."""
    try:
        text = review.export_batch(db, language)
    except review.ReviewError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    state = review.review_state(db, language)
    return {
        "language": state["language"],
        "filename": f"stopword-review-{state['language']}.yml",
        "accepted": state["counts"]["accepted"],
        "rejected": state["counts"]["rejected"],
        "yaml": text,
    }
