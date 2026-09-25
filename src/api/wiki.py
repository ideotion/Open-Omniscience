"""
Wikipedia change-tracking API.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Manage a per-language watchlist, trigger tracking, and read the flagged-edit feed
+ revision detail (diffs). Tracking flows through the same ethical MediaWiki
client (UA + maxlag + rate limit); ORES scores are optional and fail-open.
"""

from __future__ import annotations

import logging
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

_LOG = logging.getLogger("api.wiki")

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
    counts: dict[int, int] = {
        page_id: n
        for page_id, n in db.query(WikiRevision.page_id, func.count(WikiRevision.id))
        .group_by(WikiRevision.page_id)
        .all()
    }
    flagged: dict[int, int] = {
        page_id: n
        for page_id, n in db.query(WikiRevision.page_id, func.count(WikiRevision.id))
        .filter_by(flagged=True)
        .group_by(WikiRevision.page_id)
        .all()
    }
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
    wiki = _validated_wiki(wiki)
    page = ensure_page(db, wiki, title, category=payload.category)
    out = _serialize_page(page)
    out["pinned_to_hot"] = _pin_to_hot(wiki, title, page.pageid)
    return out


def _pin_to_hot(wiki: str, title: str, page_id: int | None) -> dict:
    """Q716 = a: this endpoint "survives as 'pin this page to HOT'".

    The operator asking for a page BY HAND is the strongest HOT reason there is
    (``HOT_REASONS`` lists it first), and it is the only one a rule may never set for
    them. So the pin is written on the LANE entity, which is what the tier reads --
    adding a row to the legacy watch list alone would leave the lane following nothing
    new and the operator wondering why their page never arrived.

    IT IS KEYED BY TITLE WHEN THE PAGE ID IS UNKNOWN, WHICH IS THE ORDINARY CASE HERE:
    nothing has fetched this page yet, so ``WikiPage.pageid`` is NULL, and asking the
    wiki for it would be a network call inside an endpoint the operator did not consent
    to egress from. The legacy title form exists for exactly this, and the stream's own
    reconciliation upgrades the row to Q715's ``(wiki, pageid)`` identity the first time
    an event names both -- no migration, no guess.

    DEGRADES, never 500s: a corpus with no lane file yet is the ordinary state on a
    fresh install, and refusing to add a watched page because of it would be the tail
    wagging the dog. The result says what happened either way.
    """
    from src.versioned.store import LaneAbsentError
    from src.wiki.identity import external_id_for, legacy_external_id_for

    external_id = (
        external_id_for(wiki, page_id)
        if page_id is not None and page_id > 0
        else legacy_external_id_for(wiki, title)
    )
    try:
        from src.versioned.pipeline import ensure_entity
        from src.wiki.service import wiki_lane_session

        with wiki_lane_session() as lane:
            ensure_entity(
                lane,
                external_id,
                title=title,
                language=wiki,
                pinned=True,
                admitted_reason="pinned",
            )
        return {"ok": True, "external_id": external_id}
    except LaneAbsentError:
        # THE EXCEPTION'S OWN WORDS DO NOT TRAVEL IN THE RESPONSE (CodeQL, and it is
        # right). ``LaneAbsentError`` names the database FILE; a generic failure carries
        # whatever the driver put in its message -- a path, a SQL fragment, an internal.
        # This app is loopback-only, so the reader is the operator themselves, and that
        # is still not a reason to hand internals to a surface: the response carries the
        # TOKEN the UI translates (the shape every other field in this slice already
        # uses) plus a fixed explanation, and the exception goes to the log, where an
        # operator debugging can find it and a page rendering it cannot.
        _LOG.info("the wiki lane has no database file yet; %s was not pinned", external_id)
        return {
            "ok": False,
            "reason": "lane_absent",
            "detail": "the Wikipedia lane has not been started on this machine yet",
        }
    except Exception:  # noqa: BLE001 - a watched page must still be added
        _LOG.warning("could not pin %s to the HOT tier", external_id, exc_info=True)
        return {
            "ok": False,
            "reason": "pin_failed",
            "detail": "the page was added to your watch list but could not be pinned; see the log",
        }


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


