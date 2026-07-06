"""
Insights API: keyword & entity analytics over the corpus.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Read endpoints (trends, top/trending, associations, context, map) plus a chunked
"index corpus" action that backfills mentions for articles that lack them. Every
number is a real aggregate with method/caveat carried through from
src/analytics/queries.
"""

from __future__ import annotations

import logging
import os as _os
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.analytics import queries as q
from src.analytics import readmodel as rm
from src.analytics.convergence import find_convergences
from src.database.maintenance import StatementTimeout, statement_deadline
from src.database.session import get_db
from src.utils.cache import SimpleCache

_LOG = logging.getLogger("api.insights")

router = APIRouter(prefix="/api/insights", tags=["insights"])

_VALID_KINDS = ("term", "entity", "person", "org", "location")

# ---------------------------------------------------------------------------- #
# Whole-corpus read cache (perf, field report 2026-06-18).
#
# top / trending / trending-windows / map all GROUP BY over the full 829k-mention
# table per call (measured 2.7-36 s), and the Home "Trending" panel POLLS one of
# them — 132 calls in one session. They recompute the SAME numbers every time. A
# short TTL cache makes the UI instant; honest about it (computed_at + cache_ttl_s
# + a `cached` flag travel in the payload, like the database-stats cache). We use a
# plain TTL (NOT a write-invalidated probe) on purpose: under continuous scraping a
# write-invalidated cache would be cold on every pass — exactly when the operator is
# looking — so a small disclosed staleness buys a permanently-snappy UI. The cache
# is WARMED in the background after each scrape (warm_cache), so even the first open
# rarely hits a cold query. OO_INSIGHTS_CACHE_TTL overrides; 0 disables.
_CACHE_TTL_S = int(_os.getenv("OO_INSIGHTS_CACHE_TTL", "120"))

# The (limit, series_top) shapes the UI actually requests for trending-windows — the
# warmer MUST mirror these or it warms keys nothing reads (P0-4). Kept in sync with
# src/static/app.js (loadHomeTrends / loadTrendWindows) by a test_repo_invariants guard.
WARM_TRENDING_HOME = (4, 4)
WARM_TRENDING_INSIGHTS = (6, 6)
_read_cache = SimpleCache(max_size=128, default_ttl=max(1, _CACHE_TTL_S))


def _ckey(name: str, **params) -> str:
    return name + "|" + "|".join(f"{k}={params[k]}" for k in sorted(params))


def _cached(key: str, compute):
    """Return the cached payload (flagged ``cached: true``) or compute, stamp the
    freshness window, store and return it. Disabled when the TTL is 0."""
    if _CACHE_TTL_S <= 0:
        return compute()
    hit = _read_cache.get(key)
    if isinstance(hit, dict):
        return {**hit, "cached": True}
    out = compute()
    if isinstance(out, dict):
        out = {
            **out,
            "computed_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "cache_ttl_s": _CACHE_TTL_S,
        }
        _read_cache.set(key, out)
        return {**out, "cached": False}
    return out


def _deadlined(db: Session, key: str, compute):
    """Cache + a statement DEADLINE around the heaviest per-keyword reads.

    The per-keyword analysis subtabs (associations / graph / framing) are
    whole-corpus co-occurrence aggregations that, on a large encrypted corpus,
    could run for minutes — the field "Loading… forever" freeze (remark 8). The
    deadline (``statement_deadline``, OO_STATEMENT_TIMEOUT_S, default 60 s) aborts
    a runaway aggregation with a typed StatementTimeout, which we map to an honest
    HTTP 503 ("…exceeded the Ns deadline…") instead of an unbounded hang. The
    deadline runs INSIDE the compute, so it only fires on a cache MISS — a hot
    cache hit never touches the connection. Layered on top of the existing TTL
    cache + background warm (#455/#458), which remain the primary speed lever.
    """
    def _run():
        with statement_deadline(db):
            return compute()

    try:
        return _cached(key, _run)
    except StatementTimeout as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _resolve_corpus(
    db: Session,
    article_ids: str | None,
    *,
    query: str | None,
    source: str | None,
    start_date: str | None,
    end_date: str | None,
    language: str | None,
    tags: str | None,
    cap: int,
) -> tuple[list[int], int]:
    """Resolve the analysis corpus to ``(ids, total)``.

    An EXPLICIT article-id set (a Home card / agenda event's *precise* selection,
    comma-separated) takes precedence — deduped, order-preserving, bounded by ``cap``;
    ``total`` discloses the full requested size so the endpoints' ``capped`` flag stays
    honest. Otherwise the article SEARCH runs (the omnibar path), byte-for-byte
    unchanged. This is the substrate for exact-corpus card seeding (maintainer-ruled
    2026-06-16: a card opens the analysis window over the EXACT articles it identified).
    """
    if article_ids:
        seen: set[int] = set()
        ids: list[int] = []
        for tok in article_ids.split(","):
            tok = tok.strip()
            if tok.isdigit():
                v = int(tok)
                if v not in seen:
                    seen.add(v)
                    ids.append(v)
        return ids[:cap], len(ids)
    from src.api.main import _query_articles

    articles, total = _query_articles(
        db, query=query, source=source, start_date=start_date, end_date=end_date,
        language=language, tags=tags, limit=cap, offset=0,
    )
    return [a.id for a in articles], total


class KeywordFilterUpdate(BaseModel):
    excluded: list[str] | str | None = None
    min_length: int | None = None
    drop_numeric: bool | None = None
    use_builtin_stopwords: bool | None = None


class TermBody(BaseModel):
    term: str


@router.get("/filter")
def get_filter() -> dict:
    """Current keyword-filter settings (excluded terms, min length, options)."""
    from src.analytics.filters import load_settings

    return load_settings().to_dict()


@router.put("/filter")
def update_filter(update: KeywordFilterUpdate) -> dict:
    """Update keyword-filter settings (excluded list / min length / options)."""
    from src.analytics.filters import save_settings

    return save_settings(update.model_dump(exclude_unset=True)).to_dict()


@router.get("/filter/builtin")
def get_builtin_stopwords(q: str = "", limit: int = 500) -> dict:
    """The built-in multilingual stoplist actually filtering keywords — read-only.

    The manual excluded list (GET /filter) is small and editable, but the bulk of the
    filtering is this automatic ~2,500-word multilingual stoplist, which the user could
    not see before (only a toggle). Surface it so "show the current filter-out list" is
    honest: return the total count plus a bounded, optionally-searched slice (these words
    are curated + language-scoped, so editing them is a code change — this view is
    read-only; the toggle in /filter turns the whole list on or off)."""
    from src.analytics.extract import global_stopwords

    terms = sorted(global_stopwords())
    total = len(terms)
    needle = " ".join(q.split()).casefold()
    if needle:
        terms = [w for w in terms if needle in w]
    matched = len(terms)
    lim = max(1, min(2000, int(limit) if str(limit).lstrip("-").isdigit() else 500))
    return {"total": total, "matched": matched, "terms": terms[:lim], "capped": matched > lim}


@router.post("/exclude")
def exclude_term(body: TermBody) -> dict:
    """Hide a keyword from all listings (reversible; stored mentions are kept)."""
    from src.analytics.filters import add_excluded

    if not body.term.strip():
        raise HTTPException(status_code=400, detail="term is required")
    return add_excluded(body.term).to_dict()


@router.post("/include")
def include_term(body: TermBody) -> dict:
    """Re-include a previously excluded keyword."""
    from src.analytics.filters import remove_excluded

    return remove_excluded(body.term).to_dict()


@router.get("/status")
def insights_status(db: Session = Depends(get_db)) -> dict:
    """Indexing progress + corpus keyword/entity totals."""
    return q.status(db)


@router.post("/reindex")
def insights_reindex(limit: int = Query(300, ge=1, le=5000), db: Session = Depends(get_db)) -> dict:
    """Index up to ``limit`` not-yet-indexed articles (call repeatedly to finish)."""
    from src.analytics.extract import get_extractor
    from src.analytics.store import backfill_corpus

    return backfill_corpus(db, extractor=get_extractor("baseline"), limit=limit)


@router.post("/prune-keywords")
def insights_prune_keywords(db: Session = Depends(get_db)) -> dict:
    """Garbage-collect keywords that no view references (zero mentions) — the cleanup
    that shrinks an inflated keyword count after a markup re-index drain. Pure GC, not a
    cap: a keyword with any mention is never touched; curated terms are kept."""
    from src.analytics.store import prune_orphan_keywords

    return prune_orphan_keywords(db)


@router.post("/reconcile-keyword-language")
def insights_reconcile_keyword_language(db: Session = Depends(get_db)) -> dict:
    """Re-language keywords to their signature-majority article language (P4.2) — the fix
    for the first-write-wins ``Keyword.language`` that ingest never reconciles. Background
    pass (off the request path conceptually; bounded covering scans, no per-row article
    join). Counts only, no score; a tag only changes on a clear majority."""
    from src.analytics.store import reconcile_keyword_language

    return reconcile_keyword_language(db)


