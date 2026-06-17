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

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.analytics import queries as q
from src.analytics.convergence import find_convergences
from src.database.session import get_db

router = APIRouter(prefix="/api/insights", tags=["insights"])

_VALID_KINDS = ("term", "entity", "person", "org", "location")


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
    db: Session = Depends(get_db),
) -> dict:
    """Top keywords across the analysis corpus — either an EXPLICIT article-id set (a
    card / agenda event's exact selection) or the article SEARCH (the omnibar path).

    Bounded to ``cap`` articles; the bound is DISCLOSED (``total_matched``/``capped``)
    — it scopes the analysis, never a hidden cut. No score; counts only, honest caveat.
    """
    ids, total = _resolve_corpus(
        db, article_ids, query=query, source=source, start_date=start_date,
        end_date=end_date, language=language, tags=tags, cap=cap,
    )
    res = q.corpus_keywords(db, article_ids=ids, kind=_kind(kind), limit=limit)
    res["total_matched"] = total
    res["capped"] = total > len(ids)
    res["method"] = "Keyword counts across the matched articles, ordered by how many mention each term."
    res["caveat"] = (
        f"Counts only, never a score — scoped to the top {len(ids)} matched "
        "article(s) by relevance."
    )
    return res


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
    """Who (people/orgs) + Where (places) DEDUCED across the analysis corpus (an
    explicit article-id set or the search) — the analysis window's When/Where/Who.
    Deduced from text, never confirmed; no score. Bounded to ``cap`` (disclosed)."""
    ids, total = _resolve_corpus(
        db, article_ids, query=query, source=source, start_date=start_date,
        end_date=end_date, language=language, tags=tags, cap=cap,
    )
    return {
        "who": q.corpus_who(db, article_ids=ids, limit=limit),
        "where": q.corpus_where(db, article_ids=ids, limit=limit),
        "n_articles": len(ids),
        "total_matched": total,
        "capped": total > len(ids),
        "caveat": "Deduced from article text, never confirmed; counts only.",
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
    ids, total = _resolve_corpus(
        db, article_ids, query=query, source=source, start_date=start_date,
        end_date=end_date, language=language, tags=tags, cap=cap,
    )
    res = q.corpus_sentiment(db, article_ids=ids)
    res["total_matched"] = total
    res["capped"] = total > len(ids)
    return res


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
    ids, total = _resolve_corpus(
        db, article_ids, query=query, source=source, start_date=start_date,
        end_date=end_date, language=language, tags=tags, cap=cap,
    )
    res = q.corpus_sources(db, article_ids=ids, limit=limit)
    res["n_articles"] = len(ids)
    res["total_matched"] = total
    res["capped"] = total > len(ids)
    return res


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
    ids, total = _resolve_corpus(
        db, article_ids, query=query, source=source, start_date=start_date,
        end_date=end_date, language=language, tags=tags, cap=cap,
    )
    res = q.corpus_coordination(db, article_ids=ids)
    res["total_matched"] = total
    res["capped"] = total > len(ids)
    return res


@router.get("/top")
def insights_top(
    days: int | None = Query(None, ge=1, le=3650),
    country: str | None = None,
    kind: str | None = Query(None),
    limit: int = Query(20, ge=1, le=200),
    group: bool = Query(True, description="Merge surface variants into entity families"),
    db: Session = Depends(get_db),
) -> dict:
    """Most-mentioned keywords (optionally windowed / per-country / per-kind)."""
    return q.top_terms(db, days=days, country=country, kind=_kind(kind), limit=limit, group=group)


@router.get("/trending")
def insights_trending(
    window_days: int = Query(7, ge=1, le=365),
    baseline_days: int = Query(30, ge=1, le=3650),
    country: str | None = None,
    kind: str | None = None,
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    """Rising keywords by a transparent recent-vs-prior ratio."""
    return q.trending(
        db,
        window_days=window_days,
        baseline_days=baseline_days,
        country=country,
        kind=_kind(kind),
        limit=limit,
    )


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
    db: Session = Depends(get_db),
) -> dict:
    """Rising keywords across THREE preset windows side by side — past 24h · past
    week · past month — for the Insights "Trends" redesign (maintainer-ruled
    2026-06-16). Each window is the transparent recent-vs-prior ratio (no score);
    short windows are sparse, so n + the early-corpus caveat travel with the data.

    ADDITIVE: ``series_top > 0`` attaches a per-term daily ``series`` (reusing the
    /trend day buckets) to the top terms so the frontend can draw an ooChart each;
    ``series_top=0`` (default) is byte-identical to the prior response."""
    return q.trending_windows(
        db, country=country, kind=_kind(kind), limit=limit, series_top=series_top
    )


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
    return q.associations(db, term, limit=limit, min_cooccur=min_cooccur, group=group)


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
    from sqlalchemy import func

    from src.analytics.equivalence import ring_meta
    from src.analytics.families import canonical_key
    from src.database.models import Keyword, KeywordMention

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
    rows = (
        db.query(
            Keyword.normalized_term,
            func.sum(KeywordMention.count),
            func.count(func.distinct(KeywordMention.article_id)),
        )
        .join(KeywordMention, KeywordMention.keyword_id == Keyword.id)
        .group_by(Keyword.id)
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
def list_supergroups(db: Session = Depends(get_db)) -> dict:
    """List super-groups with their members (families AND rings) + aggregate totals."""
    from src.analytics.equivalence import ring_meta
    from src.database.models import KeywordSuperGroup

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
    return {"count": len(out), "supergroups": out}


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
        return q.article_graph(db, article_ids=ids)
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

    return q.layered_graph(
        db, level=level, term=term, hops=hops, days=days, start=_parse(start), end=_parse(end)
    )


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