@router.get("/pages/{page_id}/revisions")
def page_revisions(
    page_id: int,
    limit: int = Query(50, ge=1, le=500),
    flagged_only: bool = False,
    include_diff: bool = True,
    db: Session = Depends(get_db),
) -> dict:
    """The tracked-changes feed for ONE page: its stored revisions (newest first) with
    per-revision diffs — the honest history the reader scrolls.

    Reads the stored ``WikiRevision`` rows for the page (index ``ix_wikirev_page_time``),
    bounded by ``limit`` with ``total`` disclosing the full count so the UI can say it is
    a window. Each revision carries its metadata plus, when ``include_diff`` (default), the
    STORED ``diff`` — the compact ``+added / -removed`` summary captured when the edit was
    tracked (truncated per side at capture, so it is not a live re-diff). ``has_full_text``
    flags revisions whose exact text is stored locally (materializable via
    ``/api/wiki/revisions/{rev_id}``). DEDUCED, VERSIONED facts: a revision without a
    stored diff had no parent or was tracked without diffs, and the list is the tracked
    slice, not necessarily every historical revision. Counts only, no score, no network.
    """
    page = db.query(WikiPage).filter_by(id=page_id).first()
    if page is None:
        raise HTTPException(status_code=404, detail=f"Watched page {page_id} not found.")

    base = db.query(WikiRevision).filter(WikiRevision.page_id == page_id)
    scoped = base.filter(WikiRevision.flagged.is_(True)) if flagged_only else base
    total = scoped.with_entities(func.count(WikiRevision.id)).scalar() or 0
    flagged_total = (
        base.filter(WikiRevision.flagged.is_(True))
        .with_entities(func.count(WikiRevision.id))
        .scalar()
        or 0
    )
    rows = (
        scoped.order_by(WikiRevision.timestamp.desc(), WikiRevision.id.desc()).limit(limit).all()
    )

    revisions = []
    for r in rows:
        item = _serialize_rev(r, page=page)
        item["size"] = r.size
        item["has_full_text"] = bool(r.full_text)
        if include_diff:
            item["diff"] = r.diff or ""
        revisions.append(item)

    return {
        "page": _serialize_page(page, revs=int(total), flagged=int(flagged_total)),
        "count": len(revisions),
        "total": int(total),
        "flagged_only": flagged_only,
        "revisions": revisions,
        "method": (
            "Stored tracked revisions for this page, newest first. Each 'diff' is the "
            "compact +added/-removed summary recorded when the edit was tracked (truncated "
            "per side), not a live re-diff; a revision without a stored diff had no parent "
            "or was tracked without diffs. Deduced from tracked edits, versioned; counts "
            "only, no score."
        ),
    }


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
    """Read the CURRENT published dump size for ONE edition.

    Goes through the same ``probe_sizes`` batch path ``/dumps/sizes`` uses
    (via ``get_manager().probe_sizes(...)``) rather than the size-only
    ``probe_size()``, so a refusal is reported with its NAMED reason --
    ``airplane`` (the kill switch refused it: nothing left this machine),
    ``unreachable`` or ``no-content-length`` -- instead of collapsing all
    three into an unexplained ``size_bytes: null`` (invariant #14e).
    """
    from src.wiki.dumps import get_manager

    wiki = _validated_wiki(wiki)
    (reading,) = get_manager().probe_sizes([wiki], kind, max_editions=1)
    return reading.to_dict()


