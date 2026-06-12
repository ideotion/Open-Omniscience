"""
Weather-context endpoint — the consented fetch behind the corroboration cards.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

POST /api/weather/context fetches ONE bounded (place, window) Open-Meteo
reanalysis slice. It exists solely as the target of the Home card's
"Fetch weather context" button: the UI passes through the one consent popup
(``ensureOnline``) first, and the fetch itself goes through the single
ethical fetch path (kill switch, robots fail-closed, protected-mode proxy).
Transport failures return honest verdicts (the T4 taxonomy), never a crash.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator, model_validator

from src.weather.openmeteo import (
    ALLOWED_DAILY,
    ARCHIVE_FLOOR,
    MAX_WINDOW_DAYS,
    fetch_daily_slice,
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
    """One bounded reanalysis slice; cache-aware; verdicts instead of crashes."""
    return fetch_daily_slice(
        req.lat, req.lon, req.start_date, req.end_date, req.variables,
        label=req.label, force=req.force,
    )