@router.post("/reconcile-article-language")
def insights_reconcile_article_language(
    limit: int = Query(300, ge=1, le=2000),
    after_id: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    """Backfill the DEDUCED language of UNKNOWN articles (maintainer ask 2026-07-02) — an
    article with NEITHER an asserted ``language`` nor a ``detected_language``. Two tiers,
    most-reliable first: the offline TEXT detector, then (fallback) the DOMINANT language
    among the article's own indexed KEYWORDS (gated on a real majority). The result is
    stored ONLY in ``detected_language`` (the deduced channel) — the asserted ``language``
    is never overwritten. Bounded + resumable (call repeatedly with ``after_id=last_id``
    until ``done``). Counts only, no score."""
    from src.analytics.store import reconcile_article_language

    return reconcile_article_language(db, limit=limit, after_id=after_id)


@router.post("/reindex-all")
def insights_reindex_all(
    limit: int = Query(300, ge=1, le=2000),
    after_id: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    """FORCE-re-index a batch of ALL articles (not just un-indexed ones) — the
    maintenance drain for stale keyword/metadata an OLD extraction engine produced
    (e.g. pre-2026-06-20 .eml bodies that leaked bare CSS keywords). Heavy; call
    repeatedly with ``after_id=last_id`` until ``done``."""
    from src.analytics.extract import get_extractor
    from src.analytics.store import reindex_all_batch

    return reindex_all_batch(db, extractor=get_extractor("baseline"), limit=limit, after_id=after_id)


@router.post("/reindex-job")
def insights_reindex_job(scope: str = Query("full"), prune_after: bool = Query(False)) -> dict:
    """Start the whole-corpus re-index as a BACKGROUND JOB (Phase 1.1) — it survives a
    tab close and RESUMES from a persisted cursor (no more "keep the tab open / restart
    from 0"). Pausable from the task manager (kind="reindex", a DB-writer). ``scope``
    (Phase 1.2): "full" recomputes keywords + when/where/who + sentiment; "keywords"
    does the keyword pass only (≈⅔ less work for a keyword cleanup). When ``prune_after``
    is set, the orphan-keyword GC chains on a complete pass (the one-click "clean up
    keywords" flow). 400 on a bad scope; 409 if a re-index is already running."""
    if scope not in ("full", "keywords"):
        raise HTTPException(status_code=400, detail="scope must be 'full' or 'keywords'")
    from src.analytics.reindex_job import get_reindex_manager

    try:
        return get_reindex_manager().start(scope=scope, prune_after=prune_after)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/reindex-job/status")
def insights_reindex_job_status() -> dict:
    """Live state of the (single) background re-index job — for the UI + /api/jobs."""
    from src.analytics.reindex_job import get_reindex_manager

    return get_reindex_manager().status()


@router.post("/reindex-job/{action}")
def insights_reindex_job_action(action: str) -> dict:
    """Pause / resume / cancel the running background re-index."""
    from src.analytics.reindex_job import get_reindex_manager

    mgr = get_reindex_manager()
    if action == "pause":
        mgr.pause()
        return mgr.status()
    if action == "resume":
        try:
            return mgr.resume()
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    if action == "cancel":
        mgr.cancel()
        return mgr.status()
    raise HTTPException(status_code=400, detail=f"unknown action {action!r}")


@router.get("/corpus-keywords")
def insights_corpus_keywords(
    query: str | None = None,
    source: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    language: str | None = None,
    tags: str | None = None,
    kind: str | None = Query(None),
    article_ids: str | None = Query(None, description="explicit article-id set (exact card corpus)"),
    limit: int = Query(30, ge=1, le=100),
    cap: int = Query(1000, ge=1, le=5000),
    target_lang: str | None = Query(None, description="UI language for verified ring translations"),
    db: Session = Depends(get_db),
) -> dict:
    """Top keywords across the analysis corpus — either an EXPLICIT article-id set (a
    card / agenda event's exact selection) or the article SEARCH (the omnibar path).

    Bounded to ``cap`` articles; the bound is DISCLOSED (``total_matched``/``capped``)
    — it scopes the analysis, never a hidden cut. No score; counts only, honest caveat.
    ``target_lang`` annotates each row with its verified cross-language translation.
    """
    # Cache by the resolved-corpus identity so re-opening a keyword / switching back to
    # this subtab is instant instead of re-paying the search + aggregation (field test
    # 2026-06-24: the analysis window's "Loading…"). Resolve INSIDE the compute so a hit
    # skips the search too. TTL-disclosed (cached/computed_at), like every cached endpoint.
    key = _ckey("corpus-keywords", ids=article_ids, q=query, src=source, sd=start_date,
                ed=end_date, lang=language, tags=tags, kind=kind, limit=limit, cap=cap, tl=target_lang)

    def _compute() -> dict:
        ids, total = _resolve_corpus(
            db, article_ids, query=query, source=source, start_date=start_date,
            end_date=end_date, language=language, tags=tags, cap=cap,
        )
        res = q.corpus_keywords(db, article_ids=ids, kind=_kind(kind), limit=limit, target_lang=_tlang(target_lang))
        res["total_matched"] = total
        res["capped"] = total > len(ids)
        res["method"] = "Keyword counts across the matched articles, ordered by how many mention each term."
        res["caveat"] = (
            f"Counts only, never a score — scoped to the top {len(ids)} matched "
            "article(s) by relevance."
        )
        return res

    return _cached(key, _compute)


@router.get("/corpus-www")
def insights_corpus_www(
    query: str | None = None,
    source: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    language: str | None = None,
    tags: str | None = None,
    article_ids: str | None = Query(None, description="explicit article-id set (exact card corpus)"),
    limit: int = Query(40, ge=1, le=200),
    cap: int = Query(1000, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> dict:
    """Who (people/orgs) + Where (places) + When (mentioned years) DEDUCED across the
    analysis corpus (an explicit article-id set or the search) — the analysis window's
    When/Where/Who facet surface. Each facet value is clickable (the drill endpoint
    below narrows the corpus). Deduced from text, never confirmed; no score. Bounded to
    ``cap`` (disclosed)."""
    key = _ckey("corpus-www", ids=article_ids, q=query, src=source, sd=start_date,
                ed=end_date, lang=language, tags=tags, limit=limit, cap=cap)

    def _compute() -> dict:
        ids, total = _resolve_corpus(
            db, article_ids, query=query, source=source, start_date=start_date,
            end_date=end_date, language=language, tags=tags, cap=cap,
        )
        return {
            "who": q.corpus_who(db, article_ids=ids, limit=limit),
            "where": q.corpus_where(db, article_ids=ids, limit=limit),
            "when": q.corpus_when(db, article_ids=ids, limit=limit),
            "n_articles": len(ids),
            "total_matched": total,
            "capped": total > len(ids),
            "caveat": "Deduced from article text, never confirmed; counts only.",
        }

    return _cached(key, _compute)


@router.get("/corpus-facet-articles")
def insights_corpus_facet_articles(
    facet: str = Query(..., description="entity | place | when"),
    value: str = Query(..., description="the facet value to drill into"),
    query: str | None = None,
    source: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    language: str | None = None,
    tags: str | None = None,
    article_ids: str | None = Query(None, description="explicit article-id set (exact card corpus)"),
    cap: int = Query(1000, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> dict:
    """The facet DRILL — the article ids WITHIN the current analysis corpus that carry a
    given facet value (an ``entity`` name, a ``place`` name, or a ``when`` year). This is
    what makes a facet co-equal with the text query: a facet value narrows the corpus, and
    the caller spawns a refined analysis window over the returned ids. Deduced from text,
    never confirmed; these articles MENTION the value (counts only, no score)."""
    if facet not in ("entity", "place", "when"):
        raise HTTPException(status_code=400, detail="facet must be entity|place|when")
    ids, total = _resolve_corpus(
        db, article_ids, query=query, source=source, start_date=start_date,
        end_date=end_date, language=language, tags=tags, cap=cap,
    )
    matched = q.corpus_facet_article_ids(db, article_ids=ids, facet=facet, value=value)
    return {
        "facet": facet,
        "value": value,
        "article_ids": matched,
        "total": len(matched),
        "corpus_n": len(ids),
        "corpus_total": total,
        "caveat": "Deduced from text, never confirmed — these articles mention the value.",
    }


@router.get("/corpus-sentiment")
def insights_corpus_sentiment(
    query: str | None = None,
    source: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    language: str | None = None,
    tags: str | None = None,
    article_ids: str | None = Query(None, description="explicit article-id set (exact card corpus)"),
    cap: int = Query(1000, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> dict:
    """Tone distribution across the analysis corpus (an explicit article-id set or the
    search) — the Sentiment tab — from the STORED per-article VADER valence. VADER is
    English-lexicon based, so the response carries the English share + a caveat that
    non-English scores are unreliable. Counts only; tone is a measured word-valence,
    never a verdict. Bounded to ``cap`` (disclosed)."""
    key = _ckey("corpus-sentiment", ids=article_ids, q=query, src=source, sd=start_date,
                ed=end_date, lang=language, tags=tags, cap=cap)

    def _compute() -> dict:
        ids, total = _resolve_corpus(
            db, article_ids, query=query, source=source, start_date=start_date,
            end_date=end_date, language=language, tags=tags, cap=cap,
        )
        res = q.corpus_sentiment(db, article_ids=ids)
        res["total_matched"] = total
        res["capped"] = total > len(ids)
        return res

    return _cached(key, _compute)


@router.get("/corpus-sources")
def insights_corpus_sources(
    query: str | None = None,
    source: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    language: str | None = None,
    tags: str | None = None,
    article_ids: str | None = Query(None, description="explicit article-id set (exact card corpus)"),
    limit: int = Query(40, ge=1, le=200),
    cap: int = Query(1000, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> dict:
    """How each SOURCE covers the analysis corpus (an explicit article-id set or the
    search) — the source view: per-source volume, mean tone, publication span. Counts +
    dates exact; mean tone inherits the VADER English caveat. No ranking, no verdict —
    coverage, not credibility. Bounded to ``cap`` (disclosed)."""
    key = _ckey("corpus-sources", ids=article_ids, q=query, src=source, sd=start_date,
                ed=end_date, lang=language, tags=tags, limit=limit, cap=cap)

    def _compute() -> dict:
        ids, total = _resolve_corpus(
            db, article_ids, query=query, source=source, start_date=start_date,
            end_date=end_date, language=language, tags=tags, cap=cap,
        )
        res = q.corpus_sources(db, article_ids=ids, limit=limit)
        res["n_articles"] = len(ids)
        res["total_matched"] = total
        res["capped"] = total > len(ids)
        return res

    return _cached(key, _compute)


@router.get("/corpus-coordination")
def insights_corpus_coordination(
    query: str | None = None,
    source: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    language: str | None = None,
    tags: str | None = None,
    article_ids: str | None = Query(None, description="explicit article-id set (exact card corpus)"),
    cap: int = Query(400, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> dict:
    """Near-duplicate / coordination clusters within the analysis corpus (an explicit
    article-id set or the search) -- the ambient "N near-identical copies across M sources
    = one voice" surface that lets the user BRANCH a cluster into a new corpus. Structural
    near-duplication only (MinHash+LSH, high-precision); independence = distinct sources;
    counts only, NO score. Bounded to ``cap`` (disclosed) because clustering reads full
    article text."""
    key = _ckey("corpus-coordination", ids=article_ids, q=query, src=source, sd=start_date,
                ed=end_date, lang=language, tags=tags, cap=cap)

    def _compute() -> dict:
        ids, total = _resolve_corpus(
            db, article_ids, query=query, source=source, start_date=start_date,
            end_date=end_date, language=language, tags=tags, cap=cap,
        )
        res = q.corpus_coordination(db, article_ids=ids)
        res["total_matched"] = total
        res["capped"] = total > len(ids)
        return res

    return _cached(key, _compute)


def _tlang(target_lang: str | None) -> str | None:
    """Sanitise the target-language code for verified-translation annotation.

    Type-safe: some tests call the endpoint FUNCTIONS directly (e.g.
    ``list_supergroups(db=s)``), so an unset ``target_lang`` arrives as its FastAPI
    ``Query(None)`` default OBJECT, not ``None`` — treat any non-str as no-filter."""
    if not isinstance(target_lang, str):
        return None
    c = target_lang.strip().lower()
    return c if (2 <= len(c) <= 3 and c.isalpha()) else None


@router.get("/latest")
def insights_latest(
    limit: int = Query(20, ge=1, le=100),
    window_days: int = Query(30, ge=1, le=3650),
    min_words: int = Query(0, ge=0, description="Substance gate: minimum article word count"),
    min_sources: int = Query(
        0, ge=0, description="Substance gate: minimum in-article cited (external) sources"
    ),
    content_type: str | None = Query(None, description="Facet: source channel/content type"),
    tag: str | None = Query(None, description="Facet: a source tag"),
    collapse: bool = Query(True, description="Collapse near-identical wire reprints"),
    facets: bool = Query(True, description="Include the available content-type/tag options"),
    db: Session = Depends(get_db),
) -> dict:
    """Home "Latest in your corpus": newest articles (by un-spoofable collection time)
    that pass TWO transparent substance gates (min words AND min cited sources), with
    near-identical wire reprints collapsed. A recency LENS + filters, never a score or
    a reweighting; each row shows its real word_count + cited-source count."""
    from src.analytics.latest import latest_articles

    key = _ckey(
        "latest", limit=limit, window_days=window_days, min_words=min_words,
        min_sources=min_sources, content_type=content_type or "", tag=tag or "",
        collapse=collapse, facets=facets,
    )
    return _cached(
        key,
        lambda: latest_articles(
            db, limit=limit, window_days=window_days, min_words=min_words,
            min_sources=min_sources, content_type=content_type, tag=tag,
            collapse=collapse, facets=facets,
        ),
    )


@router.get("/top")
def insights_top(
    days: int | None = Query(None, ge=1, le=3650),
    country: str | None = None,
    kind: str | None = Query(None),
    limit: int = Query(20, ge=1, le=200),
    group: bool = Query(True, description="Merge surface variants into entity families"),
    target_lang: str | None = Query(
        None, description="UI language: annotate each row with its verified ring translation into this language"
    ),
    db: Session = Depends(get_db),
) -> dict:
    """Most-mentioned keywords (optionally windowed / per-country / per-kind).

    ``target_lang`` makes the rows language-aware: a foreign keyword whose concept is
    in a cross-language ring gains its verified translation into that language."""
    tl = _tlang(target_lang)
    key = _ckey("top", days=days, country=country, kind=kind, limit=limit, group=group, tl=tl)

    def _compute() -> dict:
        out = rm.top_terms(
            db, days=days, country=country, kind=_kind(kind), limit=limit, group=group,
            target_lang=tl,
        )
        # Honesty envelope over the counts (Slice 2). The corpus-wide path reads the
        # maintained counters -> disclose their freshness; the windowed/per-country path
        # is a live GROUP BY computed now -> exact. ADDITIVE: a new `counts` key only.
        if days or country:
            from src.analytics.envelope import Envelope, now_iso

            out["counts"] = Envelope.exact(
                out.get("count", 0),
                as_of=now_iso(),
                method="live mention aggregation over the window",
                n=out.get("count", 0),
            ).to_dict()
        else:
            from src.analytics.store import counter_envelope

            out["counts"] = counter_envelope(db).to_dict()
        return out

    return _cached(key, _compute)


@router.get("/trending")
def insights_trending(
    window_days: int = Query(7, ge=1, le=365),
    baseline_days: int = Query(30, ge=1, le=3650),
    country: str | None = None,
    kind: str | None = None,
    limit: int = Query(20, ge=1, le=200),
    target_lang: str | None = Query(None, description="UI language for verified ring translations"),
    db: Session = Depends(get_db),
) -> dict:
    """Rising keywords by a transparent recent-vs-prior ratio."""
    tl = _tlang(target_lang)
    key = _ckey("trending", window_days=window_days, baseline_days=baseline_days,
                country=country, kind=kind, limit=limit, tl=tl)
    return _cached(key, lambda: rm.trending(
        db,
        window_days=window_days,
        baseline_days=baseline_days,
        country=country,
        kind=_kind(kind),
        limit=limit,
        target_lang=tl,
    ))


@router.get("/trending-windows")
def insights_trending_windows(
    country: str | None = None,
    kind: str | None = None,
    limit: int = Query(10, ge=1, le=50),
    series_top: int = Query(
        0,
        ge=0,
        le=10,
        description="Attach a daily mention-count series to the first N terms of "
        "each window (0 = none; reuses the /trend day series, counts only).",
    ),
    target_lang: str | None = Query(None, description="UI language for verified ring translations"),
    db: Session = Depends(get_db),
) -> dict:
    """Rising keywords across THREE preset windows side by side — past 24h · past
    week · past month — for the Insights "Trends" redesign (maintainer-ruled
    2026-06-16). Each window is the transparent recent-vs-prior ratio (no score);
    short windows are sparse, so n + the early-corpus caveat travel with the data.

    ADDITIVE: ``series_top > 0`` attaches a per-term daily ``series`` (reusing the
    /trend day buckets) to the top terms so the frontend can draw an ooChart each;
    ``series_top=0`` (default) is byte-identical to the prior response."""
    tl = _tlang(target_lang)
    key = _ckey("trending-windows", country=country, kind=kind, limit=limit,
                series_top=series_top, tl=tl)
    return _cached(key, lambda: rm.trending_windows(
        db, country=country, kind=_kind(kind), limit=limit, series_top=series_top, target_lang=tl
    ))


@router.get("/trend")
def insights_trend(
    term: str,
    bucket: str = Query("week", pattern="^(day|week|month)$"),
    country: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """Mention volume over time for one keyword."""
    return q.trend(db, term, bucket=bucket, country=country)


@router.get("/associations")
def insights_associations(
    term: str,
    limit: int = Query(20, ge=1, le=100),
    min_cooccur: int = Query(2, ge=1, le=50),
    group: bool = Query(True, description="Merge surface variants into entity families"),
    db: Session = Depends(get_db),
) -> dict:
    """Keywords co-occurring with ``term`` (PMI-ranked) — powers the mind-map."""
    key = _ckey("associations", term=term, limit=limit, min_cooccur=min_cooccur, group=group)
    return _deadlined(db, key, lambda: rm.associations(
        db, term, limit=limit, min_cooccur=min_cooccur, group=group))


@router.get("/context")
def insights_context(
    term: str,
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> dict:
    """Recent mention snippets for a keyword, with article + source links."""
    return q.context(db, term, limit=limit)


@router.get("/map")
def insights_map(
    days: int | None = Query(30, ge=1, le=3650),
    kind: str | None = None,
    top_per_area: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
) -> dict:
    """Top keywords per country and per city (for the world map).

    City entries are enriched with lat/lon from the city gazetteer (disambiguated
    by country) so the UI can plot them; cities not in the gazetteer keep their
    keyword data but carry no coordinates (honest: no fabricated position).
    """
    from src.catalog.cities import build_index, load_cities, lookup

    data = q.map_data(db, days=days, kind=_kind(kind), top_per_area=top_per_area)
    index = build_index(load_cities())
    placed = 0
    for city in data.get("cities", []):
        hit = lookup(index, city.get("name", ""), city.get("country"))
        if hit:
            city["lat"], city["lon"] = hit.lat, hit.lon
            placed += 1
    data["cities_placed"] = placed
    return data


@router.get("/map-coverage")
def insights_map_coverage(db: Session = Depends(get_db)) -> dict:
    """Per-country COVERAGE for the choropleth (ooMap, slice 2): how many sources
    -- and the articles collected from them -- originate in each country.

    The FIRST map dimension is ``sources``. Counts only, NO score. Sources with
    no catalogued country are surfaced in ``unlocated`` and never placed on the
    map. Each located country also carries a centroid (``lat``/``lon`` from the
    gazetteer) so the UI can fall back to a POINT for territories the coarse
    110m geometry has no polygon for -- a point, never an invented border.
    """
    def _compute() -> dict:
        from src.catalog.countries import continent_of, country_display_name
        from src.timemap.geocode import geocode

        data = rm.source_country_counts(db)
        for row in data["by_country"]:
            cc = row["country"]
            disp = country_display_name(cc)
            # A real country gets its name; an unknown code shows uppercased (honest:
            # the code itself), never a fabricated name.
            row["name"] = disp if (disp and disp != cc) else cc.upper()
            row["continent"] = continent_of(cc)
            pt = geocode(country=cc)
            if pt:
                row["lat"], row["lon"] = pt["lat"], pt["lon"]
        data["dimension"] = "sources"
        data["method"] = (
            "Count of catalogued sources whose country = each ISO-2 area "
            "(articles = those collected from them). Counts only, no score."
        )
        data["caveat"] = (
            "Country is operator/catalogue-asserted; sources without a country are "
            "counted as 'unlocated', never placed on the map."
        )
        return data

    return _cached(_ckey("map-coverage"), _compute)


@router.get("/server-locations")
def insights_server_locations(db: Session = Depends(get_db)) -> dict:
    """The ooMap "server location" layer (Slice 6c): the captured server IPs (Slice 6a)
    geolocated OFFLINE (Slice 6b), per-country, with IP/host CLUSTERING + honest
    unavailable buckets (Tor/proxy, not-captured, unknown-IP).

    DISTINCT from the editorial ``map-coverage`` (Source.country) layer: this is the
    NETWORK location we actually connected to -- our vantage point (often a CDN edge /
    anycast), never proof of the publisher's origin. Counts only, NO score; the caveat is
    visible by default. Until the country DB is bundled (a networked-machine step), the
    located countries are empty and everything lands honestly in the unavailable buckets.
    """
    return _cached(_ckey("server-locations"), lambda: q.server_locations(db))


@router.get("/lunar-correlation")
def insights_lunar_correlation(
    term: str | None = Query(
        None, description="A single keyword to test (uncorrected); omit to screen the top-N."
    ),
    limit: int = Query(40, ge=1, le=200, description="Terms to screen when no term is given"),
    fdr_q: float = Query(0.05, gt=0.0, le=1.0, description="FDR level for the screen"),
    db: Session = Depends(get_db),
) -> dict:
    """Test whether a keyword's daily coverage lines up with the moon — HONESTLY.

    With ``term`` set, returns a single circular-shift correlation (r, p-value, n) with the
    explicit note that one test is not a screen. Without ``term``, screens the top-N
    most-mentioned keywords against the moon's illuminated fraction and corrects the whole
    family with Benjamini-Hochberg FDR — so a survivor is one that beat multiple-testing,
    never a bare significant p. Correlation is NOT causation (stated on every result); the
    common, honest outcome is that nothing survives. Counts + statistics only, no score.
    """
    from src.analytics import lunar

    if term:
        corr = lunar.correlate_keyword(db, term)
        return {
            "term": term,
            "result": corr.to_dict() if corr else None,
            "single_test": True,
            "variable": "illuminated_fraction",
            "method": lunar.LUNAR_METHOD,
            "caveat": lunar.CORRELATION_CAVEAT,
            "note": (
                "A single test, NOT corrected for multiple comparisons — screen many series "
                "(omit 'term') for an honest, FDR-corrected result."
                if corr else "Too few active days to test this keyword honestly."
            ),
        }
    return lunar.lunar_screen(db, limit=limit, fdr_q=fdr_q)


class PollFieldsBody(BaseModel):
    """A poll's DISCLOSED methodological fields (any subset). Presence, not value, is what
    the transparency checklist reads — a supplied field is 'disclosed', omitted is not.
    Extra keys are allowed so a caller can pass any additional disclosure it captured."""

    model_config = {"extra": "allow"}

    pollster: str | None = None
    sponsor: str | None = None
    fielding_dates: str | None = None
    sample_size: int | str | None = None
    population: str | None = None
    question_wording: str | None = None
    sampling_method: str | None = None
    margin_of_error: str | None = None
    mode: str | None = None
    weighting: str | None = None
    response_rate: str | None = None


@router.post("/poll-transparency")
def insights_poll_transparency(body: PollFieldsBody) -> dict:
    """A poll TRANSPARENCY checklist (Tier 2) — never a score.

    Given a poll's DISCLOSED methodological fields, returns a per-item checklist of what was
    STATED vs not (who ran it, who paid, when, n, who was sampled, the exact question, …),
    with the verbatim question echoed when present. It records PRESENCE only, never the
    value's quality: a disclosed n=100 counts exactly like a disclosed n=10000, so
    transparency is never penalized; non-disclosure of a core item outranks any disclosed
    imperfection. It never grades a poll, never ranks, and never calls one 'useless' — it
    surfaces the disclosure floor and lets you conclude. No composite score.
    """
    from src.analytics.poll_transparency import assess_poll_transparency

    fields = body.model_dump(exclude_none=True)
    return assess_poll_transparency(fields).to_dict()


def warm_cache(db: Session) -> dict:
    """Pre-compute the common whole-corpus views into the read cache so the Home /
    Insights surfaces never hit a cold heavy query (perf, field report 2026-06-18).

    Called best-effort AFTER each scrape's briefing refresh (same cadence, same
    background thread), using the DEFAULT parameter combos the UI actually requests.
    Stores under the exact keys the endpoints use, so a warmed value is a cache HIT.
    """
    # Bounded background reconcile of the maintained keyword counters (Slice 2): runs
    # here (off the request path) and is a cheap no-op while the counters are fresh, so
    # it throttles itself to ~once per freshness window. Repairs the rare cascade-delete
    # drift and stamps the watermark the honesty envelope reads. Best-effort.
    try:
        from src.analytics.store import maybe_reconcile_counters

        maybe_reconcile_counters(db)
    except Exception:  # noqa: BLE001 - never fatal to a pass
        _LOG.warning("background counter reconcile failed during warm_cache", exc_info=True)

    # AUTOMATIC keyword cleanup (maintainer 2026-07-02: "Clean up keywords should be
    # automatic"): the cheap maintenance — prune orphan keywords + reconcile keyword
    # language — freshness-gated to ~once per 12h, so it is a no-op most passes. A full
    # re-index stays a manual/post-upgrade action (too heavy to run unprompted). The run
    # is recorded in a marker the corpus-integrity diagnostic surfaces.
    try:
        from src.analytics.store import maybe_cleanup_keywords

        maybe_cleanup_keywords(db)
    except Exception:  # noqa: BLE001 - never fatal to a pass
        _LOG.warning("background keyword cleanup failed during warm_cache", exc_info=True)

    # Maintain the derived COLUMNAR read-model — ONLY when the store is PERSISTED
    # (Slice 4 D). A no-op when columnar is unavailable / in-memory (an in-memory store
    # is rebuilt per process, so persisting it in the background would be wasted work).
    # Uses the SAME corpus passphrase (no second key surface). Best-effort, off the
    # request path; the canonical store stays the source of truth.
    try:
        from src.analytics.columnar import refresh_persisted_read_model
        from src.database.connect import get_passphrase

        refresh_persisted_read_model(db, passphrase=get_passphrase())
    except Exception:  # noqa: BLE001 - never fatal to a pass
        _LOG.warning("columnar read-model refresh failed during warm_cache", exc_info=True)

    # Opt-in (OO_COLUMNAR_SERVE=1) in-memory rollup serve: (re)build it in the background so
    # the windowed views pick up new articles. No-op unless opted in; never blocks.
    try:
        from src.analytics import rollup_serve

        rollup_serve.refresh(db)
    except Exception:  # noqa: BLE001 - a background accelerator must never break a pass
        _LOG.warning("rollup serve refresh failed during warm_cache", exc_info=True)

    warmed: list[str] = []
    # Warm the EXACT keys the surfaces request, or the warm value is never a hit and
    # the user pays the cold heavy query themselves (P0-4, field test 2026-06-22: the
    # old limit=10 keys matched NOTHING — Home asks limit=4/series_top=4, Insights
    # limit=8/series_top=5 — and they ALSO omitted `tl`, which the endpoint always
    # includes, so warming was dead for trending-windows). The key params here MUST
    # mirror src/static/app.js (loadHomeTrends + loadTrendWindows); the WARM_TRENDING_*
    # constants are asserted against app.js in tests so a drift reddens CI. Warmed for
    # the English (tl=None) path — a non-English UI still recomputes once (a follow-up:
    # decouple the cheap translation annotation from the expensive aggregation cache).
    specs: list[tuple[str, object]] = []
    for lim, st in (WARM_TRENDING_HOME, WARM_TRENDING_INSIGHTS):
        specs.append(
            (
                _ckey("trending-windows", country=None, kind=None, limit=lim, series_top=st, tl=None),
                lambda lim=lim, st=st: rm.trending_windows(
                    db, country=None, kind=None, limit=lim, series_top=st, target_lang=None
                ),
            )
        )
    specs.append(
        (_ckey("top", days=None, country=None, kind=None, limit=20, group=True),
         lambda: rm.top_terms(db, days=None, country=None, kind=None, limit=20, group=True))
    )
    if _CACHE_TTL_S <= 0:
        return {"warmed": warmed, "disabled": True}
    for key, compute in specs:
        # Already fresh (warmed within the TTL) -> skip; keeps warming cheap when
        # passes run faster than the TTL, recomputing only once a value expires.
        if _read_cache.get(key) is not None:
            continue
        try:
            out = compute()
            if isinstance(out, dict):
                out = {**out, "computed_at": datetime.now(UTC).isoformat(timespec="seconds"),
                       "cache_ttl_s": _CACHE_TTL_S}
                _read_cache.set(key, out)
                warmed.append(key)
        except Exception:  # noqa: BLE001 - warming is best-effort, never fatal to a pass
            _LOG.warning("insights cache warm failed for %s", key, exc_info=True)
    return {"warmed": warmed}


@router.get("/who")
def insights_who(
    entity_class: str | None = Query(
        None, description="person | organization (default: both)"
    ),
    days: int | None = Query(None, ge=1, le=3650),
    country: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    min_articles: int = Query(1, ge=1, le=10000),
    db: Session = Depends(get_db),
) -> dict:
    """Corpus-wide WHO — people & organizations deduced from article text at
    ingest, aggregated with honest counts (distinct articles + summed
    mentions). No scores; names are lexical surface forms, deduced never
    confirmed. Optionally windowed (``days``), per-country, or class-filtered.
    """
    return q.who_aggregate(
        db,
        entity_class=entity_class,
        days=days,
        country=country,
        limit=limit,
        min_articles=min_articles,
    )


@router.get("/where")
def insights_where(
    kind: str | None = Query(None, description="city | country (default: both)"),
    days: int | None = Query(None, ge=1, le=3650),
    country: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    min_articles: int = Query(1, ge=1, le=10000),
    db: Session = Depends(get_db),
) -> dict:
    """Corpus-wide WHERE — places deduced from article text at ingest,
    aggregated with honest counts (distinct articles + summed mentions) and a
    gazetteer coordinate when known. No scores; deduced, never confirmed.
    ``country`` selects places located in that country. Optionally windowed
    (``days``) or kind-filtered (``city`` | ``country``).
    """
    return q.where_aggregate(
        db,
        kind=kind,
        days=days,
        country=country,
        limit=limit,
        min_articles=min_articles,
    )


@router.get("/convergences")
def insights_convergences(
    window_days: int = Query(7, ge=1, le=90, description="±days around an anchor event date"),
    lookback_days: int | None = Query(
        None, ge=1, le=36500, description="only mentioned-dates within N days of today (None = all history)"
    ),
    min_articles: int = Query(3, ge=2, le=100, description="surfacing gate: distinct articles"),
    min_sources: int = Query(2, ge=2, le=100, description="surfacing gate: DISTINCT sources"),
    limit: int = Query(12, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    """Read-only space-time convergences over the deduced When×Where×Who substrate
    (the 0.0.9 flagship logic, surfaced as a view). Groups articles converging on
    the same PLACE within a time window on the MENTIONED event date.

    Honesty by construction (all baked into ``find_convergences``): independence is
    measured by DISTINCT SOURCES (never article count), the surfacing gate is
    ``>=min_articles`` AND ``>=min_sources`` (a chatty single source can't manufacture
    one), shared-outbound-link counts flag false triangulation, the metric is
    ``distinct_sources`` (NO score), and every cluster carries the verbatim
    "never causation … a prompt to read, not proof anything happened" caveat. Totals
    are always disclosed so ``limit`` never silently hides how much qualified.
    """
    return find_convergences(
        db,
        window_days=window_days,
        lookback_days=lookback_days,
        min_articles=min_articles,
        min_sources=min_sources,
        limit=limit,
    )


@router.get("/ring-countries")
def insights_ring_countries(
    ring_id: str = Query(..., description="an equivalence-ring id, e.g. 'inflation'"),
    days: int | None = Query(None, ge=1, le=36500, description="restrict to articles published within N days"),
    limit: int = Query(40, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    """Split a cross-language equivalence ring's coverage by SOURCE country.

    The multi-perspective / de-US-centring lens: the trans-language layer already merges
    a concept across languages (élection+election+wahl); this shows WHO covers it, by the
    producing source's country. Counts only, no score, no ranking — coverage is not
    credibility. Reuses the language-qualified ring resolver (no fabricated merge); a
    keyword with no stored language is excluded; unlocated sources bucket as null."""
    from src.analytics.queries import ring_country_split

    return ring_country_split(db, ring_id=ring_id, days=days, limit=limit)


@router.get("/source-laundering")
def insights_source_laundering(
    min_sources: int = Query(3, ge=2, le=100, description="distinct-source surfacing gate"),
    min_articles: int = Query(3, ge=2, le=100),
    days: int | None = Query(None, ge=1, le=36500),
    limit: int = Query(12, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    """Origins cited by many DISTINCT sources — apparent corroboration that isn't
    independent (manipulation-pattern card #6). Names the STRUCTURE, never intent:
    independence is distinct sources (not article count); social/storefront origins
    are excluded; the innocent explanation is stated beside the pattern; no score."""
    from src.analytics.laundering import find_source_laundering

    return find_source_laundering(
        db, min_sources=min_sources, min_articles=min_articles, days=days, limit=limit
    )


@router.get("/recycled-claims")
def insights_recycled_claims(
    recent_days: int = Query(14, ge=1, le=3650, description="window for a 'current' resurfacing"),
    lookback_days: int = Query(
        365, ge=1, le=36500, description="how far back to look for an original"
    ),
    min_gap_days: int = Query(60, ge=1, le=36500, description="minimum dormancy gap to surface"),
    limit: int = Query(12, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    """Recent articles that near-duplicate a much OLDER one — a claim resurfacing after
    dormancy (manipulation-pattern card). Names the STRUCTURE, never intent: the trigger
    is a measured time gap (not a score); a single source recycling its own evergreen is
    flagged; the innocent explanations are stated beside the pattern."""
    from src.analytics.recycled_claim import find_recycled_claims

    return find_recycled_claims(
        db,
        recent_days=recent_days,
        lookback_days=lookback_days,
        min_gap_days=min_gap_days,
        max_clusters=limit,
    )


@router.get("/headline-body-mismatch")
def insights_headline_body_mismatch(
    recent_days: int = Query(14, ge=1, le=3650, description="recent window to scan"),
    d_min: float = Query(0.67, ge=0.0, le=1.0, description="lexical-divergence fire threshold"),
    limit: int = Query(12, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    """Recent articles whose HEADLINE leads with content the body does not substantiate
    (manipulation-pattern card #7). Names the STRUCTURE, never intent: real ratios
    (lexical divergence + an English-only sentiment gap), no score; a summarising or
    metaphorical headline does this innocently — stated beside the pattern."""
    from src.analytics.headline_body import find_headline_body_mismatch

    return _cached(
        _ckey("headline-body-mismatch", recent_days=recent_days, d_min=d_min, limit=limit),
        lambda: find_headline_body_mismatch(
            db, recent_days=recent_days, d_min=d_min, max_items=limit
        ),
    )


@router.get("/manufactured-emergence")
def insights_manufactured_emergence(
    recent_days: int = Query(7, ge=1, le=365, description="onset window"),
    min_sources: int = Query(3, ge=2, le=100, description="distinct sources to be 'born wide'"),
    limit: int = Query(12, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    """New keywords that appeared wide-and-sudden across many sources with NO datable
    anchor (manipulation-pattern card #3). Names the STRUCTURE, never intent: born-wide
    independence is distinct SOURCES, the anchor gate suppresses genuine breaking news,
    and the false-negative caveat is stated. No score."""
    from src.analytics.emergence import find_manufactured_emergence

    return _cached(
        _ckey("manufactured-emergence", recent_days=recent_days, min_sources=min_sources, limit=limit),
        lambda: find_manufactured_emergence(
            db, recent_days=recent_days, min_sources=min_sources, max_items=limit
        ),
    )


@router.get("/flooded-topics")
def insights_flooded_topics(
    recent_days: int = Query(7, ge=1, le=365, description="recent window"),
    z_min: float = Query(2.5, ge=0.0, le=20.0, description="share-jump z-score fire threshold"),
    limit: int = Query(12, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    """Sources flooding a single topic far above their OWN history (manipulation card #4).
    A two-proportion z-test of the source's recent share vs its prior share — names the
    STRUCTURE, never intent; the innocent twin (volume isn't importance) is stated; no
    score. Reads the denormalised source_id, so it covers re-indexed articles."""
    from src.analytics.concentration import find_flooded_topics

    return _cached(
        _ckey("flooded-topics", recent_days=recent_days, z_min=z_min, limit=limit),
        lambda: find_flooded_topics(db, recent_days=recent_days, z_min=z_min, max_items=limit),
    )


@router.get("/copypasta")
def insights_copypasta(
    recent_days: int = Query(14, ge=1, le=365, description="recent window to scan"),
    k: int = Query(8, ge=3, le=40, description="minimum verbatim phrase length, in words"),
    min_sources: int = Query(3, ge=2, le=100, description="distinct-source surfacing gate"),
    limit: int = Query(12, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    """Verbatim phrases copied across many DISTINCT sources in articles that are NOT whole
    duplicates — a coordinated talking point / copypasta (manipulation-pattern card). Names
    the STRUCTURE, never intent: independence is distinct sources (not article count); whole-
    article wire republish is excluded (echo_chamber's job); the innocent twin (shared quote /
    boilerplate) is stated beside the pattern; no score."""
    from src.analytics.copypasta import find_copypasta

    return _cached(
        _ckey("copypasta", recent_days=recent_days, k=k, min_sources=min_sources, limit=limit),
        lambda: find_copypasta(
            db, recent_days=recent_days, k=k, min_sources=min_sources, max_items=limit
        ),
    )


def _kind(kind: str | None) -> str | None:
    """Pass through only recognised kind filters (others ignored)."""
    return kind if kind in _VALID_KINDS else None


# -- Keyword-family overrides (manual merge / split — "the user disposes") ---- #


class FamilyMerge(BaseModel):
    normalized: list[str]
    label: str | None = None
    kind: str | None = None


class FamilySplit(BaseModel):
    normalized: str
    label: str | None = None
    kind: str | None = None


def _n(s: str | None) -> str:
    return " ".join((s or "").split()).casefold()


def _upsert_override(
    db: Session, normalized: str, family_key: str, label: str | None, kind: str | None
) -> None:
    from src.database.models import KeywordFamilyOverride

    row = db.query(KeywordFamilyOverride).filter_by(normalized_term=normalized).first()
    if row:
        row.family_key, row.canonical_label, row.kind = family_key, label, kind
    else:
        db.add(
            KeywordFamilyOverride(
                normalized_term=normalized, family_key=family_key, canonical_label=label, kind=kind
            )
        )


@router.get("/family/overrides")
def family_overrides(db: Session = Depends(get_db)) -> dict:
    """List the user's manual family overrides, grouped by family."""
    from src.database.models import KeywordFamilyOverride

    fams: dict[str, dict] = {}
    for o in db.query(KeywordFamilyOverride).order_by(KeywordFamilyOverride.family_key).all():
        f = fams.setdefault(
            o.family_key,
            {
                "family_key": o.family_key,
                "label": o.canonical_label,
                "kind": o.kind,
                "members": [],
                "split": o.family_key.startswith("__alone__:"),
            },
        )
        f["members"].append(o.normalized_term)
    return {"count": sum(len(f["members"]) for f in fams.values()), "families": list(fams.values())}


@router.post("/family/merge")
def family_merge(body: FamilyMerge, db: Session = Depends(get_db)) -> dict:
    """Force two or more surface forms into one family (authoritative over auto-rules)."""
    from src.analytics.families import canonical_key

    norms = list(dict.fromkeys(n for n in (_n(x) for x in body.normalized) if n))
    if len(norms) < 2:
        raise HTTPException(status_code=400, detail="Provide at least two distinct forms to merge.")
    label = body.label or norms[0]
    family_key = canonical_key(_n(label)) or norms[0]
    for n in norms:
        _upsert_override(db, n, family_key, label, body.kind)
    db.commit()
    return {"merged": norms, "family_key": family_key, "label": label}


@router.post("/family/split")
def family_split(body: FamilySplit, db: Session = Depends(get_db)) -> dict:
    """Pin a surface form standalone, removing it from any automatic family."""
    n = _n(body.normalized)
    if not n:
        raise HTTPException(status_code=400, detail="normalized is required.")
    _upsert_override(db, n, "__alone__:" + n, body.label or body.normalized, body.kind)
    db.commit()
    return {"split": n}


@router.delete("/family/override")
def family_override_clear(normalized: str, db: Session = Depends(get_db)) -> dict:
    """Remove an override for a form, restoring automatic grouping."""
    from src.database.models import KeywordFamilyOverride

    n = _n(normalized)
    deleted = db.query(KeywordFamilyOverride).filter_by(normalized_term=n).delete()
    db.commit()
    return {"cleared": n, "deleted": int(deleted)}


# -- Keyword super-groups (a user-named group of families) -------------------- #


class SuperGroupCreate(BaseModel):
    name: str
    color: str | None = None


class SuperGroupMembers(BaseModel):
    normalized: list[str] = []
    rings: list[str] = []  # ring ids — a ring MEMBER is a cross-language concept (super-ring)


def _supergroup_totals(db: Session, member_rows: set[tuple[str, str | None]]) -> dict[str, dict]:
    """Aggregate mentions/articles per member.

    A FAMILY member (``ring_id`` None) matches its own normalized term (+ canonical
    key), as before. A RING member aggregates over ALL the ring's cross-language
    terms, so a super-group with a ring spans languages — the super-ring model.
    Keyed by the member's ``normalized_term`` (the ring id for a ring); a display
    total, best-effort like the original (one term feeds one member key)."""
    from src.analytics.equivalence import ring_meta
    from src.analytics.families import canonical_key
    from src.database.models import Keyword

    term_to_key: dict[str, str] = {}
    canon_to_key: dict[str, str] = {}
    keys: list[str] = []
    for norm_key, ring_id in member_rows:
        keys.append(norm_key)
        if ring_id:
            meta = ring_meta(ring_id)
            for _lang, term in meta.members if meta else ():
                term_to_key[_n(term)] = norm_key  # every ring term -> this ring member
        else:
            term_to_key[norm_key] = norm_key
            canon_to_key[canonical_key(norm_key)] = norm_key

    totals = {k: {"mentions": 0, "articles": 0} for k in keys}
    if not keys:
        return totals

    # PERFORMANCE (field report 2026-06-18: "Groups" took 132 s and froze the UI on a
    # 245k-keyword / 829k-mention corpus). The old query GROUP BY'd EVERY keyword joined
    # to EVERY mention, then kept only the handful belonging to a super-group — i.e. it
    # aggregated 829k mentions to discard 99.99% of them. Instead, resolve the member
    # keyword IDs FIRST (cheap, small columns), then aggregate mentions for ONLY those.
    matched_ids: set[int] = set()
    # Exact terms (every ring term + each family member's own term) — an indexed lookup.
    if term_to_key:
        for (kid,) in (
            db.query(Keyword.id)
            .filter(Keyword.normalized_term.in_(list(term_to_key)))
            .all()
        ):
            matched_ids.add(kid)
    # Family morphological variants (country↔countries) match by canonical key, which is
    # a Python function (not a column) — so a scan is unavoidable, but ONLY when a family
    # (non-ring) member exists, and over the small (id, term) columns, never the mentions.
    if canon_to_key:
        for kid, norm in db.query(Keyword.id, Keyword.normalized_term).all():
            if canonical_key(norm) in canon_to_key:
                matched_ids.add(kid)
    if not matched_ids:
        return totals
    # Read the denormalised per-keyword counters (maintained at index time) for the
    # resolved member ids — NO keyword_mentions join / GROUP BY. mention_count ==
    # SUM(count) and article_count == COUNT(DISTINCT article_id) by construction
    # (src/analytics/store.py + tests/test_keyword_counters.py), so the per-member
    # totals are identical; the residual mention aggregation over the matched ids is
    # gone, leaving a small index-only read on the keywords table.
    rows = (
        db.query(Keyword.normalized_term, Keyword.mention_count, Keyword.article_count)
        .filter(Keyword.id.in_(matched_ids))
        .all()
    )
    for norm, m, a in rows:
        key = term_to_key.get(norm) or canon_to_key.get(canonical_key(norm))
        if key is not None:
            totals[key]["mentions"] += int(m or 0)
            totals[key]["articles"] = max(totals[key]["articles"], int(a or 0))
    return totals


def _get_supergroup(db: Session, sg_id: int):
    from src.database.models import KeywordSuperGroup

    sg = db.query(KeywordSuperGroup).filter_by(id=sg_id).first()
    if sg is None:
        raise HTTPException(status_code=404, detail=f"Super-group {sg_id} not found.")
    return sg


@router.get("/supergroups")
def list_supergroups(
    target_lang: str | None = Query(None, description="UI language for verified ring translations"),
    db: Session = Depends(get_db),
) -> dict:
    """List super-groups with their members (families AND rings) + aggregate totals.

    ``target_lang`` binds the verified cross-language ``translation`` to each ring
    member (the maintainer ruling: translations bind to keyword families AND groups),
    so a super-ring shows its concept in the reader's language."""
    from src.analytics.equivalence import ring_meta, ring_translation
    from src.database.models import KeywordSuperGroup

    tl = _tlang(target_lang)
    sgs = db.query(KeywordSuperGroup).order_by(KeywordSuperGroup.name).all()
    member_rows = {(m.normalized_term, m.ring_id) for sg in sgs for m in sg.members}
    totals = _supergroup_totals(db, member_rows)
    out = []
    for sg in sgs:
        members = []
        for m in sg.members:
            t = totals.get(m.normalized_term, {})
            entry = {
                "normalized": m.normalized_term,
                "mentions": t.get("mentions", 0),
                "articles": t.get("articles", 0),
            }
            if m.ring_id:  # a ring member is a cross-language concept (super-ring)
                meta = ring_meta(m.ring_id)
                entry["ring_id"] = m.ring_id
                entry["ring_members"] = [f"{lg}:{term}" for lg, term in (meta.members if meta else ())]
                if tl:
                    tr = ring_translation(m.ring_id, tl)
                    if tr:
                        entry["translation"] = tr
                        entry["translation_source"] = "ring"
            members.append(entry)
        members.sort(key=lambda x: -x["mentions"])
        out.append(
            {
                "id": sg.id,
                "name": sg.name,
                "color": sg.color,
                "members": members,
                "count": len(members),
                "mentions": sum(x["mentions"] for x in members),
            }
        )
    out.sort(key=lambda s: -s["mentions"])
    # Honesty envelope over the maintained counters the super-group totals read (Slice
    # 2). ADDITIVE: a new `counts` key only. Disclosed `exact` when the counters were
    # reconciled within the freshness window, else `estimated` (may have drifted).
    from src.analytics.store import counter_envelope

    return {
        "count": len(out),
        "supergroups": out,
        "counts": counter_envelope(db).to_dict(),
    }


@router.get("/rings")
def list_rings() -> dict:
    """The cross-language equivalence rings (curated + Wikidata-generated), so the UI
    can show them and pick one to add to a super-group (the super-ring model). Read-only;
    rings come from the config files, not the corpus — no DB."""
    from src.analytics.equivalence import load_rings

    rings = [
        {
            "id": r.id,
            "members": [f"{lg}:{t}" for lg, t in r.members],
            "languages": sorted({lg for lg, _ in r.members}),
            "size": len(r.members),
        }
        for r in load_rings()
    ]
    rings.sort(key=lambda x: (-len(x["languages"]), x["id"]))
    return {"count": len(rings), "rings": rings}


@router.post("/supergroups")
def create_supergroup(body: SuperGroupCreate, db: Session = Depends(get_db)) -> dict:
    """Create a named super-group (the umbrella; members are added separately)."""
    from src.database.models import KeywordSuperGroup

    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required.")
    if db.query(KeywordSuperGroup).filter_by(name=name).first():
        raise HTTPException(status_code=409, detail=f"A super-group named {name!r} already exists.")
    sg = KeywordSuperGroup(name=name, color=(body.color or None))
    db.add(sg)
    db.commit()
    return {"id": sg.id, "name": sg.name, "color": sg.color}


@router.delete("/supergroups/{sg_id}")
def delete_supergroup(sg_id: int, db: Session = Depends(get_db)) -> dict:
    """Delete a super-group (its memberships cascade; keyword data is untouched)."""
    sg = _get_supergroup(db, sg_id)
    db.delete(sg)
    db.commit()
    return {"deleted": sg_id}


@router.post("/supergroups/{sg_id}/members")
def add_supergroup_members(
    sg_id: int, body: SuperGroupMembers, db: Session = Depends(get_db)
) -> dict:
    """Assign families (by normalized term) and/or RINGS (by ring id) to a super-group.

    Idempotent. A ring member makes the super-group cross-language (the super-ring
    model); unknown ring ids are rejected (400)."""
    from src.analytics.equivalence import ring_meta
    from src.database.models import KeywordSuperGroupMember

    sg = _get_supergroup(db, sg_id)
    existing = {m.normalized_term for m in sg.members}
    added = []
    for raw in body.normalized:
        n = _n(raw)
        if n and n not in existing:
            db.add(KeywordSuperGroupMember(supergroup_id=sg.id, normalized_term=n))
            existing.add(n)
            added.append(n)
    for raw in body.rings:
        rid = (raw or "").strip()
        if not rid or rid in existing:
            continue
        if ring_meta(rid) is None:
            raise HTTPException(status_code=400, detail=f"unknown ring {rid!r}")
        db.add(KeywordSuperGroupMember(supergroup_id=sg.id, normalized_term=rid, ring_id=rid))
        existing.add(rid)
        added.append(rid)
    db.commit()
    return {"supergroup": sg.id, "added": added, "members": sorted(existing)}


@router.delete("/supergroups/{sg_id}/members")
def remove_supergroup_member(sg_id: int, normalized: str, db: Session = Depends(get_db)) -> dict:
    """Remove one family from a super-group."""
    from src.database.models import KeywordSuperGroupMember

    _get_supergroup(db, sg_id)
    n = _n(normalized)
    deleted = (
        db.query(KeywordSuperGroupMember).filter_by(supergroup_id=sg_id, normalized_term=n).delete()
    )
    db.commit()
    return {"supergroup": sg_id, "removed": n, "deleted": int(deleted)}


@router.get("/graph")
def insights_graph(
    level: str = Query("keyword", description="keyword | family | supergroup"),
    term: str | None = Query(None, description="seed term (keyword level only)"),
    article_ids: str | None = Query(
        None, description="explicit article-id set → a radial keyword map over that "
        "exact selection (the reader / analysis 'corpus of 1+'); overrides term/level"
    ),
    hops: int = Query(2, ge=1, le=2),
    days: int | None = Query(None, ge=1, le=3650, description="window: last N days"),
    start: str | None = Query(None, description="window start (YYYY-MM-DD)"),
    end: str | None = Query(None, description="window end (YYYY-MM-DD)"),
    cap: int = Query(1000, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> dict:
    """The layered keyword graph (maintainer-ruled 2026-06-10): a keyword with
    its relatives AND its relatives' relatives (two hops); zoom out to keyword
    FAMILIES; zoom out again to curated SUPER-GROUPS. Every edge is real
    article co-occurrence with the method stated per level.

    With ``article_ids`` it instead returns a RADIAL keyword map over that exact
    article set — the reader's Mindmap tab (article = corpus of 1) and the analysis
    window's mindmap subtab. The explicit set takes precedence over term/level."""
    if article_ids:
        ids, _total = _resolve_corpus(
            db, article_ids, query=None, source=None, start_date=None,
            end_date=None, language=None, tags=None, cap=cap,
        )
        # Cache by the exact id set so re-opening the same analysis mindmap is instant.
        return _deadlined(db, _ckey("graph-articles", ids=",".join(map(str, ids))),
                          lambda: rm.article_graph(db, article_ids=ids))
    if level not in ("keyword", "family", "supergroup"):
        raise HTTPException(status_code=400, detail="level must be keyword|family|supergroup")
    if level == "keyword" and not (term or "").strip():
        raise HTTPException(status_code=400, detail="keyword level needs ?term=")
    from datetime import date as _date

    def _parse(d):
        try:
            return _date.fromisoformat(d) if d else None
        except ValueError:
            raise HTTPException(status_code=400, detail=f"bad date: {d!r}") from None

    key = _ckey("graph", level=level, term=term, hops=hops, days=days, start=start, end=end)
    return _deadlined(db, key, lambda: rm.layered_graph(
        db, level=level, term=term, hops=hops, days=days, start=_parse(start), end=_parse(end)
    ))


# --- Keyword tags (Item AC): explore + user curation of type/topic tags -------- #
#
# Tags are LABELLED ASSERTIONS along two axes (a semantic ``type`` and a ``topic``),
# never ground truth and never a score. A curated baseline applies them at index
# time (source="baseline"); these endpoints let the user explore them and add/remove
# their OWN (source="user"), fully reversible. Nothing in the keyword store is
# rewritten. See src/analytics/baseline.py + docs/design/KEYWORD_BASELINE_AND_MANAGEMENT.md.

_TAG_AXES = ("type", "topic")


class TagBody(BaseModel):
    normalized: str
    axis: str
    tag: str


def _norm_tag(axis: str | None, tag: str | None) -> tuple[str, str]:
    """Validate + normalise a (axis, tag) pair (lowercased, bounded). Raises 400."""
    ax = (axis or "").strip().lower()
    tg = " ".join((tag or "").split()).lower()
    if ax not in _TAG_AXES:
        raise HTTPException(status_code=400, detail=f"axis must be one of {list(_TAG_AXES)}")
    if not tg:
        raise HTTPException(status_code=400, detail="tag is required")
    if len(tg) > 64:
        raise HTTPException(status_code=400, detail="tag too long (max 64)")
    return ax, tg


@router.get("/keyword-tags")
def keyword_tags(normalized: str = Query(...), db: Session = Depends(get_db)) -> dict:
    """One keyword's tags, grouped by axis, with per-tag source provenance.

    Read-only; labels only, never a score. The ``sources`` map keys are
    ``"axis:tag"`` → ``"baseline"`` | ``"user"`` so the UI can show provenance."""
    from src.analytics.store import tags_for_keyword
    from src.database.models import Keyword, KeywordTag

    norm = _n(normalized)
    kw = db.query(Keyword).filter_by(normalized_term=norm).first()
    sources: dict[str, str] = {}
    if kw is not None:
        for r in db.query(KeywordTag).filter_by(keyword_id=kw.id):
            sources[f"{r.axis}:{r.tag}"] = r.source
    return {"normalized": norm, "tags": tags_for_keyword(db, norm), "sources": sources}


@router.post("/keyword-tags")
def add_keyword_tag(body: TagBody, db: Session = Depends(get_db)) -> dict:
    """Add a USER tag on a keyword (a labelled assertion; idempotent; reversible)."""
    from src.analytics.store import tags_for_keyword
    from src.database.models import Keyword, KeywordTag

    norm = _n(body.normalized)
    axis, tag = _norm_tag(body.axis, body.tag)
    kw = db.query(Keyword).filter_by(normalized_term=norm).first()
    if kw is None:
        raise HTTPException(status_code=404, detail="unknown keyword")
    exists = (
        db.query(KeywordTag).filter_by(keyword_id=kw.id, axis=axis, tag=tag, source="user").first()
    )
    if exists is None:
        db.add(KeywordTag(keyword_id=kw.id, axis=axis, tag=tag, source="user"))
        db.commit()
    return {"normalized": norm, "tags": tags_for_keyword(db, norm)}


@router.post("/keyword-tags/remove")
def remove_keyword_tag(body: TagBody, db: Session = Depends(get_db)) -> dict:
    """Remove a tag from a keyword (local curation — any source). Reversible by
    re-adding; a removed baseline tag is NOT re-applied (tagging is forward-only)."""
    from src.analytics.store import tags_for_keyword
    from src.database.models import Keyword, KeywordTag

    norm = _n(body.normalized)
    axis, tag = _norm_tag(body.axis, body.tag)
    kw = db.query(Keyword).filter_by(normalized_term=norm).first()
    if kw is not None:
        db.query(KeywordTag).filter_by(keyword_id=kw.id, axis=axis, tag=tag).delete()
        db.commit()
    return {"normalized": norm, "tags": tags_for_keyword(db, norm)}


@router.get("/keyword-tags/facets")
def keyword_tag_facets(db: Session = Depends(get_db)) -> dict:
    """Distinct tags per axis with DISTINCT-keyword counts — the explore filter.

    Counts only, no score. Empty axes are still listed so the UI is stable."""
    from sqlalchemy import func

    from src.database.models import KeywordTag

    rows = (
        db.query(
            KeywordTag.axis, KeywordTag.tag, func.count(func.distinct(KeywordTag.keyword_id))
        )
        .group_by(KeywordTag.axis, KeywordTag.tag)
        .all()
    )
    facets: dict[str, list[dict]] = {a: [] for a in _TAG_AXES}
    for axis, tag, n in rows:
        facets.setdefault(axis, []).append({"tag": tag, "keywords": int(n or 0)})
    for a in facets:
        facets[a].sort(key=lambda x: (-x["keywords"], x["tag"]))
    return {"axes": list(_TAG_AXES), "facets": facets}


@router.get("/keyword-tags/keywords")
def keywords_by_tag(
    axis: str = Query(...),
    tag: str = Query(...),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    """Keywords carrying a given (axis, tag), with mention/article counts + source.

    The explore view's main query. Ordered by article spread then mentions; counts
    only, never a score."""
    from sqlalchemy import func

    from src.database.models import Keyword, KeywordMention, KeywordTag

    ax, tg = _norm_tag(axis, tag)
    rows = (
        db.query(
            Keyword.normalized_term,
            Keyword.term,
            Keyword.language,
            KeywordTag.source,
            func.coalesce(func.sum(KeywordMention.count), 0),
            func.count(func.distinct(KeywordMention.article_id)),
        )
        .join(KeywordTag, KeywordTag.keyword_id == Keyword.id)
        .outerjoin(KeywordMention, KeywordMention.keyword_id == Keyword.id)
        .filter(KeywordTag.axis == ax, KeywordTag.tag == tg)
        .group_by(Keyword.id, KeywordTag.source)
        .all()
    )
    items = [
        {
            "normalized": norm,
            "term": term,
            "language": lang,
            "source": source,
            "mentions": int(m or 0),
            "articles": int(a or 0),
        }
        for norm, term, lang, source, m, a in rows
    ]
    items.sort(key=lambda x: (-x["articles"], -x["mentions"], x["normalized"]))
    return {"axis": ax, "tag": tg, "total": len(items), "keywords": items[:limit]}


@router.post("/keyword-tags/backfill")
def backfill_keyword_tags(
    limit: int = Query(0, ge=0, le=500000), db: Session = Depends(get_db)
) -> dict:
    """Apply curated baseline tags to EXISTING keywords (the retroactive pass).

    Tagging at ingest is forward-only, so a pre-existing corpus has no baseline tags
    until this runs. Idempotent; counts only, never invents a tag. ``limit=0`` = all."""
    from src.analytics.store import backfill_baseline_tags

    return backfill_baseline_tags(db, limit=limit or None)
