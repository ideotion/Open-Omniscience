"""
Wikipedia change-tracking API.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Manage a per-language watchlist, trigger tracking, and read the flagged-edit feed
+ revision detail (diffs). Tracking flows through the same ethical MediaWiki
client (UA + maxlag + rate limit); ORES scores are optional and fail-open.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.database.models import WikiPage, WikiRevision
from src.database.session import get_db
from src.wiki.client import WikiClient
from src.wiki.ores import OresClient

router = APIRouter(prefix="/api/wiki", tags=["wikipedia"])

# Shared clients (network); injectable/monkeypatchable in tests.
_client = WikiClient()
_ores = OresClient()


class AddPage(BaseModel):
    wiki: str
    title: str
    category: str | None = None


def _live_diff_url(wiki: str, revid: int) -> str:
    return f"https://{wiki}.wikipedia.org/w/index.php?diff={revid}"


def _serialize_page(p: WikiPage, *, revs: int = 0, flagged: int = 0) -> dict:
    return {
        "id": p.id, "wiki": p.wiki, "title": p.title, "category": p.category,
        "watched": p.watched, "baseline_revid": p.baseline_revid, "last_revid": p.last_revid,
        "last_checked_at": p.last_checked_at.isoformat() if p.last_checked_at else None,
        "revisions": revs, "flagged": flagged,
    }


def _serialize_rev(r: WikiRevision, *, page: WikiPage | None = None) -> dict:
    return {
        "id": r.id, "revid": r.revid, "parent_revid": r.parent_revid,
        "wiki": page.wiki if page else None, "title": page.title if page else None,
        "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        "editor": r.editor, "editor_anon": r.editor_anon, "comment": r.comment,
        "delta_bytes": r.delta_bytes, "tags": r.tags, "minor": r.minor, "bot": r.bot,
        "ores_damaging": r.ores_damaging, "ores_goodfaith": r.ores_goodfaith,
        "flagged": r.flagged, "flag_reasons": (r.flag_reasons or "").split(",") if r.flag_reasons else [],
        "diff_url": _live_diff_url(page.wiki, r.revid) if page else None,
    }


@router.get("/status")
def wiki_status(db: Session = Depends(get_db)) -> dict:
    return {
        "pages": db.query(func.count(WikiPage.id)).scalar() or 0,
        "watched": db.query(func.count(WikiPage.id)).filter_by(watched=True).scalar() or 0,
        "revisions": db.query(func.count(WikiRevision.id)).scalar() or 0,
        "flagged": db.query(func.count(WikiRevision.id)).filter_by(flagged=True).scalar() or 0,
    }


@router.get("/pages")
def list_pages(db: Session = Depends(get_db)) -> dict:
    counts = dict(
        db.query(WikiRevision.page_id, func.count(WikiRevision.id)).group_by(WikiRevision.page_id).all()
    )
    flagged = dict(
        db.query(WikiRevision.page_id, func.count(WikiRevision.id))
        .filter_by(flagged=True).group_by(WikiRevision.page_id).all()
    )
    pages = db.query(WikiPage).order_by(WikiPage.wiki, WikiPage.title).all()
    return {"count": len(pages),
            "pages": [_serialize_page(p, revs=counts.get(p.id, 0), flagged=flagged.get(p.id, 0)) for p in pages]}


@router.post("/pages")
def add_page(payload: AddPage, db: Session = Depends(get_db)) -> dict:
    from src.wiki.track import ensure_page

    if not payload.wiki.strip() or not payload.title.strip():
        raise HTTPException(status_code=400, detail="wiki and title are required.")
    page = ensure_page(db, payload.wiki, payload.title, category=payload.category)
    return _serialize_page(page)


@router.delete("/pages/{page_id}")
def delete_page(page_id: int, db: Session = Depends(get_db)) -> dict:
    page = db.query(WikiPage).filter_by(id=page_id).first()
    if page is None:
        raise HTTPException(status_code=404, detail=f"Page {page_id} not found.")
    db.delete(page)
    db.commit()
    return {"deleted": page_id}


@router.post("/pages/{page_id}/track")
def track_page(page_id: int, ores: bool = True, db: Session = Depends(get_db)) -> dict:
    from src.wiki.track import update_page

    page = db.query(WikiPage).filter_by(id=page_id).first()
    if page is None:
        raise HTTPException(status_code=404, detail=f"Page {page_id} not found.")
    return update_page(db, _client, page, ores_client=_ores if ores else None)


@router.post("/track-now")
def track_now(ores: bool = True, limit: int = Query(25, ge=1, le=500),
              db: Session = Depends(get_db)) -> dict:
    """Track all watched pages now (synchronous; for a handful of pages)."""
    from src.wiki.track import track_watched

    return track_watched(db, _client, ores_client=_ores if ores else None, limit_pages=limit)


@router.get("/changes")
def changes(
    flagged_only: bool = True,
    wiki: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    """Recent tracked edits (flagged by default), newest first."""
    q = db.query(WikiRevision, WikiPage).join(WikiPage, WikiPage.id == WikiRevision.page_id)
    if flagged_only:
        q = q.filter(WikiRevision.flagged.is_(True))
    if wiki:
        q = q.filter(WikiPage.wiki == wiki.lower())
    rows = q.order_by(WikiRevision.timestamp.desc(), WikiRevision.id.desc()).limit(limit).all()
    return {"count": len(rows), "changes": [_serialize_rev(r, page=p) for r, p in rows]}


# ----------------------------- offline dumps -------------------------------- #
# Separate, optional, heavy: per-language baseline downloads (resumable).


class StartDump(BaseModel):
    wiki: str
    kind: str = "pages-articles"


@router.get("/dumps")
def dumps_list() -> dict:
    from src.wiki.dumps import get_manager

    return {"downloads": get_manager().list()}


@router.get("/dumps/probe")
def dumps_probe(wiki: str, kind: str = "pages-articles") -> dict:
    from src.wiki.dumps import dump_url, get_manager

    size = get_manager().probe_size(wiki, kind)
    return {"wiki": wiki.lower(), "kind": kind, "url": dump_url(wiki, kind), "size_bytes": size}


@router.post("/dumps/start")
def dumps_start(payload: StartDump) -> dict:
    from src.wiki.dumps import get_manager

    if not payload.wiki.strip():
        raise HTTPException(status_code=400, detail="wiki is required.")
    try:
        return get_manager().start(payload.wiki, payload.kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/dumps/pause")
def dumps_pause(key: str) -> dict:
    from src.wiki.dumps import get_manager

    return {"paused": get_manager().pause(key)}


@router.delete("/dumps")
def dumps_delete(key: str) -> dict:
    from src.wiki.dumps import get_manager

    return {"deleted": get_manager().delete(key)}


@router.get("/revisions/{rev_id}")
def revision_detail(rev_id: int, db: Session = Depends(get_db)) -> dict:
    r = db.query(WikiRevision).filter_by(id=rev_id).first()
    if r is None:
        raise HTTPException(status_code=404, detail=f"Revision row {rev_id} not found.")
    page = db.query(WikiPage).filter_by(id=r.page_id).first()
    out = _serialize_rev(r, page=page)
    out["diff"] = r.diff or ""
    return out
