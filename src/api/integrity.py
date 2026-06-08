"""
Source-integrity API: the no-composite profile + user-guided actor-collapse (§6 C+D).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Read endpoints surface *measured* signals (a source profile with no composite score;
the proposed actor graph; story prominence raw vs collapsed). Write endpoints record
only the user's explicit collapse decisions — the app proposes, the user disposes;
nothing is ever auto-applied.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.database.session import get_db
from src.integrity import collapse as collapse_mod
from src.integrity import profile as profile_mod

router = APIRouter(prefix="/api/integrity", tags=["integrity"])


class SignatureBody(BaseModel):
    signature: str


@router.get("/profile")
def get_profile(source: str, days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)) -> dict:
    """A source's measured-signal panel — coordination, novelty, capacity, transparency,
    track-record. **No composite trust score** (§6)."""
    result = profile_mod.source_profile(db, source, days=days)
    if not result.get("found"):
        raise HTTPException(status_code=404, detail=f"Source '{source}' not found.")
    return result


@router.get("/actors")
def get_actors(days: int = Query(14, ge=1, le=180), db: Session = Depends(get_db)) -> dict:
    """Proposed coordinated actors over the recent corpus, each flagged applied/not."""
    return collapse_mod.collapse_status(db, days=days)


@router.get("/prominence")
def get_prominence(
    days: int = Query(14, ge=1, le=180),
    weight_by_novelty: bool = False,
    db: Session = Depends(get_db),
) -> dict:
    """Story prominence in independent voices — raw vs actor-collapsed (the equal view
    one toggle away). ``weight_by_novelty`` (opt-in) additionally weights each story by
    the new information it contributes vs the corpus."""
    return collapse_mod.story_prominence(db, days=days, weight_by_novelty=weight_by_novelty)


@router.post("/collapse/apply")
def apply_collapse(body: SignatureBody) -> dict:
    """Apply a proposed collapse (an explicit user action; reversible, stays flagged)."""
    if not body.signature:
        raise HTTPException(status_code=400, detail="signature is required")
    return {"applied": sorted(collapse_mod.apply_collapse(body.signature))}


@router.post("/collapse/revert")
def revert_collapse(body: SignatureBody) -> dict:
    """Undo an applied collapse — the raw equal view returns for that cluster."""
    return {"applied": sorted(collapse_mod.revert_collapse(body.signature))}


@router.post("/collapse/apply_all")
def apply_all(days: int = Query(14, ge=1, le=180), db: Session = Depends(get_db)) -> dict:
    """Apply every currently-proposed actor (collapse globally)."""
    return {"applied": sorted(collapse_mod.apply_all(db, days=days))}


@router.post("/collapse/revert_all")
def revert_all() -> dict:
    """Undo all applied collapses."""
    return {"applied": sorted(collapse_mod.revert_all())}
