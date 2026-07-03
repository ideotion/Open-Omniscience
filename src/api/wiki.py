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


def _validated_wiki(wiki: str) -> str:
    """Validate a Wikipedia edition code at the API boundary (path-traversal guard).

    A dump ``wiki`` code flows into a filesystem path and a fetch URL, so reject
    anything unsafe with a clean HTTP 400 instead of letting it reach disk.
    """
    from src.wiki.dumps import validate_wiki_code

    try:
        return validate_wiki_code(wiki)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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

    Returns ONE flat ``languages`` list ordered UI-locales-first then
    largest-edition-first. The by-continent ``groups`` were DROPPED (UI invariant
    #1, amended 2026-06-16): editions are language-based, not continent-based, so
    a continent split is a category error — the picker renders a flat list.

    ``scope="dumps"`` limits the list to THE APP'S LANGUAGES (maintainer-ruled
    2026-06-12): the UI locales + evidence-backed corpus languages. Only the
    heavy dump surface narrows — the watched-pages picker (invariant #1) keeps
    the full list via the default scope.
    """
    from src.wiki.languages import app_languages_ui_first, languages_ui_first

    if scope == "dumps":
        # Enrich each edition with a bundled, dated size ESTIMATE so the picker
        # shows sizes inline & instantly — no per-edition network probe (zero-
        # network boot / airplane mode stay intact). Exact size is read on download.
        from src.wiki.dump_sizes import DUMP_SIZES_AS_OF, estimate_bytes

        return {
            "scope": scope,
            "languages": [
                {**lang.to_dict(), "size_estimate_bytes": estimate_bytes(lang.code)}
                for lang in app_languages_ui_first()
            ],
            "size_estimate_as_of": DUMP_SIZES_AS_OF,
        }
    return {
        "scope": scope,
        "languages": [lang.to_dict() for lang in languages_ui_first()],
    }


@router.get("/dumps")
def dumps_list() -> dict:
    from src.wiki.dumps import get_manager

    return {"downloads": get_manager().list()}


@router.get("/dumps/probe")
def dumps_probe(wiki: str, kind: str = "pages-articles-multistream") -> dict:
    from src.wiki.dumps import dump_url, get_manager

    wiki = _validated_wiki(wiki)
    size = get_manager().probe_size(wiki, kind)
    return {"wiki": wiki, "kind": kind, "url": dump_url(wiki, kind), "size_bytes": size}


@router.post("/dumps/start")
def dumps_start(payload: StartDump) -> dict:
    from src.wiki.dumps import get_manager

    wiki = _validated_wiki(payload.wiki)
    try:
        result = get_manager().start(wiki, payload.kind)
        if payload.kind == "pages-articles-multistream":
            # The tiny companion index rides along automatically — it is what
            # makes the downloaded dump READABLE (seekable) offline.
            get_manager().start(wiki, "pages-articles-multistream-index")
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

    if not title.strip():
        raise HTTPException(status_code=400, detail="wiki and title are required.")
    return find_page(_validated_wiki(wiki), title.strip())


@router.get("/dumps/search")
def dumps_search(wiki: str, q: str, limit: int = 20) -> dict:
    """Substring TITLE search over a downloaded edition's multistream index — local,
    no network. Honest scope: titles only (page bodies are not full-text-searched;
    decompressing every block per query is out of scope). Each hit opens via the
    local dump reader (/dumps/page)."""
    from src.wiki.dumpread import search_titles

    if not q.strip():
        raise HTTPException(status_code=400, detail="wiki and q are required.")
    return search_titles(_validated_wiki(wiki), q.strip(), limit=max(1, min(limit, 100)))


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

    wiki = _validated_wiki(payload.wiki)
    titles = [t.strip() for t in (payload.titles or []) if t and t.strip()]
    if not titles:
        raise HTTPException(
            status_code=400, detail="wiki and a non-empty titles list are required."
        )
    return ingest_dump_pages(db, wiki, titles)


@router.get("/dumps/fts-search")
def dumps_fts_search(q: str, wiki: str | None = None, limit: int = 20) -> dict:
    """Full-text search over the BODIES of indexed downloaded dumps — local, no network.

    Unlike ``/dumps/search`` (titles only), this searches page content that a prior
    ``/dumps/index`` build indexed, with the same Boolean syntax + BM25F ranking as
    article search. Each hit opens via the local dump reader (``/dumps/page``). An
    edition must be indexed first (``/dumps/index``); an unindexed edition returns no
    items honestly (``reason: no-index``)."""
    from src.wiki.dump_index import search as dump_search

    if not q.strip():
        raise HTTPException(status_code=400, detail="q is required.")
    return dump_search(
        q.strip(), wiki=_validated_wiki(wiki) if wiki else None, limit=max(1, min(limit, 100))
    )


@router.get("/dumps/index")
def dumps_index_status() -> dict:
    """Which downloaded editions have a full-text index, page counts, and build state."""
    from src.wiki.dump_index import get_manager

    return get_manager().status()


class BuildDumpIndex(BaseModel):
    wiki: str


@router.post("/dumps/index")
def dumps_index_build(payload: BuildDumpIndex) -> dict:
    """Build (or rebuild) the full-text index for ONE downloaded edition — local, no
    network. Runs on a background worker so the request never blocks on the sweep;
    poll ``GET /dumps/index`` for progress. 409 if a build is already running, 404 if
    the edition's multistream dump is not downloaded."""
    from src.wiki.dump_index import get_manager
    from src.wiki.dumpread import readable_wikis

    wiki = _validated_wiki(payload.wiki)
    if wiki not in readable_wikis():
        raise HTTPException(
            status_code=404,
            detail=f"no downloaded multistream dump for {wiki!r} to index.",
        )
    try:
        return get_manager().start(wiki)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/dumps/index/cancel")
def dumps_index_cancel() -> dict:
    """Cancel an in-progress dump-index build (its partial rows stay searchable but the
    edition is not marked complete)."""
    from src.wiki.dump_index import get_manager

    return get_manager().cancel()


@router.delete("/dumps/index")
def dumps_index_clear(wiki: str | None = None) -> dict:
    """Drop the full-text index for one edition (or all editions when ``wiki`` is
    omitted) — it is rebuildable from the local dump at any time."""
    from src.wiki.dump_index import clear_index

    return clear_index(_validated_wiki(wiki) if wiki else None)


@router.get("/revisions/{rev_id}")
def revision_detail(rev_id: int, db: Session = Depends(get_db)) -> dict:
    r = db.query(WikiRevision).filter_by(id=rev_id).first()
    if r is None:
        raise HTTPException(status_code=404, detail=f"Revision row {rev_id} not found.")
    page = db.query(WikiPage).filter_by(id=r.page_id).first()
    out = _serialize_rev(r, page=page)
    out["diff"] = r.diff or ""
    return out
