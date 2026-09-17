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

import copy

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.analytics.equivalence import _norm
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


def _annotate_card_terms(payload: dict, db: Session, target_lang: str | None) -> dict:
    """Fill each keyword card's ``term_translation`` / ``term_lang`` for ONE reader.

    Q411 = a is a RULED EXCEPTION to the "data never translates" design note at
    ``i18n.js:162``: the keyword term normally travels as data precisely because a term
    must not be translated by the i18n walker, and this says that for the card TITLE it
    should be — through the template, not through the walker. So the template stays a
    fixed keyable frame and the translation arrives as another DATA var beside the term.

    WORKS ON A COPY. ``get_briefing`` serves a cached structure, and annotating it in
    place would stamp one reader's language onto everybody's — the defect
    ``_annotate_after_cache`` carries its own warning about. No copy at all when there is
    nothing to annotate, so the no-``target_lang`` path stays byte-identical.

    A card whose term has no translation keeps ``term_translation`` ABSENT, and the
    client then renders the untranslated template. Filling it with the term itself would
    make every card read "“Wahl” (translated from German: Wahl)".
    """
    tl = (target_lang or "").strip().casefold()
    if not tl or not isinstance(payload, dict):
        return payload
    from src.analytics.equivalence import resolve_translation
    from src.analytics.translation_store import tentative_translations

    cards = [
        c
        for bucket in (payload.get("cards") or {}).values() if isinstance(bucket, list)
        for c in bucket if isinstance(c, dict) and isinstance(c.get("title_vars"), dict)
        and c["title_vars"].get("term")
    ]
    if not cards:
        return payload
    terms = [str(c["title_vars"]["term"]) for c in cards]
    langs = _term_languages(db, terms)
    try:
        tent = tentative_translations(db, terms, tl)
    except Exception:  # noqa: BLE001 - a pre-migration store: the ladder reports untranslated
        tent = {}
    out = copy.deepcopy(payload)
    out_cards = [
        c
        for bucket in (out.get("cards") or {}).values() if isinstance(bucket, list)
        for c in bucket if isinstance(c, dict) and isinstance(c.get("title_vars"), dict)
        and c["title_vars"].get("term")
    ]
    for card in out_cards:
        term = str(card["title_vars"]["term"])
        key = _norm(term)
        src = langs.get(key)
        res = resolve_translation(src, key, tl, tentative=tent.get(key))
        if src:
            card["title_vars"]["term_lang"] = src
        card["translation_tier"] = res.tier
        if res.text:
            card["title_vars"]["term_translation"] = res.text
            card["title_i18n"] = _TRANSLATED_TITLE
    return out


#: Q411 = a's template, VERBATIM from the ruling. Swapped in for a card whose term was
#: actually translated; a card without a translation keeps the producer's own template,
#: because a frame with an unfilled hole renders a literal ``{term_translation}``.
_TRANSLATED_TITLE = '“{term_translation}” (translated from {term_lang}: {term})'


def _term_languages(db: Session, terms: list[str]) -> dict[str, str]:
    """``{normalised term: language}`` from the keyword index, for the cards on screen.

    Reads ``Keyword.language``, which Q414 = a demoted to a CACHE of the per-mention
    majority that ``reconcile_keyword_language`` maintains. Good enough here and stated
    as such: a card title is a display surface, the ladder refuses rather than guesses
    when the language is absent, and an unknown language simply leaves the card
    untranslated rather than translating it from a language nobody measured.
    """
    from src.database.models import Keyword

    keys = [k for k in {_norm(t) for t in terms} if k]
    if not keys:
        return {}
    rows = db.query(Keyword.normalized_term, Keyword.language).filter(
        Keyword.normalized_term.in_(keys), Keyword.language.isnot(None)
    ).all()
    return {k: v for k, v in rows if v}


@router.get("")
def get_briefing(
    force: bool = False,
    include_dismissed: bool = False,
    target_lang: str | None = Query(None, description="UI language for keyword translations"),
    db: Session = Depends(get_db),
) -> dict:
    """The cached briefing feed, grouped by bucket. Recompute (when stale/absent or
    forced) runs OFF the request thread — the request never blocks; the response
    carries a ``refreshing`` flag + progress while a background recompute runs.

    ``target_lang`` is Q411 = a's seam, and it is read HERE rather than in the producer
    for a reason worth stating: a card is built once by a BACKGROUND refresh that has no
    reader and therefore no locale, and the only server-side candidate —
    ``settings.default_language`` — is declared and used by nothing in the tree (checked,
    2026-09-17). Translating a card at produce time would mean picking a language for
    everyone, so an Arabic reader would be served a French translation of a German term,
    which is worse than showing them the term. Annotating at SERVE time is the shape this
    API already uses for exactly this problem (``insights._annotate_after_cache``): the
    cache stays language-neutral and each reader gets their own answer.
    """
    out = service.get_briefing(
        db, force=force, include_dismissed=include_dismissed, background=True
    )
    return _annotate_card_terms(out, db, target_lang)


@router.post("/refresh")
def refresh_briefing(db: Session = Depends(get_db)) -> dict:
    """Kick a background recompute (also done automatically after each scrape) and
    return the current feed immediately with a ``refreshing`` flag — never blocks."""
    return service.get_briefing(db, force=True, background=True)


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
