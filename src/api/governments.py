"""Governments tab API (field test 2026-06-22): per-country indicators + the map.

The Governments tab (renamed from World Law) shows per-country data — GDP, population,
life expectancy, labour, public finance + common indices — drawn from the curated
indicator catalog (``src/stats/indicators``) over the existing vintaged ``StatFigure``
store. These endpoints are READS (no network); the ONE networked action is
``POST /load-standard``, which fetches the curated set for ALL countries through the
guarded official-statistics path (airplane-gated, consented in the UI).

Honesty (carried from the stats layer): every value is a STANCED producer's published
figure (World Bank), never a credibility score; a missing value is a published GAP, not
zero; producers are shown, never averaged; public-finance/inequality series are patchy.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.catalog.countries import to_iso2, to_iso3
from src.database.session import get_db, session_scope
from src.jobs.background import BackgroundJob, register_job
from src.stats import indicators as ind
from src.stats.store import list_figures

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/governments", tags=["Governments"])

_CAVEAT = (
    "Each value is a producer's published figure (World Bank), never a credibility "
    "score. A missing value is a published gap, not zero. Public-finance and inequality "
    "series have patchy country coverage by nature."
)
# A generous read bound: one indicator across ~200 countries x ~65 years is well under
# this; it caps a pathological store, never the normal case.
_READ_CAP = 60000


def _figures(db: Session, *, series_id: str | None = None, ref_area: str | None = None) -> list[dict]:
    """Latest-vintage figures for one indicator and/or one country (no network)."""
    return list_figures(
        db, series_id=series_id, ref_area=ref_area, latest_vintage_only=True, limit=_READ_CAP
    )["figures"]


def _latest_by_country(figs: list[dict], *, year: str | None = None) -> tuple[list[dict], list[str]]:
    """Collapse per-indicator figures to ONE value per country (the requested year, or
    the most recent available), plus the sorted years present (for the slider). A None
    value (published gap) is kept as None — never coerced to zero."""
    years = sorted({str(f["time_period"]) for f in figs if f.get("time_period")})
    by_country: dict[str, dict] = {}
    for f in figs:
        iso3 = (f.get("ref_area") or "").upper()
        # The choropleth + Intl.DisplayNames key on alpha-2; WB stores alpha-3. A
        # non-country AGGREGATE (WLD/EUU/ARB...) has no alpha-2 -> dropped, never mapped.
        iso2 = to_iso2(iso3)
        period = str(f.get("time_period") or "")
        if not iso2 or not period:
            continue
        if year and period != str(year):
            continue
        prev = by_country.get(iso2)
        # keep the most recent period per country (when no specific year is asked)
        if prev is None or period > str(prev["year"]):
            by_country[iso2] = {"country": iso2, "iso3": iso3, "value": f.get("value"), "year": period}
    return list(by_country.values()), years


@router.get("/indicators")
def list_indicators() -> dict:
    """The curated per-country indicator catalog (codes are stable; the data is fetched
    live + vintaged elsewhere). Counts only, no score."""
    return {
        "indicators": ind.INDICATOR_CATALOG,
        "catalog_revised": ind.CATALOG_REVISED,
        "agency": ind.AGENCY,
        "caveat": _CAVEAT,
    }


@router.get("/map")
def map_data(indicator: str, year: str | None = None, db: Session = Depends(get_db)) -> dict:
    """Per-country value for ONE indicator (the choropleth feed): the requested ``year``
    or the latest available per country, plus the years present (the history slider)."""
    meta = ind.indicator_meta(indicator)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"unknown indicator: {indicator!r}")
    figs = _figures(db, series_id=indicator)
    by_country, years = _latest_by_country(figs, year=year)
    return {
        "indicator": meta,
        "year": year,
        "years": years,
        "by_country": by_country,
        "located": len(by_country),
        "caveat": _CAVEAT,
    }


@router.get("/country/{iso}")
def country_data(iso: str, history: int = 30, db: Session = Depends(get_db)) -> dict:
    """All curated indicators for ONE country: the latest value + a bounded history
    series per indicator (for the per-country sparklines). Indicators with no stored
    figures are reported with a null latest (a published/unfetched gap, never zero)."""
    # Accept alpha-2 OR alpha-3; the stored ref_area is alpha-3 (WB), so query that form.
    iso3 = to_iso3(iso) or (iso or "").strip().upper()
    if not iso3:
        raise HTTPException(status_code=422, detail="a country ISO code is required")
    figs = _figures(db, ref_area=iso3)
    by_series: dict[str, list[dict]] = {}
    for f in figs:
        by_series.setdefault(f.get("series_id") or "", []).append(f)
    out: list[dict] = []
    for meta in ind.INDICATOR_CATALOG:
        rows = sorted(
            (f for f in by_series.get(meta["id"], []) if f.get("time_period")),
            key=lambda f: str(f["time_period"]),
        )
        series = [{"year": str(f["time_period"]), "value": f.get("value")} for f in rows]
        # latest = the most recent NON-NULL value (a published gap doesn't mask the value)
        latest = next((s for s in reversed(series) if s["value"] is not None), None)
        out.append({
            **meta,
            "latest": latest,                       # {year, value} or None
            "series": series[-max(1, history):] if series else [],
        })
    return {"country": iso3, "iso2": to_iso2(iso3), "indicators": out, "caveat": _CAVEAT}


class LoadStandardBody(BaseModel):
    indicators: list[str] | None = None  # subset of the catalog; None/empty = all curated


def _fetch_and_store_indicator(db: Session, code: str) -> dict:
    """One indicator's fetch + vintaged store + subscription record, for ALL countries.

    Shared by the manual ``/load-standard`` worker and the automatic scheduler
    ride-along (2026-07-24 §2) so both paths behave identically. Raises ``RuntimeError``
    UNCHANGED on a kill-switch refusal (the caller decides whether that means "stop the
    whole batch"); any OTHER failure is caught here and returned as an honest
    ``{"status": "error", ...}`` record — degrade loudly, never raise, never fabricate a
    figure. Does not commit — the caller controls transaction boundaries."""
    from src.stats import fetch as statfetch
    from src.stats.store import store_figures

    try:
        figures = statfetch.fetch_worldbank(code, "all")
    except RuntimeError:
        raise  # the kill-switch up-front refusal — let the caller stop the whole batch
    except Exception as exc:  # noqa: BLE001 - transport/decode: degrade loudly, continue
        logger.warning("indicator fetch failed for %s", code, exc_info=True)
        return {"indicator": code, "status": "error", "detail": str(exc)[:200]}
    tally = store_figures(db, figures)
    try:
        from src.stats.subscriptions import record_subscription

        record_subscription(db, source="worldbank", indicator=code, country="all")
    except Exception:  # noqa: BLE001 - tracking is additive, never blocks the fetch
        pass
    return {"indicator": code, "status": "ok", "fetched": len(figures), **tally}


def _load_standard_worker(ctx, *, wanted: list[str]) -> dict:
    """The governments load, off the request thread (field test 2026-07-08, Item 8 P1).

    Commits PER INDICATOR so the single-writer gate is taken+released between indicators
    (collection interleaves) instead of being held for the whole 2.9 min run — a genuine
    fix over the old one-transaction handler — and so the Governments tab sees data appear
    progressively. Cancellable between indicators; each indicator's failure degrades loudly
    (recorded), never aborts the set or fabricates a figure."""
    per_indicator: list[dict] = []
    total_fetched = total_stored = 0
    complete = True  # False if we stop early (cancel / airplane refusal) — an HONEST partial
    ctx.set_progress(done=0, total=len(wanted), detail="starting")
    with session_scope() as db:
        for i, code in enumerate(wanted):
            if ctx.stopping:
                complete = False
                break
            ctx.set_progress(detail=f"fetching {code}")
            try:
                rec = _fetch_and_store_indicator(db, code)
            except RuntimeError as exc:  # the kill-switch up-front refusal
                per_indicator.append({"indicator": code, "status": "refused", "detail": str(exc)})
                complete = False
                break  # airplane mode: stop — every subsequent fetch would refuse too
            per_indicator.append(rec)
            if rec["status"] == "ok":
                total_fetched += rec.get("fetched", 0)
                total_stored += rec.get("stored", 0)
            db.commit()  # release the writer gate between indicators (arbitrate w/ collect)
            ctx.set_progress(done=i + 1)
    return {
        "requested": wanted,
        "fetched": total_fetched,
        "stored": total_stored,
        "complete": complete,  # honest: did it finish the whole set, or stop early?
        "per_indicator": per_indicator,
        "caveat": _CAVEAT,
    }


# cancellable=True: the worker checks ctx.stopping between indicators, so the task-manager
# Cancel button is HONEST (it stops at the next indicator). store_figures is idempotent per
# vintage, so a partial run + re-run never double-counts.
_GOV_JOB = register_job(
    BackgroundJob(
        "governments", "Loading government statistics", _load_standard_worker,
        is_writer=True, cancellable=True,
    )
)


@router.post("/load-standard")
def load_standard(body: LoadStandardBody | None = None) -> dict:
    """Fetch the curated indicator set for ALL countries (the one-click "load country
    data") as a BACKGROUND JOB — returns immediately with the job status instead of
    freezing the app for ~3 min (field test 2026-07-08, Item 4 + Item 8 P1). The ONE
    networked action: refuses up front under airplane mode (409, never a traceback); the
    worker routes through the guarded factory, stores each as a vintaged figure, records a
    subscription so the scheduler auto-refreshes new vintages, and commits per indicator so
    collection is never blocked for the whole run. Poll ``/load-standard/status`` or the
    task manager (``/api/jobs``) for progress; the tab reads stored figures as they land."""
    from src.ingest import kill_switch_active

    wanted = [c for c in (body.indicators if body else None) or ind.indicator_ids() if ind.is_curated(c)]
    if not wanted:
        raise HTTPException(status_code=422, detail="no curated indicators selected")
    # Refuse up front, before starting the job, so airplane mode is a clean 409.
    if kill_switch_active():
        raise HTTPException(status_code=409, detail="network refused: airplane mode is engaged")
    try:
        return {"started": True, "job": _GOV_JOB.start(wanted=wanted)}
    except RuntimeError:
        # Already running — return the live status rather than 409 (idempotent button).
        return {"started": False, "job": _GOV_JOB.status()}


@router.get("/load-standard/status")
def load_standard_status() -> dict:
    """Live status of the background government-statistics load (state/progress/error)."""
    return _GOV_JOB.status()


def advance_country_data(session: Session, *, per_pass: int = 2) -> dict:
    """Scheduler ride-along (2026-07-24 field-feedback Session A §2, ruled): bootstrap
    the curated country-indicator catalog AUTOMATICALLY in the background, a few
    indicators per online collection pass, instead of requiring the user to click
    "Load standard country data" once before any Governments-tab figures exist.

    Reuses ``_fetch_and_store_indicator`` (the SAME fetch + vintaged-store + subscription
    path ``/load-standard`` uses) so both the manual button and this ride-along behave
    identically. Ongoing REFRESH of an already-loaded indicator's vintage is already
    handled elsewhere in this same pass by ``stats.subscriptions.refresh_due`` (which
    replays every DUE ``StatSubscription``) — this function only covers the FIRST load of
    an indicator that has never been fetched at all (no subscription for it yet), so the
    two never duplicate work. Honest named skips: a manual load already running, airplane
    mode, or (once every curated indicator has a subscription) nothing left to bootstrap.
    Best-effort — a single indicator's failure is recorded and never breaks the pass."""
    if per_pass <= 0:
        return {"enabled": False}
    if _GOV_JOB.status().get("state") == "running":
        return {"enabled": True, "skipped": "a manual load is already running"}
    from src.ingest import kill_switch_active

    if kill_switch_active():
        return {"enabled": True, "skipped": "airplane mode"}

    from sqlalchemy import select

    from src.database.models import StatSubscription

    already = {
        row[0]
        for row in session.execute(
            select(StatSubscription.indicator).where(
                StatSubscription.source == "worldbank", StatSubscription.country == "all"
            )
        ).all()
    }
    pending = [c for c in ind.indicator_ids() if c not in already][: max(0, int(per_pass))]
    if not pending:
        return {"enabled": True, "skipped": "the whole catalog is already bootstrapped"}

    per_indicator: list[dict] = []
    fetched_total = stored_total = 0
    for code in pending:
        try:
            rec = _fetch_and_store_indicator(session, code)
        except RuntimeError as exc:  # airplane mode toggled mid-loop — a concurrent race
            per_indicator.append({"indicator": code, "status": "refused", "detail": str(exc)})
            break  # every subsequent fetch would refuse too
        per_indicator.append(rec)
        if rec["status"] == "ok":
            fetched_total += rec.get("fetched", 0)
            stored_total += rec.get("stored", 0)
        session.commit()  # release the writer gate between indicators, like the manual load
    return {
        "enabled": True,
        "started": bool(per_indicator),
        "fetched": fetched_total,
        "stored": stored_total,
        "per_indicator": per_indicator,
    }
