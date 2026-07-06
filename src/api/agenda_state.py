"""
Agenda subscription-preferences API — the server-side home for calendar subscriptions.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

DB-reliability D4: agenda "smart-calendar" subscriptions (which curated calendars to
show, which to exclude, the view) lived only in browser ``localStorage`` — invisible
to the server and to backups. This exposes a durable REST path over the ``app_state``
store (:mod:`src.config.agenda_prefs`); the frontend can adopt it later and falls back
to its client default (``configured=false``) until it does. Local-only, no network.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.config.agenda_prefs import AgendaPrefsError, load_prefs, save_prefs

router = APIRouter(prefix="/api/agenda", tags=["agenda"])


class AgendaPrefsUpdate(BaseModel):
    subs: list[str] | None = None
    excluded: list[str] | None = None
    view: str | None = None


@router.get("/prefs")
def get_agenda_prefs() -> dict:
    """Return the stored agenda subscription prefs.

    ``configured=false`` means the server has no explicit choice yet — the client
    should keep its first-run default (subscribe to every calendar).
    """
    return load_prefs().to_dict()


@router.put("/prefs")
def update_agenda_prefs(update: AgendaPrefsUpdate) -> dict:
    """Apply a partial prefs update (only provided fields change) and persist it."""
    try:
        saved = save_prefs(update.model_dump(exclude_unset=True))
    except AgendaPrefsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return saved.to_dict()
