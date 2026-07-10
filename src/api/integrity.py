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

from src.api.heavy import guarded_read
from src.database.session import get_db
from src.integrity import collapse as collapse_mod
from src.integrity import profile as profile_mod
from src.verification.fixity import audit_fixity

router = APIRouter(prefix="/api/integrity", tags=["integrity"])


class SignatureBody(BaseModel):
    signature: str


@router.get("/profile")
def get_profile(
    source: str, days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)
) -> dict:
    """A source's measured-signal panel — coordination, novelty, capacity, transparency,
    track-record. **No composite trust score** (§6).

    Under the shared heavy-read guard (:func:`src.api.heavy.guarded_read`): the profile runs
    coordination/novelty scans over the source's recent corpus, so it takes a slot in the
    global heavy-concurrency cap + a statement deadline, and duplicate concurrent requests
    for the same (source, days) share one compute — it can never join the Home-poll thrash.
    The cheap not-found check stays OUTSIDE the guard (an honest 404, never shared as a
    heavy result)."""
    key = f"integrity-profile|source={source}|days={days}"
    result = guarded_read(db, key, lambda: profile_mod.source_profile(db, source, days=days))
    if not result.get("found"):
        raise HTTPException(status_code=404, detail=f"Source '{source}' not found.")
    return result


@router.get("/actors")
def get_actors(days: int = Query(14, ge=1, le=180), db: Session = Depends(get_db)) -> dict:
    """Proposed coordinated actors over the recent corpus, each flagged applied/not.

    Guarded (:func:`src.api.heavy.guarded_read`): the MinHash/LSH near-duplicate coordination
    scan is corpus-wide and heavy on a large encrypted corpus, so it runs under the global
    heavy cap + deadline with same-``days`` single-flight — bounded, never a pile-up."""
    key = f"integrity-actors|days={days}"
    return guarded_read(db, key, lambda: collapse_mod.collapse_status(db, days=days))


@router.get("/prominence")
def get_prominence(
    days: int = Query(14, ge=1, le=180),
    weight_by_novelty: bool = False,
    db: Session = Depends(get_db),
) -> dict:
    """Story prominence in independent voices — raw vs actor-collapsed (the equal view
    one toggle away). ``weight_by_novelty`` (opt-in) additionally weights each story by
    the new information it contributes vs the corpus.

    Guarded (:func:`src.api.heavy.guarded_read`): prominence recomputes the coordinated-actor
    collapse and (optionally) per-story novelty over the recent corpus — heavy at scale — so
    it runs under the global heavy cap + deadline, single-flighted on its exact parameters."""
    key = f"integrity-prominence|days={days}|nov={int(weight_by_novelty)}"
    return guarded_read(
        db,
        key,
        lambda: collapse_mod.story_prominence(
            db, days=days, weight_by_novelty=weight_by_novelty
        ),
    )


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


@router.get("/fixity")
def get_fixity(
    limit: int | None = Query(None, ge=1, description="Optional cap on rows checked."),
    db: Session = Depends(get_db),
) -> dict:
    """Local fixity audit -- re-hash stored articles against their capture-time hash.

    "Reliable memory turned inward": a read-only, LOCAL, no-network integrity check
    that proves the stored corpus still hashes to what was recorded at ingest. Any
    divergence (the stored content no longer matches its ``Article.hash``) is
    reported LOUDLY in ``mismatches``; nothing is ever auto-fixed. The exact method
    compared travels in the ``method`` field. ``?limit=`` bounds the work.

    Guarded (:func:`src.api.heavy.guarded_read`): a full-corpus re-hash decrypts and hashes
    every article — one of the heaviest reads — so it takes a slot in the global heavy cap +
    is single-flighted on ``limit`` (the load-bearing anti-pile-up bounds). The statement
    deadline is BEST-EFFORT here: it fires from the SQLite progress handler at fetch
    boundaries, so it is soft against the CPU-bound SHA-256 hashing that dominates fixity's
    wall-time — the reliable way to bound the work is the explicit ``?limit=``. Either way,
    an interrupt/deadline RAISES (HTTP 503), so a truncated audit is NEVER returned as a
    false "all clear".
    """
    key = f"integrity-fixity|limit={limit if limit is not None else 'all'}"
    return guarded_read(db, key, lambda: audit_fixity(db, limit=limit))
