"""
Briefing API: the Home triage feed, dismissals, and the draft accumulator.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``GET /api/briefing`` serves the cached card feed (instant Home); ``refresh``
recomputes it from the registered producers. Dismissals and the newsletter draft are
single-user JSON state under the data dir. Every card already carries its method,
caveat and evidence — this router only moves them; it never computes a verdict.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.briefing import draft as draft_store
from src.briefing import service
from src.database.session import get_db

router = APIRouter(prefix="/api/briefing", tags=["briefing"])


class CardRef(BaseModel):
    id: str


class DraftAdd(BaseModel):
    card: dict
    note: str = ""


class NoteUpdate(BaseModel):
    id: str
    note: str = ""


class TitleUpdate(BaseModel):
    title: str


@router.get("")
def get_briefing(
    force: bool = False,
    include_dismissed: bool = False,
    db: Session = Depends(get_db),
) -> dict:
    """The cached briefing feed, grouped by bucket (recomputes once if absent)."""
    return service.get_briefing(db, force=force, include_dismissed=include_dismissed)


@router.post("/refresh")
def refresh_briefing(db: Session = Depends(get_db)) -> dict:
    """Recompute the briefing now (also done automatically after each scrape)."""
    service.refresh_briefing(db)
    return service.get_briefing(db)


@router.post("/dismiss")
def dismiss_card(ref: CardRef) -> dict:
    """Hide a card from the feed (reversible — it can be restored)."""
    if not ref.id:
        raise HTTPException(status_code=400, detail="id is required")
    ids = service.dismiss(ref.id)
    return {"dismissed": sorted(ids)}


@router.post("/restore")
def restore_card(ref: CardRef) -> dict:
    """Un-dismiss a previously dismissed card."""
    ids = service.restore(ref.id)
    return {"dismissed": sorted(ids)}


@router.post("/dismissed/clear")
def clear_dismissed() -> dict:
    """Restore every dismissed card."""
    service.clear_dismissed()
    return {"dismissed": []}


# --- draft accumulator ----------------------------------------------------- #

@router.get("/draft")
def get_draft() -> dict:
    """The current newsletter draft (pinned cards + notes)."""
    return draft_store.load_draft()


@router.post("/draft/add")
def draft_add(body: DraftAdd) -> dict:
    """Pin a card into the draft."""
    try:
        return draft_store.add_card(body.card, note=body.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/draft/{card_id}")
def draft_remove(card_id: str) -> dict:
    """Remove a pinned card from the draft."""
    return draft_store.remove_card(card_id)


@router.put("/draft/note")
def draft_note(body: NoteUpdate) -> dict:
    """Set the user's note on a pinned card."""
    return draft_store.set_note(body.id, body.note)


@router.put("/draft/title")
def draft_title(body: TitleUpdate) -> dict:
    """Rename the draft (the exported issue's title)."""
    return draft_store.set_title(body.title)


@router.post("/draft/clear")
def draft_clear() -> dict:
    """Empty the draft."""
    return draft_store.clear_draft()


@router.get("/draft/export.md", response_class=PlainTextResponse)
def draft_export() -> str:
    """Export the draft as evidence-carrying Markdown."""
    return draft_store.export_markdown()
