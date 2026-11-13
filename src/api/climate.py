"""The Climate tab's API: what this install holds, the series to draw, and the one click that fetches.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

ONE route egresses, and it is the only one gated: ``POST /fetch`` runs one climate fetch unit
(``src/stats/climate.py``) through its guarded fetcher. It refuses with a 409 that NAMES airplane
mode (invariant #14e's corollary), with a 422 on a malformed station id or param BEFORE anything
is sent, and with a 400 unless the caller says ``consent: true``: the UI passes the ONE network
consent first, and a caller that never opened the UI meets the same refusal (invariant #14f). The
fetch runs as a background job, so the task manager shows it and one run at a time is a fact of
the job kind. Every other route reads the local database and makes no request.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.jobs.background import BackgroundJob, register_job
from src.monitoring.secret_scrub import http_detail

router = APIRouter(prefix="/api/climate", tags=["climate"])


def _fetch_worker(ctx, *, dataset: str, param: str | None) -> dict:
    from src.database.session import session_scope
    from src.stats.climate import fetch_and_store

    steps = {"fetching": 0, "storing": 1}

    def progress(step: str) -> None:
        ctx.set_progress(done=steps.get(step, 0), total=2, detail=step)

    with session_scope() as db:
        record = fetch_and_store(db, dataset, param, progress=progress)
    return {
        "dataset": record["dataset"],
        "param": record["param"],
        "fetched_at": record["fetched_at"],
        "figures": record["figures"],
        "tally": record["tally"],
    }


#: A WRITER: it commits figures and the fetch record to the corpus file, so the offline
#: maintenance hold-off must see it. NOT cancellable, honestly: each download is a blocking GET
#: with no stop flag to check, and a Cancel button that did nothing would be theater.
_FETCH_JOB = register_job(
    BackgroundJob("climate-fetch", "Fetching a climate dataset", _fetch_worker, is_writer=True, cancellable=False)
)


class _FetchBody(BaseModel):
    dataset: str
    param: str | None = None
    consent: bool = False


def _unit(dataset: str, param: str | None) -> str | None:
    from src.stats.climate import valid_param

    try:
        return valid_param(dataset, param)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=http_detail(exc)) from exc


@router.get("/datasets")
def climate_datasets() -> dict:
    """Every fetch unit and what this install holds for it. Local only: nothing is requested."""
    from src.database.session import session_scope
    from src.stats.climate import DATASETS, areas, unit_status

    units = []
    with session_scope() as db:
        for ds in DATASETS.values():
            if ds.id == "ghcnd":
                for st in areas(db, "ghcnd", None):
                    units.append(unit_status(db, "ghcnd", st["code"]))
                continue
            for param in ds.params or (None,):
                units.append(unit_status(db, ds.id, param))
    return {
        "units": units,
        # Every dataset's publisher host, also for a dataset with nothing stored yet: the consent
        # popup names it on the very first fetch (a GHCN station has no unit until one is stored).
        "hosts": {ds.id: ds.host for ds in DATASETS.values()},
        "method": "Read from this install's own database; nothing is requested from the network.",
    }


@router.get("/series")
def climate_series(
    dataset: str = Query(...),
    series_id: str = Query(...),
    area: str = Query(...),
    param: str | None = Query(None),
) -> dict:
    """The latest stored vintage per period of one series, for the chart. Local only."""
    from src.database.session import session_scope
    from src.stats.climate import area_for, read_series, series_ids_for

    p = _unit(dataset, param)
    if series_id not in series_ids_for(dataset, p):
        raise HTTPException(status_code=404, detail="not a series of this climate dataset")
    fixed = area_for(dataset, p)
    if fixed is not None and area != fixed:
        raise HTTPException(status_code=404, detail="not an area of this climate dataset")
    with session_scope() as db:
        return read_series(db, dataset, series_id, area[:64])


@router.get("/areas")
def climate_areas(dataset: str = Query(...), param: str | None = Query(None)) -> dict:
    """The areas (OWID) or stations (GHCN) this install holds for a dataset. Local only."""
    from src.database.session import session_scope
    from src.stats.climate import DATASETS, areas

    if dataset not in DATASETS:
        raise HTTPException(status_code=422, detail="unknown climate dataset")
    # Listing the stations needs no station; every other dataset's param is checked as usual.
    p = None if dataset == "ghcnd" else _unit(dataset, param)
    with session_scope() as db:
        return {"dataset": dataset, "param": p, "areas": areas(db, dataset, p)}


@router.post("/fetch")
def climate_fetch(body: _FetchBody) -> dict:
    """Fetch one climate unit live (EGRESSES) and store new or revised observations (R662)."""
    from src.ingest import kill_switch_active
    from src.ingest.fetch_verdict import NETWORK_REFUSED

    param = _unit(body.dataset, body.param)
    if kill_switch_active():
        raise HTTPException(status_code=409, detail=NETWORK_REFUSED)
    if not body.consent:
        raise HTTPException(status_code=400, detail="consent required: this sends a request to the dataset's publisher")
    try:
        return {"started": True, "job": _FETCH_JOB.start(dataset=body.dataset, param=param)}
    except RuntimeError:
        # Already running: the live status, not an error, so a double click is harmless.
        return {"started": False, "job": _FETCH_JOB.status()}


@router.get("/fetch/status")
def climate_fetch_status() -> dict:
    """Live status of the climate fetch job (state, progress, result, error)."""
    return _FETCH_JOB.status()
