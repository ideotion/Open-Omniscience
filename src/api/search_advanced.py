"""The advanced search's own endpoints (S05-01): its facets, did-you-mean, local history.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The search itself is ``/api/articles`` (and the export and every analysis endpoint), which
take the filter set through :func:`src.api.search_filters.advanced_search_params`. This
router serves what the BUILDER needs around it:

* ``GET /api/search/facets`` -- the values the builder offers, with counts: sources,
  countries (alpha-3 displayed, Q401 row L), regions, languages asserted and detected, and
  the caveats each filter carries (Q601: "sources facet with counts").
* ``/api/search/spell-index`` -- the did-you-mean table's build job and its note (Q605).
* ``/api/search/history`` -- the reader's own search history (Q614 = a): LOCAL, PRIVATE,
  OPT-IN (default off), CLEARABLE, NEVER EXPORTED. It lives in the encrypted ``app_state``
  store under one key read by this module alone (a test pins that nothing else reads it),
  so no article export, evidence bundle or diagnostics member can carry it; ``app_state``
  is never merged by a restore, so another machine's history is never adopted either.

All local: no network, no consent gate (nothing here leaves the machine).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.database.session import get_db
from src.jobs.background import BackgroundJob, register_job

router = APIRouter(prefix="/api/search", tags=["search"])

#: The ONE key the history lives under. Nothing outside this module may read it.
HISTORY_KEY = "search.history"
#: Most recent searches kept; older ones fall off the end.
HISTORY_MAX = 100


# --------------------------------------------------------------------------- #
# Facets
# --------------------------------------------------------------------------- #


@router.get("/facets")
def search_facets(db: Session = Depends(get_db)) -> dict:
    """What the builder offers, with counts. Source counts are the maintained per-source
    article counter (``Source.article_count``), the figure the Sources tab shows; the
    language counts are live, split into asserted and detected (field §2.6)."""
    from src.api.search_filters import FILTER_CAVEATS, LANG_BASES, SENTIMENT_LABELS
    from src.catalog.countries import country_display_code, country_display_name
    from src.config.app_settings import load_settings
    from src.database.fts import FIELD_MODES, FIELDS, NEAR_MAX, NEAR_MIN
    from src.database.models import Article, Source

    sources = [
        {"id": sid, "name": name, "domain": domain, "articles": int(n or 0)}
        for sid, name, domain, n in db.query(
            Source.id, Source.name, Source.domain, Source.article_count
        ).order_by(Source.article_count.desc().nullslast(), Source.name)
    ]
    countries: dict[str, dict] = {}
    for code, n in (
        db.query(Source.country, func.count(Source.id))
        .filter(Source.country.isnot(None), Source.country != "")
        .group_by(Source.country)
    ):
        key = str(code).lower()
        row = countries.setdefault(key, {
            "code": key,
            "display": country_display_code(key) or key.upper(),
            "name": country_display_name(key) or key.upper(),
            "sources": 0,
        })
        row["sources"] += int(n)
    regions = [
        {"region": r, "sources": int(n)}
        for r, n in db.query(Source.region, func.count(Source.id))
        .filter(Source.region.isnot(None), Source.region != "")
        .group_by(Source.region).order_by(func.count(Source.id).desc())
    ]
    asserted = {
        str(lang): int(n)
        for lang, n in db.query(Article.language, func.count(Article.id))
        .filter(Article.language.isnot(None)).group_by(Article.language)
    }
    detected = {
        str(lang): int(n)
        for lang, n in db.query(Article.detected_language, func.count(Article.id))
        .filter(Article.language.is_(None), Article.detected_language.isnot(None))
        .group_by(Article.detected_language)
    }
    # The date spans the two time components are drawn over. One aggregate per query:
    # SQLite answers a lone min() or max() from the index, and a query asking for both
    # scans the table instead.
    def _day(col, agg) -> str | None:
        v = db.query(agg(col)).scalar()
        return str(v)[:10] if v else None

    spans = {
        "published": {"min": _day(Article.published_at, func.min),
                      "max": _day(Article.published_at, func.max)},
        "collected": {"min": _day(Article.created_at, func.min),
                      "max": _day(Article.created_at, func.max)},
    }
    langs = sorted(set(asserted) | set(detected), key=lambda c: -(asserted.get(c, 0) + detected.get(c, 0)))
    return {
        "sources": sources,
        "countries": sorted(countries.values(), key=lambda r: -r["sources"]),
        "regions": regions,
        "languages": [
            {"code": c, "asserted": asserted.get(c, 0), "detected": detected.get(c, 0)} for c in langs
        ],
        "lang_bases": list(LANG_BASES),
        "sentiments": list(SENTIMENT_LABELS),
        "fields": list(FIELDS),
        "field_modes": list(FIELD_MODES),
        "near": {"default": load_settings().search_near_default, "min": NEAR_MIN, "max": NEAR_MAX},
        "caveats": FILTER_CAVEATS,
        "spans": spans,
    }


# --------------------------------------------------------------------------- #
# Did you mean (Q605 = b)
# --------------------------------------------------------------------------- #


def _spell_worker(ctx):
    from src.analytics.spell_index import build

    return build(ctx)


_SPELL_JOB = register_job(BackgroundJob(
    "search-spell-index", "Building the did-you-mean table", _spell_worker,
    is_writer=True, cancellable=True,
))


def _spell_job():
    return _SPELL_JOB


@router.get("/spell-index")
def spell_index_status() -> dict:
    """The last build's note (when, how many keywords and rows, how long, how big) and
    the live job state."""
    from src.analytics.spell_index import status

    return {**status(), "job": _spell_job().status()}


@router.post("/spell-index/build")
def spell_index_build() -> dict:
    """Start a rebuild on the task manager. 409 while one is already running."""
    try:
        return _spell_job().start()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# --------------------------------------------------------------------------- #
# Local search history (Q614 = a + its note)
# --------------------------------------------------------------------------- #


class HistoryEntry(BaseModel):
    query: str = Field("", max_length=2000)
    # The builder's full state (filters, sort, view) -- a permalink's parameters.
    params: dict = Field(default_factory=dict)


def _history() -> list[dict]:
    from src.config.kv_store import kv_get_json

    blob = kv_get_json(HISTORY_KEY) or {}
    entries = blob.get("entries")
    return entries if isinstance(entries, list) else []


def _save_history(entries: list[dict]) -> None:
    from src.config.kv_store import kv_set_json

    kv_set_json(HISTORY_KEY, {"entries": entries[:HISTORY_MAX]})


@router.get("/history")
def get_history() -> dict:
    from src.config.app_settings import load_settings

    enabled = load_settings().search_history_enabled
    return {
        "enabled": enabled,
        "entries": _history() if enabled else [],
        "max": HISTORY_MAX,
        "caveat": (
            "Stored only on this machine, inside your encrypted corpus. Never exported, "
            "never in a diagnostics bundle. Off unless you turn it on; clearing it deletes "
            "every entry."
        ),
    }


@router.post("/history")
def add_history(entry: HistoryEntry) -> dict:
    """Record one search -- refused (409) unless the reader turned history on."""
    from src.config.app_settings import load_settings

    if not load_settings().search_history_enabled:
        raise HTTPException(status_code=409, detail="search history is off")
    q = entry.query.strip()
    params = {str(k): v for k, v in (entry.params or {}).items() if v not in (None, "", [])}
    if not q and not params:
        return {"recorded": False, "count": len(_history())}
    entries = [e for e in _history() if not (e.get("query") == q and e.get("params") == params)]
    entries.insert(0, {"query": q, "params": params,
                       "at": datetime.now(UTC).isoformat(timespec="seconds")})
    _save_history(entries)
    return {"recorded": True, "count": min(len(entries), HISTORY_MAX)}


@router.delete("/history")
def clear_history() -> dict:
    """Delete every entry (whether or not history is on)."""
    _save_history([])
    return {"cleared": True, "count": 0}
