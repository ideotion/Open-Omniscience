"""The entity spine's HTTP face: Places, the Wikidata item cache, entity resolution (S05-03).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

ONE route egresses, and it is the only one gated: ``POST /items/fetch`` asks
``www.wikidata.org`` for the items the corpus mentions, at one request per 10 seconds (R8). It
refuses with a 409 that NAMES airplane mode (invariant #14e's corollary), and with a 400 unless
the caller says ``consent: true`` -- the UI passes the ONE network consent first, and a caller
that never opened the UI meets the same refusal (the lesson #14f recorded when OpenTimestamps
had a gated button in front of an ungated endpoint). Every other route reads local tables, or
writes Places from the local gazetteer, and makes no request.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.database.session import get_db
from src.jobs.background import BackgroundJob, register_job

router = APIRouter(prefix="/api/entities", tags=["entities"])


# ---- jobs ------------------------------------------------------------------------ #


def _items_worker(ctx, *, limit: int = 500) -> dict:
    from src.database.session import session_scope
    from src.entities import items as it

    with session_scope() as db:
        qids = it.mentioned_qids(db)
        from src.database.models import WikidataItem

        cached = {q for (q,) in db.query(WikidataItem.qid).filter(WikidataItem.qid.in_(qids)).all()} if qids else set()
    todo = [q for q in qids if q not in cached][:limit]
    ctx.set_progress(done=0, total=len(todo), detail="starting")

    def _progress(done: int, total: int, first: str) -> None:
        # The count, never the QID list or the URL: the task manager shows what the app
        # is doing, and a query string on a progress line is plumbing (invariant #8).
        ctx.set_progress(done=done, total=total, detail=f"{done}/{total}")

    return it.fetch_items(todo, session_factory=session_scope,
                          should_stop=lambda: ctx.stopping, progress=_progress)


#: NOT a writer in the arbitration sense (the ``wikidata-rings`` precedent): it writes one
#: small batch of cache rows every ten seconds at most, which is an ordinary short write,
#: and claiming the flag would ask the operator to stop a collection pass for a contention
#: that does not exist. ``cancellable`` is honest: the rate gate checks the stop flag.
_ITEMS_JOB = register_job(
    BackgroundJob(
        "wikidata-items", "Fetching Wikidata items for the places and people in your corpus",
        _items_worker, is_writer=False, cancellable=True,
    )
)


def _places_worker(ctx) -> dict:
    from src.database.session import session_scope
    from src.entities.places import resolve_mentioned

    ctx.set_progress(done=0, total=1, detail="resolving")
    with session_scope() as db:
        return resolve_mentioned(db, should_stop=lambda: ctx.stopping)


_PLACES_JOB = register_job(
    BackgroundJob(
        "resolve-places", "Resolving mentioned places through the gazetteer", _places_worker,
        is_writer=False, cancellable=True,
    )
)


# ---- Places ---------------------------------------------------------------------- #


@router.get("/places/card")
def place_card(
    id: str = Query(..., min_length=3, max_length=40),  # noqa: A002 - the Place's own key
    lang: str = Query("en", max_length=16),
    db: Session = Depends(get_db),
) -> dict:
    """One Place, as its card shows it. Local tables only; no network call."""
    from src.entities.places import place_card as _card

    out = _card(db, id, lang)
    if out is None:
        raise HTTPException(status_code=404, detail="no such place")
    return out


class _Mention(BaseModel):
    name: str
    country: str | None = None
    kind: str | None = None


@router.post("/places/resolve")
def resolve_place(body: _Mention, db: Session = Depends(get_db)) -> dict:
    """Resolve ONE mentioned place into its Place, materialising it from the gazetteer.

    A local write (the gazetteer is a file on this machine), so it is a POST; it makes no
    request. An unresolvable mention answers with the reason, never with a guessed Place.
    """
    from src.entities.places import _gazetteer, gazetteer_entry, materialise

    city, reason = gazetteer_entry(body.name, (body.country or "").lower() or None, body.kind)
    if reason is not None:
        return {"place_id": None, "reason": reason}
    _i, meta = _gazetteer()
    pid = materialise(db, city, vintage=meta.get("vintage"))
    db.commit()
    return {"place_id": pid, "reason": None}


@router.get("/places/search")
def search_places(q: str = Query(..., min_length=2, max_length=200), db: Session = Depends(get_db)) -> dict:
    from src.entities.places import search_places as _search

    return _search(db, " ".join(q.split()))


@router.get("/places/by-wiki")
def place_by_wiki(external_id: str = Query(..., min_length=3, max_length=512), db: Session = Depends(get_db)) -> dict:
    """Q819 step 2 from the wiki side: the Place a Wikipedia lane page resolves to, by QID."""
    from src.entities.places import place_for_wiki_page

    return place_for_wiki_page(db, external_id)


@router.post("/places/resolve-mentioned")
def resolve_mentioned() -> dict:
    """Materialise Places for every mentioned place the gazetteer resolves. No network call."""
    try:
        return {"started": True, "job": _PLACES_JOB.start()}
    except RuntimeError:
        return {"started": False, "job": _PLACES_JOB.status()}


@router.get("/places/resolve-mentioned/status")
def resolve_mentioned_status() -> dict:
    return _PLACES_JOB.status()


# ---- the Wikidata item cache ----------------------------------------------------- #


@router.get("/items/pending")
def items_pending(db: Session = Depends(get_db)) -> dict:
    """What a fetch WOULD ask for -- computed locally, with NO network call (see #14e)."""
    from src.catalog.cities import gazetteer_meta
    from src.entities.items import pending_summary

    out = pending_summary(db)
    out["gazetteer"] = gazetteer_meta()
    return out


class _FetchBody(BaseModel):
    consent: bool = False
    limit: int = 500


@router.post("/items/fetch")
def items_fetch(body: _FetchBody) -> dict:
    """Fetch the Wikidata items the corpus mentions (Q724), at one request per 10 seconds (R8).

    EGRESSES to ``www.wikidata.org``. Refuses under airplane mode with a 409 that names it,
    and without ``consent: true`` with a 400 -- see the module docstring.
    """
    from src.ingest import kill_switch_active

    if kill_switch_active():
        raise HTTPException(status_code=409, detail="network refused: airplane mode is engaged")
    if not body.consent:
        raise HTTPException(
            status_code=400,
            detail="consent required: this sends requests to www.wikidata.org",
        )
    limit = max(1, min(5000, int(body.limit or 500)))
    try:
        return {"started": True, "job": _ITEMS_JOB.start(limit=limit)}
    except RuntimeError:
        return {"started": False, "job": _ITEMS_JOB.status()}


@router.get("/items/status")
def items_status() -> dict:
    return _ITEMS_JOB.status()


@router.get("/items/{qid}")
def item(qid: str, db: Session = Depends(get_db)) -> dict:
    """One cached item, or a 404 that says this machine has not read it."""
    from src.entities.items import cached_item, item_payload
    from src.entities.wikidata_items import is_qid

    if not is_qid(qid):
        raise HTTPException(status_code=400, detail="not a Wikidata id")
    out = item_payload(cached_item(db, qid))
    if out is None:
        raise HTTPException(status_code=404, detail="not fetched on this machine")
    return out


# ---- the ladder (Q415) ----------------------------------------------------------- #


@router.get("/resolve")
def resolve(
    term: str = Query(..., min_length=1, max_length=200),
    target_lang: str = Query("en", max_length=16),
    language: str | None = Query(None, max_length=16),
    db: Session = Depends(get_db),
) -> dict:
    """One entity name on the ladder: its QID (or why none), its label in ``target_lang``."""
    from src.entities.spine import resolve_entity

    out = resolve_entity(term, target_lang, language=language, session=db).to_dict()
    out["term"] = term
    return out
