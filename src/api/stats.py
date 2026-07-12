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
    included alongside Western producers + IGOs). An official figure is a STANCED
    source — stated as a descriptive caveat, never a per-source verdict label and
    never a score (ruling #50: the user judges). Descriptive only: no figures, no
    ranking, no network. ``continents_covered`` is an honest coverage metric (the
    ruling measures coverage, never assumes it)."""
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
    """Register the curated statistical producers as DISABLED sources.

    Each agency is added to the source catalog as a ``source_type="statistics"``
    Source, carrying the ``official-statistics`` + region tags (NO "controversial"
    verdict tag — ruling #50: an official figure is a STANCED source, stated as a
    caveat, but the user judges). Rows are created DISABLED — registered, NOT
    scraped: official machine endpoints (SDMX / APIs)
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
    optional ``country``); ``eurostat`` / any SDMX-JSON producer (needs ``dataset``
    + optional ``params``; ``agency`` defaults to ``eurostat`` but can name another
    SDMX-JSON producer, e.g. ``imf``); or ``owid`` (Our World in Data — needs a chart
    ``slug``, optional ``value_col`` [auto-detected for a single-metric chart] +
    optional ``unit`` since OWID CSVs carry no machine-readable unit). The fetch
    egresses over the user's configured transport and is REFUSED while airplane mode
    is engaged.
    """

    source: str = Field(..., description="worldbank | eurostat (SDMX-JSON) | owid (CSV)")
    indicator: str | None = Field(None, description="World Bank indicator id, e.g. NY.GDP.MKTP.CD")
    country: str = Field("all", description="World Bank country code or 'all'")
    dataset: str | None = Field(None, description="SDMX dataset id, e.g. nama_10_gdp")
    params: dict[str, str] | None = Field(None, description="extra SDMX query params")
    agency: str | None = Field(None, description="SDMX producer agency code (default eurostat)")
    slug: str | None = Field(None, description="OWID grapher chart slug, e.g. co2-emissions-per-capita")
    value_col: str | None = Field(None, description="OWID value column (auto-detected if a single metric)")
    unit: str | None = Field(None, description="OWID unit (carried verbatim; OWID CSVs state none)")
    url: str | None = Field(None, description="JSON-stat endpoint URL (Eurostat JSON-stat / IRENA / PxWeb)")
    series_id: str | None = Field(None, description="pin a single JSON-stat series slice for unambiguous rows")


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
        elif src == "owid":
            if not (body.slug and body.slug.strip()):
                raise HTTPException(status_code=422, detail="owid fetch needs a 'slug'")
            try:
                figures = statfetch.fetch_owid(
                    body.slug, value_col=body.value_col, unit=body.unit
                )
            except ValueError as exc:  # ambiguous value column → ask the caller to name it
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        elif src in ("jsonstat", "json-stat", "pxweb"):
            if not (body.url and body.url.strip()):
                raise HTTPException(
                    status_code=422,
                    detail="jsonstat fetch needs a 'url' (the producer's JSON-stat endpoint)",
                )
            try:
                figures = statfetch.fetch_jsonstat(
                    body.url,
                    agency=(body.agency or "jsonstat").strip().lower(),
                    series_id=body.series_id,
                )
            except ValueError as exc:  # not an http(s) url → a clean 422
                raise HTTPException(status_code=422, detail=str(exc)) from exc
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
        # Record this fetch as a TRACKED subscription so the scheduler can replay it
        # for new vintages (ruling #12). Idempotent; best-effort (never fail the fetch).
        # owid auto-refresh is a follow-on (the replay can't reconstruct a slug fetch yet),
        # so only the SDMX/WB families are tracked here — never record an unreplayable sub.
        if src in ("worldbank", "eurostat", "sdmx"):
            try:
                from src.stats.subscriptions import record_subscription

                record_subscription(
                    db, source=src, indicator=body.indicator, country=body.country,
                    dataset=body.dataset, params=body.params,
                    agency=(body.agency or "eurostat") if src in ("eurostat", "sdmx") else None,
                )
            except Exception:  # noqa: BLE001 - tracking is additive, never blocks the fetch
                pass
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


@router.get("/subscriptions")
def list_stat_subscriptions() -> dict:
    """Tracked fetches the scheduler replays for new vintages (ruling #12)."""
    from src.database.session import session_scope
    from src.stats.subscriptions import list_subscriptions

    with session_scope() as db:
        subs = list_subscriptions(db)
    return {
        "count": len(subs),
        "subscriptions": subs,
        "caveat": (
            "Each tracked fetch is replayed every interval_days while you are online, "
            "storing a new VINTAGE — revisions are preserved, never overwritten. No score."
        ),
    }


class StatSubPatch(BaseModel):
    enabled: bool | None = None
    interval_days: int | None = Field(None, ge=1, le=3650)


@router.patch("/subscriptions/{sub_id}")
def patch_stat_subscription(sub_id: int, body: StatSubPatch) -> dict:
    from src.database.session import session_scope
    from src.stats.subscriptions import set_subscription

    with session_scope() as db:
        s = set_subscription(db, sub_id, **body.model_dump(exclude_none=True))
        if s is None:
            raise HTTPException(status_code=404, detail="no such subscription")
        return {"id": s.id, "enabled": bool(s.enabled), "interval_days": s.interval_days}


@router.delete("/subscriptions/{sub_id}")
def delete_stat_subscription(sub_id: int) -> dict:
    from src.database.session import session_scope
    from src.stats.subscriptions import delete_subscription

    with session_scope() as db:
        if not delete_subscription(db, sub_id):
            raise HTTPException(status_code=404, detail="no such subscription")
        return {"deleted": sub_id}


@router.post("/subscriptions/refresh")
def refresh_stat_subscriptions() -> dict:
    """Replay DUE subscriptions now (also runs automatically in the scheduler markets pass).

    Airplane-gated: opens NO socket while the kill switch is engaged (returns the count
    as skipped_offline). Best-effort per subscription."""
    from src.database.session import session_scope
    from src.stats.subscriptions import refresh_due

    with session_scope() as db:
        return refresh_due(db)


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


@router.get("/minerals-supply")
def minerals_supply() -> dict:
    """USGS Mineral Commodity Summaries SUPPLY data grouped by commodity → measure.

    The honest surface for minerals with no free spot-price source (rare earths, B12):
    production / reserves / net-import-reliance, NEVER prices. Empty until the operator
    runs the USGS MCS fetch — the response says so loudly (``available: false`` + reason).
    """
    from src.database.session import session_scope
    from src.stats.store import minerals_supply_summary

    with session_scope() as db:
        return minerals_supply_summary(db)


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


@router.get("/figures/series")
def figure_series(
    series_id: str = Query(...),
    ref_area: str = Query(...),
    agency: str | None = Query(None, description="scope to one producer (recommended)"),
) -> dict:
    """An honest, comparability-segmented time series for ONE (series_id, ref_area) — the
    feed for a stat chart (the src/stats/series.py to_chart_series output).

    A new line segment starts at every unit / base-year / seasonal-adjustment change (values
    across a break are never joined), a published gap is kept as null (the chart breaks the
    line, never interpolates), and periods that can't be placed are listed separately. Scope
    by ``agency`` for a single producer; omit only when one producer publishes this series
    (use /triangulate to compare producers). Counts only, no score."""
    from src.database.session import session_scope
    from src.stats.store import chart_series

    with session_scope() as db:
        return chart_series(db, series_id=series_id, ref_area=ref_area, agency=agency)


@router.get("/map")
def figure_map(
    series_id: str = Query(...),
    agency: str | None = Query(None, description="pin one producer (recommended if several report)"),
    time_period: str | None = Query(None, description="pin a period; default = each area's latest"),
    limit: int = Query(2000, ge=1, le=5000),
) -> dict:
    """Latest-vintage figures for ONE series across all areas — the choropleth feed.

    One cell per ``ref_area`` (the area's latest period unless ``time_period`` is pinned),
    each carrying the producer's published value + its comparability fields. The frontend
    ``ooViz.choroplethData`` applies the honesty gate: an area on a different unit /
    base-year / seasonal-adjustment basis is shown as no-data (never recoloured to one
    scale), a gap is no-data (never zero), and a LEVEL indicator is shown as proportional
    symbols not colour. A map is single-producer — pin ``agency`` when several report the
    series; the map never averages producers. Counts only, no score."""
    from src.database.session import session_scope
    from src.stats.store import map_figures

    with session_scope() as db:
        return map_figures(
            db, series_id=series_id, agency=agency, time_period=time_period, limit=limit
        )


@router.get("/revision-anomalies")
def revision_anomalies_view(
    agency: str | None = Query(None),
    series_id: str | None = Query(None),
    ref_area: str | None = Query(None),
    min_prior_revisions: int = Query(4, ge=2, le=50),
    z_min: float = Query(3.5, ge=1.0, le=20.0),
) -> dict:
    """Observations whose MOST RECENT vintage revised a past figure unusually far for that
    series' own revision history — the reliable-memory check.

    History must not be silently rewritten. This is RETROSPECTIVE (it flags a revision that
    already happened across stored vintages, never a forecast) and names the SHAPE (an
    outlier-sized revision), never the intent — the innocent twin (a benchmark/methodology
    update, a late source, a correction) travels in the caveat. Magnitudes only, no score."""
    from src.database.session import session_scope
    from src.stats.store import revision_anomalies

    with session_scope() as db:
        return revision_anomalies(
            db,
            agency=agency,
            series_id=series_id,
            ref_area=ref_area,
            min_prior_revisions=min_prior_revisions,
            z_min=z_min,
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
    """The registered official-statistics SOURCE rows (ingested as DISABLED; no verdict tag).

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
