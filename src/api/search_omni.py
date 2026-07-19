"""
The omnibar endpoint — instant, index-backed, federated search (T13 slice 1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

One query fans out over the corpus's INDEXED surfaces and returns the first
few hits per group for the command palette: articles (FTS5, relevance-
ordered), keywords (prefix on the indexed normalized term), sources, watched
Wikipedia pages and law documents (small catalog tables). Never scan-on-type:
every group is served by an index or a small bounded table, the method is
stated in the response, and per-group totals are disclosed so the display
bound never silently hides how much matched.

Mid-typing honesty: a half-typed Boolean query ("drought AND") is not an
error condition — it falls back to a quoted-phrase match instead of a 400.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.database.fts import SearchQueryError, search_ids
from src.database.models import Article, Keyword, LawDocument, Source, WikiPage
from src.database.session import get_db

_LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])

_PER_GROUP = 3  # the ruled "first THREE results"; totals are always disclosed


def _like_escape(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _articles_group(db: Session, q: str) -> dict:
    note = "FTS5 Boolean match, relevance-ordered"
    try:
        ids = search_ids(db, q)
    except SearchQueryError:
        # Half-typed operators mid-keystroke: fall back to a phrase, never 400.
        try:
            ids = search_ids(db, '"' + q.replace('"', " ") + '"')
            note = "FTS5 phrase match (the raw query was not a valid Boolean expression)"
        except SearchQueryError:
            return {"kind": "articles", "items": [], "total": 0,
                    "note": "query not searchable as typed"}
    rows = []
    if ids:
        top = ids[:_PER_GROUP]
        got = (
            db.query(Article.id, Article.title, Article.published_at)
            .filter(Article.id.in_(top))
            .all()
        )
        by_id = {r[0]: r for r in got}
        rows = [
            {
                "article_id": aid,
                "title": by_id[aid][1],
                "published_at": by_id[aid][2].isoformat() if by_id[aid][2] else None,
                "url": f"/api/articles/{aid}/view",  # the LOCAL reader first (invariant #6)
            }
            for aid in top
            if aid in by_id
        ]
    return {"kind": "articles", "items": rows, "total": len(ids), "note": note}


def _keywords_group(db: Session, q: str) -> dict:
    pat = _like_escape(q.casefold()) + "%"
    base = db.query(Keyword).filter(Keyword.normalized_term.like(pat, escape="\\"))
    total = base.count()
    rows = (
        base.order_by(Keyword.frequency.desc().nullslast(), Keyword.normalized_term)
        .limit(_PER_GROUP)
        .all()
    )
    # S3 (keyword -> super-group navigation): the omnibar shows only _PER_GROUP=3
    # rows, so this batched reverse lookup is trivially cheap (cached index, no N+1).
    from src.analytics.supergroup_index import supergroups_for_keywords

    sg_by_term = supergroups_for_keywords(db, [(k.normalized_term, k.language) for k in rows])
    items: list[dict] = []
    for k in rows:
        item: dict = {
            "term": k.term, "normalized_term": k.normalized_term,
            "frequency": k.frequency, "is_entity": bool(k.is_entity),
            "language": k.language,
        }
        hits = sg_by_term.get(k.normalized_term, [])
        if hits:
            item["supergroups"] = hits
        items.append(item)
    return {
        "kind": "keywords",
        "items": items,
        "total": total,
        "note": "prefix match on the indexed normalized term",
    }


def _sources_group(db: Session, q: str) -> dict:
    pat = "%" + _like_escape(q) + "%"
    base = db.query(Source).filter(
        or_(Source.name.ilike(pat, escape="\\"), Source.domain.ilike(pat, escape="\\"))
    )
    total = base.count()
    rows = base.order_by(Source.name).limit(_PER_GROUP).all()
    return {
        "kind": "sources",
        "items": [{"source_id": s.id, "name": s.name, "domain": s.domain} for s in rows],
        "total": total,
        "note": "name/domain contains-match over the (small) source catalog",
    }


_WIKI_DOMAIN_LIKE = "%wikipedia.org"  # the wiki corpus source convention (xx.wikipedia.org)
_WIKI_SCAN_CAP = 2000  # bound the wiki-membership scan over FTS hits (omnibar speed)


def _dump_hits(q: str) -> tuple[list[dict], bool, bool]:
    """Top BM25F matches in the user's DOWNLOADED-dump bodies (the #573-deferred
    dump-content search folded into the omnibar).

    Returns ``(items, available, more)``: ``available`` is False when no dump index has
    been built (honest empty state, never a fabricated result); ``more`` discloses that
    the dump holds additional matches beyond the ``_PER_GROUP`` shown (the omnibar's
    "how much matched is disclosed" contract — a cheap peek, one extra row fetched, since
    the dump index exposes no total). Each item is labelled a dump result (``dump: true``)
    and opens via the LOCAL dump reader (``/api/wiki/dumps/page``); the snapshot-as-of-the-
    dump-date honesty travels with it. Failures degrade to no dump results, never break
    the group.
    """
    from urllib.parse import quote

    from src.wiki.dump_index import search as dump_search

    try:
        # +1 so we can honestly disclose "more exist" without an (unavailable) full count.
        res = dump_search(q, limit=_PER_GROUP + 1)
        # A half-typed Boolean can make the dump FTS error; fall back to a quoted phrase,
        # exactly as the corpus path (search_ids) does above — never a mid-typing 400.
        if res.get("reason") == "search-error":
            res = dump_search('"' + q.replace('"', " ") + '"', limit=_PER_GROUP + 1)
    except Exception:  # noqa: BLE001 - a dump-index hiccup must never break the omnibar
        _LOG.warning("omni dump search failed for %r", q, exc_info=True)
        return [], False, False
    if res.get("reason") in ("no-index", "search-error"):
        # no-index: nothing indexed yet. search-error: even the phrase retry failed
        # (a genuinely un-FTS-able query) -> no dump results, honestly, never a fake zero.
        return [], res.get("reason") != "no-index", False
    hits = res.get("items", [])
    more = len(hits) > _PER_GROUP
    items: list[dict] = []
    for it in hits[:_PER_GROUP]:
        w = (it.get("wiki") or "").strip()
        title = it.get("title") or ""
        items.append(
            {
                "dump": True,  # labelled: a downloaded-dump body match, not a corpus article
                "wiki": w,
                "title": title,
                "pageid": it.get("pageid"),
                "snippet": it.get("snippet"),
                # the LOCAL dump reader (a wikitext snapshot as of the dump date)
                "url": f"/api/wiki/dumps/page?wiki={quote(w)}&title={quote(title)}",
            }
        )
    return items, True, more


def _wiki_group(db: Session, q: str) -> dict:
    """Wikipedia: search the wiki ARTICLE CONTENT, not only watched-page titles
    (maintainer 2026-06-21). Wiki page text (WikiPage.baseline_text) is stored
    COMPRESSED, so content search runs over the FTS-indexed corpus articles produced by
    the watched-page -> corpus sync (source domain ``xx.wikipedia.org``). When no indexed
    wiki content matches, fall back to the watched-pages title catalog (the prior
    behaviour). Downloaded offline DUMP bodies are ALSO searched (via the dump FTS index,
    when built) and returned as a labelled ``dump_items`` sub-list."""
    # 1) content hits among Wikipedia-edition articles, in FTS rank order (bounded).
    try:
        ids = search_ids(db, q)
    except SearchQueryError:
        try:
            ids = search_ids(db, '"' + q.replace('"', " ") + '"')
        except SearchQueryError:
            ids = []
    window = ids[:_WIKI_SCAN_CAP]
    content_items: list[dict] = []
    content_total = 0
    if window:
        wiki_set: set[int] = set()
        for i in range(0, len(window), 900):
            chunk = window[i : i + 900]
            for (aid,) in (
                db.query(Article.id)
                .join(Source, Article.source_id == Source.id)
                .filter(Article.id.in_(chunk), Source.domain.like(_WIKI_DOMAIN_LIKE))
                .all()
            ):
                wiki_set.add(aid)
        ranked = [a for a in window if a in wiki_set]
        content_total = len(ranked)
        top = ranked[:_PER_GROUP]
        if top:
            got = (
                db.query(Article.id, Article.title, Article.published_at, Source.domain)
                .join(Source, Article.source_id == Source.id)
                .filter(Article.id.in_(top))
                .all()
            )
            by = {r[0]: r for r in got}
            for aid in top:
                if aid in by:
                    dom = by[aid][3] or ""
                    edition = dom.split(".", 1)[0] if dom.endswith("wikipedia.org") else ""
                    content_items.append(
                        {
                            "article_id": aid,
                            "title": by[aid][1],
                            "wiki": edition,
                            "url": f"/api/articles/{aid}/view",  # the LOCAL reader (invariant #6)
                            "published_at": by[aid][2].isoformat() if by[aid][2] else None,
                        }
                    )
    # 2) downloaded-dump BODY matches (labelled dump results; honest empty when none).
    dump_items, dump_available, dump_more = _dump_hits(q)
    dump_note = " + downloaded-dump content" + (" (more available)" if dump_more else "") \
        if dump_items else ""

    # 3) watched-page TITLE catalog (fills remaining slots / the no-content fallback).
    pat = "%" + _like_escape(q) + "%"
    base = db.query(WikiPage).filter(WikiPage.title.ilike(pat, escape="\\"))
    if content_total:
        title_items = []
        if len(content_items) < _PER_GROUP:
            for p in base.order_by(WikiPage.title).limit(_PER_GROUP - len(content_items)).all():
                title_items.append({"page_id": p.id, "title": p.title, "wiki": p.wiki})
        capped = len(ids) > len(window)
        return {
            "kind": "wiki",
            "items": content_items + title_items,
            "total": content_total,
            "dump_items": dump_items,
            "dump_available": dump_available,
            "dump_more": dump_more,
            "note": "FTS5 content match over your Wikipedia corpus"
            + (" (within the top results)" if capped else "")
            + (" + watched-page titles" if title_items else "")
            + dump_note,
        }
    total = base.count()
    rows = base.order_by(WikiPage.title).limit(_PER_GROUP).all()
    return {
        "kind": "wiki",
        "items": [{"page_id": p.id, "title": p.title, "wiki": p.wiki} for p in rows],
        "total": total,
        "dump_items": dump_items,
        "dump_available": dump_available,
        "dump_more": dump_more,
        "note": "title match over your watched-pages list (no indexed Wikipedia content matched)"
        + dump_note,
    }


def _law_group(db: Session, q: str) -> dict:
    pat = "%" + _like_escape(q) + "%"
    base = db.query(LawDocument).filter(LawDocument.title.ilike(pat, escape="\\"))
    total = base.count()
    rows = base.order_by(LawDocument.title).limit(_PER_GROUP).all()
    return {
        "kind": "law",
        "items": [
            {"document_id": d.id, "title": d.title, "jurisdiction": d.jurisdiction}
            for d in rows
        ],
        "total": total,
        "note": "title contains-match over your tracked law documents",
    }


@router.get("/omni")
def omni(q: str = Query(min_length=2, max_length=200), db: Session = Depends(get_db)) -> dict:
    """Federated first-hits for the omnibar. Index-backed; totals disclosed.

    S2.4 guard: the omnibar fires per debounced keystroke and runs 2x full FTS
    ``search_ids`` (articles + wiki) — on a large corpus a 2-char term matches most
    of it. ``guarded_read`` collapses identical concurrent keystrokes to ONE compute
    (single-flight) + a concurrency cap + a statement deadline, so a burst can never
    pile onto the one SQLCipher connection. Because the omnibar must NEVER blank, a
    busy/timeout DEGRADES to an honest empty-with-note payload (never a 429/503)."""
    q = " ".join(q.split())
    _method = (
        "index-backed federation: FTS5 for articles, the normalized-term index "
        "for keywords, bounded catalog tables for the rest; first "
        f"{_PER_GROUP} per group with the true totals disclosed"
    )

    def _compute() -> dict:
        groups = []
        for fn in (_articles_group, _keywords_group, _sources_group, _wiki_group, _law_group):
            try:
                groups.append(fn(db, q))
            except Exception:  # noqa: BLE001 - one group must never blank the omnibar
                _LOG.warning("omni group %s failed", fn.__name__, exc_info=True)
        return {"q": q, "per_group": _PER_GROUP, "groups": groups, "method": _method}

    def _degraded(_exc) -> dict:
        return {
            "q": q,
            "per_group": _PER_GROUP,
            "groups": [],
            "method": _method,
            "degraded": "search is under load — results are momentarily unavailable; try again",
        }

    from src.api.heavy import guarded_read

    return guarded_read(
        db, f"omni|{q}", _compute, on_timeout=_degraded, on_busy=_degraded
    )
