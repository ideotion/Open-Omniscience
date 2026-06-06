"""
Scheduler API: start/stop the background ingester, run now, edit its config.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The scheduler runs in-process (a daemon thread); these endpoints are the GUI's
control surface. Status reflects the *real* thread state and the last actual run
result -- never a simulated "healthy".
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.scheduler.runner import get_scheduler
from src.scheduler.settings import (
    VALID_MODES,
    SchedulerSettingsError,
    load_settings,
    save_settings,
)

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


class SchedulerConfigUpdate(BaseModel):
    autostart: bool | None = None
    interval_minutes: int | None = None
    mode: str | None = None
    max_sources_per_run: int | None = None
    crawl_max_depth: int | None = None
    crawl_max_pages: int | None = None


def _status_payload() -> dict:
    status = get_scheduler().status()
    status["valid_modes"] = list(VALID_MODES)
    return status


@router.get("/status")
def scheduler_status() -> dict:
    """Live scheduler state: running, in-progress, last/next run, last result."""
    return _status_payload()


@router.post("/start")
def scheduler_start() -> dict:
    """Start the background ingestion loop (the first run begins immediately)."""
    started = get_scheduler().start()
    return {"started": started, **_status_payload()}


@router.post("/stop")
def scheduler_stop() -> dict:
    """Stop the background ingestion loop."""
    stopped = get_scheduler().stop()
    return {"stopped": stopped, **_status_payload()}


@router.post("/run-now")
def scheduler_run_now() -> dict:
    """Trigger one immediate run. Returns started=False if a run is already active."""
    started = get_scheduler().run_now()
    return {"started": started, **_status_payload()}


@router.get("/config")
def scheduler_config() -> dict:
    """Current scheduler configuration plus the set of valid modes."""
    return {**load_settings().to_dict(), "valid_modes": list(VALID_MODES)}


@router.put("/config")
def scheduler_update_config(update: SchedulerConfigUpdate) -> dict:
    """Apply a partial config update (validated; a running loop picks up changes)."""
    try:
        save_settings(update.model_dump(exclude_unset=True))
    except SchedulerSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**load_settings().to_dict(), "valid_modes": list(VALID_MODES)}
