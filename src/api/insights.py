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
from src.database.session import get_db

router = APIRouter(prefix="/api/insights", tags=["insights"])

_VALID_KINDS = ("term", "entity", "person", "org", "location")


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
    limit: int = Query(30, ge=1, le=100),
    cap: int = Query(1000, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> dict:
    """Top keywords across the articles matched by a search — the analysis window.

    Re-runs the SAME article search as /api/articles, bounded to the top ``cap``
    matched articles (by relevance/recency), then aggregates their keywords. The
    bound is DISCLOSED (``total_matched``/``capped``) — it scopes the analysis,
    it is not a hidden cut. No score; counts only, with an honest caveat.
    """
    # Lazy import: main.py includes this router, so a module-level import would
    # be circular.
    from src.api.main import _query_articles

    articles, total = _query_articles(
        db, query=query, source=source, start_date=start_date, end_date=end_date,
        language=language, tags=tags, limit=cap, offset=0,
    )
    ids = [a.id for a in articles]
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
    limit: int = Query(40, ge=1, le=200),
    cap: int = Query(1000, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> dict:
    """Who (people/orgs) + Where (places) DEDUCED across the matched articles —
    the analysis window's When/Where/Who. Deduced from text, never confirmed; no
    score. Bounded to the top ``cap`` matched articles (disclosed)."""
    from src.api.main import _query_articles

    articles, total = _query_articles(
        db, query=query, source=source, start_date=start_date, end_date=end_date,
        language=language, tags=tags, limit=cap, offset=0,
    )
    ids = [a.id for a in articles]
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
    cap: int = Query(1000, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> dict:
    """Tone distribution across the matched articles (the analysis window's Sentiment
    tab), from the STORED per-article VADER valence. VADER is English-lexicon based,
    so the response carries the English share + a caveat that non-English scores are
    unreliable. Counts only; tone is a measured word-valence, never a verdict. Bounded
    to the top ``cap`` matched articles (disclosed)."""
    from src.api.main import _query_articles

    articles, total = _query_articles(
        db, query=query, source=source, start_date=start_date, end_date=end_date,
        language=language, tags=tags, limit=cap, offset=0,
    )
    ids = [a.id for a in articles]
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
    limit: int = Query(40, ge=1, le=200),
    cap: int = Query(1000, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> dict:
    """How each SOURCE covers the matched set (the analysis window's source view):
    per-source volume, mean tone, and publication span. Counts + dates exact; mean
    tone inherits the VADER English caveat. No ranking, no verdict -- coverage, not
    credibility. Bounded to the top ``cap`` matched articles (disclosed)."""
    from src.api.main import _query_articles

    articles, total = _query_articles(
        db, query=query, source=source, start_date=start_date, end_date=end_date,
        language=language, tags=tags, limit=cap, offset=0,
    )
    ids = [a.id for a in articles]
    res = q.corpus_sources(db, article_ids=ids, limit=limit)
    res["n_articles"] = len(ids)
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
    normalized: list[str]


def _supergroup_totals(db: Session, members: set[str]) -> dict[str, dict]:
    """Aggregate mentions/articles for each member family (by canonical normalized key)."""
    from sqlalchemy import func

    from src.analytics.families import canonical_key
    from src.database.models import Keyword, KeywordMention

    totals = {m: {"mentions": 0, "articles": 0} for m in members}
    if not members:
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
        key = (
            norm
            if norm in members
            else (canonical_key(norm) if canonical_key(norm) in members else None)
        )
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
    """List super-groups with their member families + aggregate mentions/articles."""
    from src.database.models import KeywordSuperGroup

    sgs = db.query(KeywordSuperGroup).order_by(KeywordSuperGroup.name).all()
    all_members = {m.normalized_term for sg in sgs for m in sg.members}
    totals = _supergroup_totals(db, all_members)
    out = []
    for sg in sgs:
        members = [
            {
                "normalized": m.normalized_term,
                "mentions": totals.get(m.normalized_term, {}).get("mentions", 0),
                "articles": totals.get(m.normalized_term, {}).get("articles", 0),
            }
            for m in sg.members
        ]
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
    """Assign one or more families (by normalized term) to a super-group (idempotent)."""
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
    hops: int = Query(2, ge=1, le=2),
    days: int | None = Query(None, ge=1, le=3650, description="window: last N days"),
    start: str | None = Query(None, description="window start (YYYY-MM-DD)"),
    end: str | None = Query(None, description="window end (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
) -> dict:
    """The layered keyword graph (maintainer-ruled 2026-06-10): a keyword with
    its relatives AND its relatives' relatives (two hops); zoom out to keyword
    FAMILIES; zoom out again to curated SUPER-GROUPS. Every edge is real
    article co-occurrence with the method stated per level."""
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
