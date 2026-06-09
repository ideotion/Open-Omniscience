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
    return q.trending(db, window_days=window_days, baseline_days=baseline_days,
                      country=country, kind=_kind(kind), limit=limit)


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


def _upsert_override(db: Session, normalized: str, family_key: str,
                     label: str | None, kind: str | None) -> None:
    from src.database.models import KeywordFamilyOverride

    row = db.query(KeywordFamilyOverride).filter_by(normalized_term=normalized).first()
    if row:
        row.family_key, row.canonical_label, row.kind = family_key, label, kind
    else:
        db.add(KeywordFamilyOverride(normalized_term=normalized, family_key=family_key,
                                     canonical_label=label, kind=kind))


@router.get("/family/overrides")
def family_overrides(db: Session = Depends(get_db)) -> dict:
    """List the user's manual family overrides, grouped by family."""
    from src.database.models import KeywordFamilyOverride

    fams: dict[str, dict] = {}
    for o in db.query(KeywordFamilyOverride).order_by(KeywordFamilyOverride.family_key).all():
        f = fams.setdefault(o.family_key, {"family_key": o.family_key, "label": o.canonical_label,
                                           "kind": o.kind, "members": [], "split": o.family_key.startswith("__alone__:")})
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
