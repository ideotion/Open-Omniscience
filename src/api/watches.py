"""Convergence watch-engine API (ruling 2026-06-17 #3, ON by default).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The Watches view: create / list / edit / enable-disable / delete saved local
conditions, browse each watch's firing history, and run an evaluation on demand. All
LOCAL — no network, no consent gate (a watch reads the corpus and writes only the two
local tables); the engine also runs automatically inside every briefing refresh.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.database.session import get_db

router = APIRouter(prefix="/api/watches", tags=["watches"])


class WatchBody(BaseModel):
    name: str = Field("", max_length=200)
    query: str = Field(..., min_length=1, max_length=2000)
    threshold: int = Field(3, ge=1, le=10000)
    window_days: int = Field(7, ge=1, le=3650)
    enabled: bool = True


class WatchPatch(BaseModel):
    name: str | None = Field(None, max_length=200)
    query: str | None = Field(None, max_length=2000)
    threshold: int | None = Field(None, ge=1, le=10000)
    window_days: int | None = Field(None, ge=1, le=3650)
    enabled: bool | None = None


@router.get("")
def list_watches(db: Session = Depends(get_db)) -> dict:
    """Every watch with its recent firing history (the Watches panel)."""
    from src.analytics.watches import list_watches as _list

    watches = _list(db)
    return {
        "count": len(watches),
        "watches": watches,
        "caveat": (
            "A watch is a saved search that fires when enough new articles match your "
            "threshold — a prompt to read, never a verdict or score. Local-only: no "
            "notifications, no network."
        ),
    }


@router.post("")
def create_watch(body: WatchBody, db: Session = Depends(get_db)) -> dict:
    from src.analytics.watches import create_watch as _create

    try:
        w = _create(
            db, name=body.name, query=body.query,
            threshold=body.threshold, window_days=body.window_days, enabled=body.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return {"id": w.id, "name": w.name, "query": w.query, "enabled": bool(w.enabled)}


@router.patch("/{watch_id}")
def update_watch(watch_id: int, body: WatchPatch, db: Session = Depends(get_db)) -> dict:
    from src.analytics.watches import update_watch as _update

    w = _update(db, watch_id, **body.model_dump(exclude_none=True))
    if w is None:
        raise HTTPException(status_code=404, detail="no such watch")
    db.commit()
    return {"id": w.id, "name": w.name, "query": w.query, "enabled": bool(w.enabled),
            "threshold": w.threshold, "window_days": w.window_days}


@router.delete("/{watch_id}")
def delete_watch(watch_id: int, db: Session = Depends(get_db)) -> dict:
    from src.analytics.watches import delete_watch as _delete

    if not _delete(db, watch_id):
        raise HTTPException(status_code=404, detail="no such watch")
    db.commit()
    return {"deleted": watch_id}


@router.get("/{watch_id}/history")
def watch_history(
    watch_id: int, limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)
) -> dict:
    from src.analytics.watches import watch_history as _history

    return {"watch_id": watch_id, "history": _history(db, watch_id, limit=limit)}


@router.post("/evaluate")
def evaluate_now(db: Session = Depends(get_db)) -> dict:
    """Run the engine on demand (it also runs automatically in every briefing refresh).

    Returns the watches that fired this pass. LOCAL only — reads the corpus, writes the
    two watch tables; no network."""
    from src.analytics.watches import evaluate_watches as _evaluate

    fired = _evaluate(db)
    db.commit()
    return {"fired": fired, "count": len(fired)}
