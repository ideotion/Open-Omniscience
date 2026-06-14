"""
Wikipedia change-tracking API.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Manage a per-language watchlist, trigger tracking, and read the flagged-edit feed
+ revision detail (diffs). Tracking flows through the same ethical MediaWiki
client (UA + maxlag + rate limit); ORES scores are optional and fail-open.
"""

from __future__ import annotations

import re
from urllib.parse import unquote

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
    import json as _json

    try:
        wiki_cats = _json.loads(p.wiki_categories) if p.wiki_categories else []
    except ValueError:
        wiki_cats = []
    return {
        "id": p.id,
        "wiki": p.wiki,
        "title": p.title,
        "category": p.category,
        "watched": p.watched,
        "missing": p.missing,
        "wiki_categories": wiki_cats,
        "baseline_revid": p.baseline_revid,
        "last_revid": p.last_revid,
        "last_checked_at": p.last_checked_at.isoformat() if p.last_checked_at else None,
        "revisions": revs,
        "flagged": flagged,
    }


# Accept a full Wikipedia URL in the title box (live-test ask 2026-06-10):
# https://de.wikipedia.org/wiki/Grundgesetz or de.m.wikipedia.org/wiki/...
# -> (wiki='de', title='Grundgesetz'). Pure parsing, no network.
_WIKI_URL_RE = re.compile(
    r"^(?:https?://)?([a-z][a-z0-9-]{1,11})(?:\.m)?\.wikipedia\.org/wiki/([^?#]+)",
    re.IGNORECASE,
)


def _parse_title_or_url(wiki: str, title: str) -> tuple[str, str]:
    m = _WIKI_URL_RE.match(title.strip())
    if m:
        return m.group(1).lower(), unquote(m.group(2)).replace("_", " ").strip()
    return wiki.strip(), title.strip()


def _serialize_rev(r: WikiRevision, *, page: WikiPage | None = None) -> dict:
    return {
        "id": r.id,
        "revid": r.revid,
        "parent_revid": r.parent_revid,
        "wiki": page.wiki if page else None,
        "title": page.title if page else None,
        "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        "editor": r.editor,
        "editor_anon": r.editor_anon,
        "comment": r.comment,
        "delta_bytes": r.delta_bytes,
        "tags": r.tags,
        "minor": r.minor,
        "bot": r.bot,
        "ores_damaging": r.ores_damaging,
        "ores_goodfaith": r.ores_goodfaith,
        "flagged": r.flagged,
        "flag_reasons": (r.flag_reasons or "").split(",") if r.flag_reasons else [],
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
        db.query(WikiRevision.page_id, func.count(WikiRevision.id))
        .group_by(WikiRevision.page_id)
        .all()
    )
    flagged = dict(
        db.query(WikiRevision.page_id, func.count(WikiRevision.id))
        .filter_by(flagged=True)
        .group_by(WikiRevision.page_id)
        .all()
    )
    pages = db.query(WikiPage).order_by(WikiPage.wiki, WikiPage.title).all()
    return {
        "count": len(pages),
        "pages": [
            _serialize_page(p, revs=counts.get(p.id, 0), flagged=flagged.get(p.id, 0))
            for p in pages
        ],
    }


@router.post("/pages")
def add_page(payload: AddPage, db: Session = Depends(get_db)) -> dict:
    from src.wiki.track import ensure_page

    wiki, title = _parse_title_or_url(payload.wiki, payload.title)
    if not title:
        raise HTTPException(status_code=400, detail="wiki and title are required.")
    if not wiki:
        raise HTTPException(
            status_code=400,
            detail="wiki is required (or paste a full Wikipedia URL as the title).",
        )
    page = ensure_page(db, wiki, title, category=payload.category)
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
    try:
        return update_page(db, _client, page, ores_client=_ores if ores else None)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - a MediaWiki fetch/parse failure is a 502, not a crash
        db.rollback()
        raise HTTPException(
            status_code=502,
            detail=f"Could not track '{page.title}': {type(exc).__name__}: {exc}",
        ) from exc


@router.post("/track-now")
def track_now(
    ores: bool = True, limit: int = Query(25, ge=1, le=500), db: Session = Depends(get_db)
) -> dict:
    """Track all watched pages now (synchronous; for a handful of pages)."""
    from src.wiki.track import track_watched

    try:
        return track_watched(db, _client, ores_client=_ores if ores else None, limit_pages=limit)
    except Exception as exc:  # noqa: BLE001 - never 500 the batch on one bad fetch
        db.rollback()
        raise HTTPException(
            status_code=502, detail=f"Tracking failed: {type(exc).__name__}: {exc}"
        ) from exc


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
    # Multistream is the default (T14): its companion index makes downloaded
    # dumps READABLE offline; the index file is queued automatically with it.
    kind: str = "pages-articles-multistream"


