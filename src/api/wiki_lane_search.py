"""Searching the Wikipedia lane's held texts, and adding one version to the corpus (``R52``).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``R52`` («In the lane», 2026-09-28): WARM's texts stay in ``wiki.db`` with a search index of
their own, found from the one search box, and each hit can be added to the corpus as the
version it is. ``src/wiki/lane_search.py`` is the index; this is its HTTP face.

TWO READS AND ONE WRITE. ``/search`` and ``/version`` read the lane and never create it: a
lane that has never run answers with the same named absence as every other lane route
(``src/api/wiki_lane.py``). ``/add-to-corpus`` writes ONE article into the corpus, and only
when the operator clicks: the lane's texts never become corpus articles by themselves (Q719).

NOTHING HERE TOUCHES THE NETWORK. Every text these routes read is already on disk.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.database.session import get_db
from src.versioned.store import LaneAbsentError, lane_path, lane_session

_LOG = logging.getLogger("api.wiki.lane_search")

router = APIRouter(prefix="/api/wiki/lane", tags=["wikipedia"])

#: The named absences, in the shape ``src/api/wiki_lane.py`` answers them, so the two
#: surfaces cannot disagree about what "not run yet" looks like.
_NEVER_RUN = "lane-never-run"
_UNREADABLE = "lane-unreadable"
_LOCKED = "locked"


def _indexer_status() -> dict[str, Any] | None:
    """The running process's indexer state (``None`` when the lane is not running)."""
    try:
        from src.wiki.service import lane_service_status

        return lane_service_status().get("index")
    except Exception:  # noqa: BLE001 - a status read must never fail a search
        _LOG.debug("could not read the lane indexer status", exc_info=True)
        return None


def _warm_enabled() -> bool | None:
    """WARM's switch as the settings hold it, or ``None`` when they cannot be read."""
    try:
        from src.wiki.service import _warm_enabled as enabled

        return bool(enabled())
    except Exception:  # noqa: BLE001 - a settings read must never fail a search
        _LOG.debug("could not read WARM's switch", exc_info=True)
        return None


def _absent(reason: str, q: str = "") -> dict[str, Any]:
    return {"available": False, "reason": reason, "query": q, "total": None, "items": []}


def search_lane(
    q: str,
    *,
    limit: int,
    offset: int = 0,
    snippets: bool = True,
    queue: bool = True,
    coverage: bool = False,
) -> dict[str, Any]:
    """The lane search, or a named absence. Shared by the route and the omnibar's group."""
    from src.database.connect import DatabaseLockedError
    from src.wiki.lane_search import search, search_coverage

    if not lane_path("wiki").is_file():
        return _absent(_NEVER_RUN, q)
    try:
        with lane_session("wiki") as lane:
            out = search(lane, q, limit=limit, offset=offset, snippets=snippets, queue=queue)
            if coverage and out.get("available"):
                out["coverage"] = search_coverage(lane)
            return out
    except LaneAbsentError:
        return _absent(_NEVER_RUN, q)
    except DatabaseLockedError:
        return _absent(_LOCKED, q)
    except SQLAlchemyError:
        _LOG.warning("lane search: the Wikipedia lane could not be read", exc_info=True)
        return _absent(_UNREADABLE, q)


@router.get("/search")
def lane_search(
    q: str = Query("", max_length=500),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10_000),
) -> dict[str, Any]:
    """Held Wikipedia texts matching ``q``: changed pages' latest texts and older versions.

    ``total`` is exact; ``pending`` is how many held texts still wait to be indexed, and
    ``coverage`` which editions and how many pages the lane holds a text for, and whether
    WARM is switched on -- so a search with no hit reads as "not in what this machine holds",
    never as "Wikipedia does not say this" (``R52``).
    """
    out = search_lane(q, limit=limit, offset=offset, coverage=True)
    if "coverage" in out:
        out["coverage"]["warm_enabled"] = _warm_enabled()
    out["indexer"] = _indexer_status()
    return out


def _held(source: str, owner_id: int, revid: int):
    from src.database.connect import DatabaseLockedError
    from src.wiki.lane_search import held_version

    if not lane_path("wiki").is_file():
        raise HTTPException(status_code=404, detail=_NEVER_RUN)
    try:
        with lane_session("wiki") as lane:
            return held_version(lane, source, owner_id, revid)
    except LaneAbsentError as exc:
        raise HTTPException(status_code=404, detail=_NEVER_RUN) from exc
    except DatabaseLockedError as exc:
        raise HTTPException(status_code=423, detail=_LOCKED) from exc
    except SQLAlchemyError as exc:
        _LOG.warning("lane version: the Wikipedia lane could not be read", exc_info=True)
        raise HTTPException(status_code=503, detail=_UNREADABLE) from exc


@router.get("/version")
def lane_version(
    source: Literal["warm", "hot"],
    owner_id: int = Query(ge=1),
    revid: int = Query(ge=1),
) -> dict[str, Any]:
    """ONE held version as plain text, for reading before adding it. 404 when not held."""
    from src.wiki.corpus import wiki_version_url
    from src.wiki.lane_search import plain_text

    held = _held(source, owner_id, revid)
    if held is None:
        raise HTTPException(status_code=404, detail="not-held")
    body = plain_text(held.text)
    return {
        "source": held.source,
        "owner_id": held.owner_id,
        "edition": held.edition,
        "page_id": held.page_id,
        "title": held.title,
        "revid": held.revid,
        "revised_at": held.revised_at.isoformat() if held.revised_at else None,
        "deleted": held.deleted,
        "newest_followed": held.newest_followed,
        "url": wiki_version_url(held.edition, held.title, held.revid),
        "text": body,
        "chars": len(body),
    }


class AddVersion(BaseModel):
    """The version a hit named: which lane row, and which revision of it."""

    source: Literal["warm", "hot"]
    owner_id: int = Field(ge=1)
    revid: int = Field(ge=1)


@router.post("/add-to-corpus")
def add_to_corpus(payload: AddVersion, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Add the held version to the corpus as its own article. Never a second copy.

    ``created`` (a new article, indexed through the one hook), ``exists`` (this version is
    already an article) or ``same_text`` (an article with these exact words is already in
    the corpus, and the answer names it). 404 when the lane does not hold that version,
    409 when it holds no title for the page (an article needs one).
    """
    from src.wiki.corpus import add_wiki_version_article
    from src.wiki.lane_search import plain_text

    held = _held(payload.source, payload.owner_id, payload.revid)
    if held is None:
        raise HTTPException(status_code=404, detail="not-held")
    if not held.title:
        raise HTTPException(status_code=409, detail="no-title")
    out = add_wiki_version_article(
        db,
        wiki=held.edition,
        title=held.title,
        plain=plain_text(held.text),
        revid=held.revid,
        published_at=held.revised_at,
    )
    out["source"] = held.source
    out["newest_followed"] = held.newest_followed
    return out
