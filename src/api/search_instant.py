"""The instant rung of the omnibar: the newest article titles that start with what is typed so far.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Reads ONLY the local titles-only prefix index (``src/database/fts_title.py``); no network, no body,
no ranking. It answers from the first typed character and it is deliberately not relevance: the
response states its order, its method and its caveat so the surface cannot present it as "best
match". The ranked, federated answer stays ``/api/search/omni`` and arrives after it.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database import fts_title
from src.database.models import Article, Source
from src.database.session import get_db
from src.jobs.background import BackgroundJob, register_job

_LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])

_ORDER = "newest-ingested"
_METHOD = (
    "prefix index over article titles only, read newest-ingested first and stopped after the first "
    "hits; the last word typed is a prefix and the earlier words are whole words"
)
_CAVEAT = (
    "newest titles that match, not the best match: no relevance ranking, body text is not searched, "
    "and 'newest' is the order articles were added here, not their publication date"
)


@router.get("/instant")
def instant(
    q: str = Query(max_length=400),
    limit: int = Query(10, ge=1, le=25),
    db: Session = Depends(get_db),
) -> dict:
    """First hits for what is typed so far (one character is enough). Cheap enough for every keystroke."""
    conn = db.connection()
    ids = fts_title.title_prefix_ids(conn, q, limit=limit + 1)
    more = len(ids) > limit
    ids = ids[:limit]
    hits: list[dict] = []
    if ids:
        rows = db.execute(
            select(Article.id, Article.title, Article.published_at, Source.name)
            .join(Source, Source.id == Article.source_id, isouter=True)
            .where(Article.id.in_(ids))
        ).all()
        by_id = {int(r[0]): r for r in rows}
        for i in ids:
            r = by_id.get(i)
            if r is not None:
                hits.append({
                    "id": i,
                    "title": r[1],
                    "published_at": r[2].isoformat() if r[2] is not None else None,
                    "source": r[3],
                })
    st = fts_title._state(conn)  # one-row read: whether the history backfill reached its end
    return {
        "q": q,
        "hits": hits,
        "more": more,
        "order": _ORDER,
        "method": _METHOD,
        "caveat": _CAVEAT,
        # False until the backfill finished: older articles may not be in the index yet, and the surface says so.
        "index_complete": bool(st and st[2]),
    }


@router.get("/instant/status")
def instant_status(db: Session = Depends(get_db)) -> dict:
    """How much of the corpus the title index covers (two counts: for a status line, not a keystroke)."""
    return fts_title.status(db.connection())


def _build_worker(ctx, *, rebuild: bool = False) -> dict:
    """Index the history in bounded steps, each in its own short transaction (the writer gate is
    taken and released per step, never held across the run). Resumable: the cursor is in the store."""
    from src.database.session import session_scope

    steps = 0
    indexed = 0
    if rebuild:
        with session_scope() as s:
            fts_title.reset(s.connection())
    while not ctx.stopping:
        with session_scope() as s:
            r = fts_title.backfill_step(s.connection())
        steps += 1
        indexed += r["indexed"]
        ctx.set_progress(done=r["cursor"], total=r["frozen_max"])
        if r["done"]:
            break
    return {"steps": steps, "indexed": indexed}


_BUILD_JOB = register_job(
    BackgroundJob(
        "title-index", "Building the instant title index", _build_worker,
        is_writer=True, cancellable=True,
    )
)


@router.post("/instant/build")
def instant_build(rebuild: bool = False) -> dict:
    """Start (or continue, from the stored cursor) the title-index backfill. ``rebuild=true`` forgets the
    index first and fills it again from the articles (the repair path). 409 when already running."""
    try:
        return _BUILD_JOB.start(rebuild=rebuild)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail="already-running") from exc


def start_build_if_incomplete() -> str:
    """Queue the backfill unless the index is already complete or a build is already running.

    Called once, after the heavy boot steps (``boot_sequence``), never at unlock itself (P0.4). The job
    works in bounded steps and takes the writer gate per step, so it yields to ingest. Returns what
    happened: ``"started"``, ``"complete"`` or ``"running"``."""
    from src.database.session import session_scope

    with session_scope() as s:
        st = fts_title._state(s.connection())
    if st is not None and st[2]:
        return "complete"
    try:
        _BUILD_JOB.start()
    except RuntimeError:
        return "running"
    return "started"