@router.get("/dumps/sizes")
def dumps_sizes(
    wikis: str,
    kind: str = "pages-articles-multistream",
) -> dict:
    """Read the CURRENT published dump size for SEVERAL editions, in ONE action.

    A plain ``def`` on purpose: this makes bounded, politeness-spaced network
    calls, and a blocking body inside an ``async def`` would freeze the single
    event loop for the whole batch. Starlette runs a ``def`` route in the
    threadpool.

    ``wikis`` is a comma-separated list of edition codes; the batch is bounded
    (``MAX_SIZE_PROBE_EDITIONS``) and the surplus is REPORTED rather than
    silently dropped, so a caller can never read a short answer as a complete
    one. Each reading is one HEAD against the same ``latest`` URL the download
    itself fetches, so the figure and the download agree by construction.

    An edition whose size could not be read carries ``size_bytes: null`` and a
    NAMED ``reason`` -- ``airplane`` (the kill switch refused it: nothing left
    this machine), ``unreachable``, ``no-content-length`` or ``invalid-edition``
    -- never a 0 and never an omission, because "we could not read it" and "it
    is empty" are opposite facts.
    """
    from src.wiki.dumps import MAX_SIZE_PROBE_EDITIONS, get_manager

    requested: list[str] = []
    for raw in (wikis or "").split(","):
        code = raw.strip().lower()
        if code and code not in requested:
            requested.append(code)
    if not requested:
        raise HTTPException(status_code=400, detail="no edition codes given")
    # Validate BEFORE the manager so a traversal-shaped code is a 400 here, the
    # same refusal /dumps/probe already makes, rather than a per-row reason.
    for code in requested:
        _validated_wiki(code)

    granted = requested[:MAX_SIZE_PROBE_EDITIONS]
    readings = get_manager().probe_sizes(granted, kind)
    return {
        "kind": kind,
        "requested": len(requested),
        "probed": len(readings),
        # A cap may bound which editions were read; it may NEVER be published as
        # though it were the whole request (anti-capping).
        "not_probed": requested[MAX_SIZE_PROBE_EDITIONS:],
        "max_editions": MAX_SIZE_PROBE_EDITIONS,
        "sizes": [r.to_dict() for r in readings],
        "method": (
            "One HTTP HEAD per edition against the same 'latest' dump URL the "
            "download fetches, spaced by the per-host politeness interval. The "
            "figure is the size the dump host publishes right now; an edition "
            "that could not be read reports a named reason, never a zero."
        ),
    }


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

    A READABLE rendition rides alongside the raw wikitext, and it is a STRIP
    rather than a render -- the distinction is the whole reason it is named this
    way. ``plain_from_wikitext`` is the corpus pipeline's own reducer, reused
    here rather than reimplemented, and its docstring says what it is for:
    "keyword/WWW-quality text, not rendering fidelity". It PEELS templates,
    DROPS refs, comments, tables and file links, and keeps link labels. So an
    infobox does not become a table -- it disappears, and a reader who was told
    "rendered" would believe the page never had one. ``plain_method`` states
    that in the payload, so the caveat travels with the text rather than living
    only in whichever UI happens to draw it. True rendering (templates
    evaluated, tables laid out) remains open in the docket.
    """
    from src.wiki.corpus import plain_from_wikitext
    from src.wiki.dumpread import find_page

    if not title.strip():
        raise HTTPException(status_code=400, detail="wiki and title are required.")
    res = find_page(_validated_wiki(wiki), title.strip())
    raw = res.get("wikitext") if isinstance(res, dict) else None
    if raw:
        res["plain"] = plain_from_wikitext(raw)
        res["plain_method"] = (
            "Lexical strip, not a render: templates and infoboxes are peeled away, "
            "references, comments, tables and file links are removed, and link "
            "labels are kept. Anything a template would have produced is absent "
            "rather than rendered."
        )
    return res


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

# RETIRED 2026-09-17 (Q728 = a): the dump-to-corpus POST route.
#
# The ruling reads: "the dump machinery stays (it is built and tested) as an opt-in
# offline reader, never the tracking path; the dump->corpus endpoint is retired."
# Those are two different things and only the second one goes. A dump is a SNAPSHOT as
# of its build date, so an article ingested from one enters the corpus carrying that
# date's text with nothing to say it has since changed -- which is exactly the claim
# the live lane exists to avoid making. The stream now supplies changed pages with
# their revision, so a second, staler path into the corpus is not a fallback; it is a
# way for two surfaces to disagree about what a Wikipedia article says.
#
# WHAT SURVIVES, deliberately: ``src.wiki.corpus.ingest_dump_pages`` itself, the
# downloader, the multistream index, and the read routes below and above -- the
# offline reader is the whole point of the ruling's first clause, and it is the
# FUNCTION an operator with a dump on disk uses, not this route.
#
# ``tests/test_wiki_dump_endpoint_retired.py`` pins BOTH halves: the route's absence
# against this router's OWN definitions (never the shared ``app.routes`` singleton,
# per the recorded rule about process-global route reads), and the reader's presence,
# because a test asserting only the absence would be satisfied by deleting the whole
# dump subsystem that the same ruling keeps.

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