@router.get("/languages")
def wiki_languages(scope: str = "all") -> dict:
    """Curated Wikipedia editions for the offline-baseline picker.

    Returns both a flat ``languages`` list (largest tier first; each entry now
    carries its continent of origin in ``region``) and a ``groups`` list that
    splits the editions by continent — regions ordered largest-edition-first —
    so the UI can render short, scannable ``<optgroup>`` sections instead of one
    long scroll.

    ``scope="dumps"`` limits the list to THE APP'S LANGUAGES (maintainer-ruled
    2026-06-12): the UI locales + evidence-backed corpus languages. Only the
    heavy dump surface narrows — the watched-pages picker (invariant #1) keeps
    the full list via the default scope.
    """
    from src.wiki.languages import (
        all_languages,
        app_languages,
        app_languages_by_region,
        languages_by_region,
    )

    if scope == "dumps":
        flat, grouped = app_languages(), app_languages_by_region()
    else:
        flat, grouped = all_languages(), languages_by_region()
    return {
        "scope": scope,
        "languages": [lang.to_dict() for lang in flat],
        "groups": [
            {"region": region, "languages": [lang.to_dict() for lang in langs]}
            for region, langs in grouped
        ],
    }


@router.get("/dumps")
def dumps_list() -> dict:
    from src.wiki.dumps import get_manager

    return {"downloads": get_manager().list()}


@router.get("/dumps/probe")
def dumps_probe(wiki: str, kind: str = "pages-articles-multistream") -> dict:
    from src.wiki.dumps import dump_url, get_manager

    size = get_manager().probe_size(wiki, kind)
    return {"wiki": wiki.lower(), "kind": kind, "url": dump_url(wiki, kind), "size_bytes": size}


@router.post("/dumps/start")
def dumps_start(payload: StartDump) -> dict:
    from src.wiki.dumps import get_manager

    if not payload.wiki.strip():
        raise HTTPException(status_code=400, detail="wiki is required.")
    try:
        result = get_manager().start(payload.wiki, payload.kind)
        if payload.kind == "pages-articles-multistream":
            # The tiny companion index rides along automatically — it is what
            # makes the downloaded dump READABLE (seekable) offline.
            get_manager().start(payload.wiki, "pages-articles-multistream-index")
            result["index_queued"] = True
        return result
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


@router.post("/corpus/sync")
def corpus_sync(db: Session = Depends(get_db)) -> dict:
    """Backfill: every watched page's stored text enters the corpus as an
    article (keywords + When x Where x Who via the one index hook). LOCAL
    ONLY — this reads text already on disk and never touches the network;
    new revisions sync automatically when the tracker runs."""
    from src.wiki.corpus import sync_watched

    return sync_watched(db)


@router.get("/dumps/readable")
def dumps_readable() -> dict:
    """Editions whose multistream data+index pair is on disk (reader-ready)."""
    from src.wiki.dumpread import readable_wikis

    return {"wikis": readable_wikis()}


@router.get("/dumps/page")
def dumps_page(wiki: str, title: str) -> dict:
    """Read ONE page out of a downloaded multistream dump — local, no network.

    The result is always honest about what happened: found (with raw
    wikitext + match kind + scan stats), not in the index, or not readable
    because only a legacy single-stream file exists (re-download hint).
    """
    from src.wiki.dumpread import find_page

    if not wiki.strip() or not title.strip():
        raise HTTPException(status_code=400, detail="wiki and title are required.")
    return find_page(wiki.strip(), title.strip())


class IngestDumpPages(BaseModel):
    wiki: str
    titles: list[str]


@router.post("/dumps/corpus-ingest")
def dumps_corpus_ingest(payload: IngestDumpPages, db: Session = Depends(get_db)) -> dict:
    """Ingest a bounded list of titles FROM a downloaded dump into the corpus.

    LOCAL ONLY — reads the local multistream dump, never the network. Each page
    becomes a corpus article (a snapshot as of the dump date) through the one
    ``index_article`` hook (keywords + When×Where×Who), keyed on the canonical
    wiki URL so a later live sync of the same page updates the SAME row (no
    duplicate). The title list is operator-chosen — a full edition is millions of
    pages, so whole-dump streaming is a future slice.
    """
    from src.wiki.corpus import ingest_dump_pages

    wiki = (payload.wiki or "").strip()
    titles = [t.strip() for t in (payload.titles or []) if t and t.strip()]
    if not wiki or not titles:
        raise HTTPException(
            status_code=400, detail="wiki and a non-empty titles list are required."
        )
    return ingest_dump_pages(db, wiki, titles)


@router.get("/revisions/{rev_id}")
def revision_detail(rev_id: int, db: Session = Depends(get_db)) -> dict:
    r = db.query(WikiRevision).filter_by(id=rev_id).first()
    if r is None:
        raise HTTPException(status_code=404, detail=f"Revision row {rev_id} not found.")
    page = db.query(WikiPage).filter_by(id=r.page_id).first()
    out = _serialize_rev(r, page=page)
    out["diff"] = r.diff or ""
    return out
