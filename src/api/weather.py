"""
Weather-context endpoint — the consented fetch behind the corroboration cards.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

POST /api/weather/context fetches ONE bounded (place, window) Open-Meteo
reanalysis slice. It exists solely as the target of the Home card's
"Fetch weather context" button: the UI asks first (the one consent popup,
naming the rounded place and the host) and sends ``consent: true``; the
endpoint refuses a fetch without it and under the kill switch, and the fetch
itself goes through the single ethical fetch path (kill switch, robots
fail-closed, protected-mode proxy). A slice already held answers locally.
Transport failures return honest verdicts (the T4 taxonomy), never a crash.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator

from src.weather.openmeteo import (
    ALLOWED_DAILY,
    ARCHIVE_FLOOR,
    MAX_WINDOW_DAYS,
    build_archive_url,
    fetch_daily_slice,
    read_cached_slice,
)

router = APIRouter(prefix="/api/weather", tags=["weather"])


class WeatherContextRequest(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    start_date: date
    end_date: date
    variables: list[str] = Field(
        default_factory=lambda: ["precipitation_sum", "temperature_2m_max",
                                 "temperature_2m_min"]
    )
    label: str | None = Field(default=None, max_length=200)
    force: bool = False
    #: Must be true for a fetch (R683, invariant #14f): it sends the (rounded) place to Open-Meteo.
    consent: bool = False

    @field_validator("variables")
    @classmethod
    def _vars_allowed(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("at least one daily variable is required")
        bad = sorted(set(v) - ALLOWED_DAILY)
        if bad:
            raise ValueError(f"unknown daily variables {bad}; allowed: {sorted(ALLOWED_DAILY)}")
        return v

    @model_validator(mode="after")
    def _window_bounds(self) -> WeatherContextRequest:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        if (self.end_date - self.start_date).days > MAX_WINDOW_DAYS:
            raise ValueError(f"window is bounded to {MAX_WINDOW_DAYS} days per fetch")
        if self.start_date < ARCHIVE_FLOOR:
            raise ValueError(f"the reanalysis archive starts {ARCHIVE_FLOOR.isoformat()}")
        if self.end_date > date.today():
            raise ValueError("end_date is in the future — reanalysis is historical only")
        return self


@router.post("/context")
def weather_context(req: WeatherContextRequest) -> dict:
    """One bounded reanalysis slice; verdicts instead of crashes (R683).

    A slice already held is answered locally, with no consent needed and in airplane mode too.
    Anything else EGRESSES: refused while the kill switch is engaged, and without ``consent``.
    The place is rounded to 0.1 degree before it is sent or kept."""
    from src.ingest import kill_switch_active
    from src.ingest.fetch_verdict import NETWORK_REFUSED

    if not req.force:
        held = read_cached_slice(
            build_archive_url(req.lat, req.lon, req.start_date, req.end_date, req.variables))
        if held is not None:
            return {**held, "cached": True, "label": req.label}
    if kill_switch_active():
        raise HTTPException(status_code=409, detail=NETWORK_REFUSED)
    if not req.consent:
        raise HTTPException(status_code=400, detail="consent required: this sends the place's rounded coordinates to Open-Meteo")
    return fetch_daily_slice(
        req.lat, req.lon, req.start_date, req.end_date, req.variables,
        label=req.label, force=True,
    )


class WeatherAnomalyRequest(WeatherContextRequest):
    """Same WINDOW bounds as a context fetch; the 1991-2020 baseline is fixed server-side.

    ``consent`` (inherited) must be true (R675, invariant #14f): this sends the (rounded) place to Open-Meteo."""

    @field_validator("variables")
    @classmethod
    def _vars_allowed(cls, v: list[str]) -> list[str]:
        from src.weather.anomaly import SUPPORTED

        if not v:
            raise ValueError("at least one daily variable is required")
        bad = sorted(set(v) - set(SUPPORTED))
        if bad:
            raise ValueError(f"no anomaly definition for {bad}; supported: {sorted(SUPPORTED)}")
        return list(dict.fromkeys(v))


@router.post("/anomaly")
def weather_anomaly(req: WeatherAnomalyRequest) -> dict:
    """Anomalies against the stated 1991-2020 baseline (EGRESSES, R675). The place is rounded
    before it is sent; the slices not held yet (the 30-year baseline once per place, then the
    window) are fetched and kept in the encrypted store."""
    from src.ingest import kill_switch_active
    from src.ingest.fetch_verdict import NETWORK_REFUSED
    from src.weather.anomaly import fetch_anomalies

    if kill_switch_active():
        raise HTTPException(status_code=409, detail=NETWORK_REFUSED)
    if not req.consent:
        raise HTTPException(status_code=400, detail="consent required: this sends the place's rounded coordinates to Open-Meteo")
    return fetch_anomalies(req.lat, req.lon, req.start_date, req.end_date, req.variables,
                           force=req.force)


@router.get("/anomaly/held")
def weather_anomaly_held(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    start_date: date = Query(),
    end_date: date = Query(),
) -> dict:
    """The same anomalies from slices already held on this machine. Never fetches (R675): a
    slice not held is named in ``missing``, so a re-view works in airplane mode."""
    from pydantic import ValidationError

    from src.weather.anomaly import held_anomalies

    try:
        WeatherAnomalyRequest(lat=lat, lon=lon, start_date=start_date, end_date=end_date)
    except ValidationError as exc:
        from src.monitoring.secret_scrub import http_detail

        raise HTTPException(status_code=422, detail=http_detail(exc)) from None
    return held_anomalies(lat, lon, start_date, end_date)
