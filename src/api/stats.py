"""
Official-statistics API (Group N): the descriptive producer directory PLUS the
figure layer (consented live fetch, vintaged storage, side-by-side triangulation,
and the registered-sources view).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The directory + the read views are OFFLINE. The ONE networked action here is
``POST /figures/fetch`` — it routes through ``src.stats.fetch`` (the guarded factory:
kill switch + proxy, transport never downgraded) and is REFUSED up front when airplane
mode is engaged (the frontend additionally gates the button behind the ONE network
consent popup). NO scores anywhere: figures carry only their published value + the
provenance trail; producers are shown side by side and NEVER averaged.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/agencies")
def stat_agencies() -> dict:
    """The curated directory of official statistical producers — government +
    international agencies, deliberately global (BRICS, Africa and smaller economies
    included alongside Western producers + IGOs). Each is flagged ``controversial``
    (an official figure is a STANCED source — stated, never a score). Descriptive
    only: no figures, no ranking, no network. ``continents_covered`` is an honest
    coverage metric (the ruling measures coverage, never assumes it)."""
    from src.stats.agencies import continents_covered, list_agencies

    agencies = list_agencies()
    return {
        "agencies": [a.to_dict() for a in agencies],
        "count": len(agencies),
        "continents_covered": sorted(continents_covered()),
        "caveat": (
            "A directory of WHO publishes official statistics — every entry is a "
            "STANCED source (a producing state has interests), never a credibility "
            "verdict. Figures, vintages and methodology come later, triangulated "
            "side by side and never averaged."
        ),
    }


@router.post("/sources/ingest")
def ingest_stat_sources() -> dict:
    """Register the curated statistical producers as DISABLED, controversial sources.

    Each agency is added to the source catalog as a ``source_type="statistics"``
    Source, carrying the ``official-statistics`` + ``controversial`` tags (an
    official figure is a STANCED source — by ruling, every producer is
    ``controversial``; there is no "controversial" column). Rows are created
    DISABLED — registered, NOT scraped: official machine endpoints (SDMX / APIs)
    are preferred over scraping, wired up in a later slice.

    Additive and IDEMPOTENT — a domain already in the catalog is left untouched, so
    this is safe to call repeatedly; an operator's curation is never clobbered. NO
    ``reliability_score`` is written (no fabricated credibility score, ever). LOCAL
    DB write only: no network — ``home_url`` is reduced to a registrable domain
    locally, never fetched."""
    from src.database.session import session_scope
    from src.stats.ingest import ingest_agencies_as_sources

    with session_scope() as db:
        return ingest_agencies_as_sources(db)


# --------------------------------------------------------------------------- #
# The figure layer (consented fetch · vintaged storage · triangulation · views)
# --------------------------------------------------------------------------- #
class FigureFetchBody(BaseModel):
    """A consented, bounded official-statistics fetch request.

    ``source`` selects the producer family: ``worldbank`` (needs ``indicator`` +
    optional ``country``) or ``eurostat`` / any SDMX-JSON producer (needs ``dataset``
    + optional ``params``; ``agency`` defaults to ``eurostat`` but can name another
    SDMX-JSON producer, e.g. ``imf``). The fetch egresses over the user's configured
    transport and is REFUSED while airplane mode is engaged.
    """

    source: str = Field(..., description="worldbank | eurostat (SDMX-JSON)")
    indicator: str | None = Field(None, description="World Bank indicator id, e.g. NY.GDP.MKTP.CD")
    country: str = Field("all", description="World Bank country code or 'all'")
    dataset: str | None = Field(None, description="SDMX dataset id, e.g. nama_10_gdp")
    params: dict[str, str] | None = Field(None, description="extra SDMX query params")
    agency: str | None = Field(None, description="SDMX producer agency code (default eurostat)")


@router.post("/figures/fetch")
def fetch_figures(body: FigureFetchBody) -> dict:
    """Fetch official figures LIVE, parse, and store them with their vintage.

    The ONE networked stats action. It refuses up front under airplane mode (a clean
    409, never a traceback), routes through the guarded factory (kill switch + proxy,
    transport never downgraded), delegates parsing to the offline SDMX parser, and
    stores via the single-writer gate — a re-fetch at a new vintage is a new row, never
    an overwrite. Returns the storage tally + a small sample, NO score. A transport
    failure degrades LOUDLY (502 with an honest verdict), never a fabricated figure.
    """
    from src.database.session import session_scope
    from src.stats import fetch as statfetch
    from src.stats.store import store_figures

    src = (body.source or "").strip().lower()
    try:
        if src == "worldbank":
            if not (body.indicator and body.indicator.strip()):
                raise HTTPException(status_code=422, detail="worldbank fetch needs an 'indicator'")
            figures = statfetch.fetch_worldbank(body.indicator, body.country or "all")
        elif src in ("eurostat", "sdmx"):
            if not (body.dataset and body.dataset.strip()):
                raise HTTPException(status_code=422, detail="eurostat fetch needs a 'dataset'")
            figures = statfetch.fetch_eurostat(
                body.dataset, params=body.params, agency=(body.agency or "eurostat").strip().lower()
            )
        else:
            raise HTTPException(status_code=422, detail=f"unknown stats source: {body.source!r}")
    except HTTPException:
        raise
    except RuntimeError as exc:  # the kill-switch up-front refusal
        # Airplane mode engaged: an honest refusal, not a crash (the frontend gates the
        # button behind the ONE consent popup, but the backend refuses regardless).
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # transport / decode failure -> degrade loudly
        raise HTTPException(
            status_code=502,
            detail=f"official-statistics fetch failed (transport or endpoint): {exc}",
        ) from exc

    with session_scope() as db:
        tally = store_figures(db, figures)
    return {
        "source": src,
        "fetched": len(figures),
        **tally,
        "sample": [f.to_dict() for f in figures[:10]],
        "caveat": (
            "Stored with the producer's published value + provenance only — no score. "
            "A re-fetch later is a new vintage (revisions preserved). Producers are "
            "compared side by side, never averaged."
        ),
    }


@router.get("/figures")
def figures(
    agency: str | None = Query(None),
    series_id: str | None = Query(None),
    ref_area: str | None = Query(None),
    history: bool = Query(False, description="show every vintage, not just the latest"),
    limit: int = Query(500, ge=1, le=5000),
) -> dict:
    """A filterable read over stored figures (latest vintage unless ``history=1``)."""
    from src.database.session import session_scope
    from src.stats.store import list_figures

    with session_scope() as db:
        return list_figures(
            db, agency=agency, series_id=series_id, ref_area=ref_area,
            latest_vintage_only=not history, limit=limit,
        )


@router.get("/figures/vintages")
def figure_vintages(
    agency: str = Query(...), series_id: str = Query(...),
    ref_area: str = Query(...), time_period: str = Query(...),
) -> dict:
    """Every stored vintage of ONE observation (the revision trail, oldest → newest)."""
    from src.database.session import session_scope
    from src.stats.store import vintages_for

    with session_scope() as db:
        return vintages_for(
            db, agency=agency, series_id=series_id, ref_area=ref_area, time_period=time_period
        )


@router.get("/triangulate")
def triangulate_series(
    series_id: str = Query(...),
    ref_area: str | None = Query(None),
    time_period: str | None = Query(None),
    agencies: str | None = Query(None, description="comma-separated agency codes to include"),
) -> dict:
    """Show the SAME series_id across producers, side by side — never averaged.

    Cross-agency series equivalence is NOT inferred (no fabricated mapping); this
    compares the literal series_id. Incomparable cells (different unit / seasonal
    adjustment / base year) are flagged, never reconciled."""
    from src.database.session import session_scope
    from src.stats.store import triangulate

    ag = [a for a in (agencies or "").split(",") if a.strip()] or None
    with session_scope() as db:
        return triangulate(
            db, series_id=series_id, ref_area=ref_area, time_period=time_period, agencies=ag
        )


@router.get("/sources")
def registered_sources(
    country: str | None = Query(None, description="ISO-2 country filter (lowercase)"),
    region: str | None = Query(None, description="region-slug tag filter, e.g. africa"),
    enabled: bool | None = Query(None),
) -> dict:
    """The registered official-statistics SOURCE rows (ingested as DISABLED, controversial).

    A filterable directory of what has been registered as a source via
    ``/sources/ingest`` — descriptive provenance only (name · domain · country ·
    tags · enabled), NO score/ranking. ``reliability_score`` is never surfaced (it is
    NULL for these by design)."""
    from sqlalchemy import select

    from src.database.models import Source
    from src.database.session import session_scope

    with session_scope() as db:
        q = select(Source).where(Source.source_type == "statistics")
        if country:
            q = q.where(Source.country == country.strip().lower())
        if enabled is not None:
            q = q.where(Source.enabled == enabled)
        rows = list(db.execute(q).scalars())
        if region:
            slug = region.strip().lower()
            rows = [r for r in rows if slug in (r.tags or "").lower()]
        rows.sort(key=lambda r: (r.country or "zz", r.name))
        return {
            "count": len(rows),
            "sources": [
                {
                    "name": r.name,
                    "domain": r.domain,
                    "country": r.country,
                    "region": r.region,
                    "language": r.language,
                    "tags": [t for t in (r.tags or "").split(",") if t],
                    "enabled": bool(r.enabled),
                }
                for r in rows
            ],
            "caveat": (
                "Registered producers (disabled by default) — a STANCED-source "
                "directory, never a credibility ranking. No score is stored or shown."
            ),
        }
