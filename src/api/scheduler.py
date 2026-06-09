"""
Scheduler API: start/stop the background ingester, run now, edit its config.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The scheduler runs in-process (a daemon thread); these endpoints are the GUI's
control surface. Status reflects the *real* thread state and the last actual run
result -- never a simulated "healthy".
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.database.models import Source
from src.database.session import get_db
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
    select_languages: list[str] | None = None
    select_tags: list[str] | None = None
    select_source_types: list[str] | None = None


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


@router.get("/targets")
def scheduler_targets(db: Session = Depends(get_db)) -> dict:
    """How many (and which) sources the current selection will scrape (rss/crawl).

    Shows the matched count vs total enabled, what will actually run this pass
    (capped by max_sources_per_run), a sample, and a breakdown by language and
    source_type — so "what gets scraped" is never a mystery.
    """
    from collections import Counter

    from src.scheduler.runner import select_sources

    s = load_settings()
    base = select_sources(db, s)
    matched = base.count()
    total_enabled = db.query(Source).filter_by(enabled=True).count()
    sample_rows = base.limit(25).all()
    by_lang: Counter = Counter()
    by_type: Counter = Counter()
    for src in base.all():
        by_lang[(src.language or "?")] += 1
        by_type[(src.source_type or "?")] += 1
    return {
        "mode": s.mode,
        "applies": s.mode in ("rss", "crawl"),
        "matched": matched,
        "total_enabled": total_enabled,
        "will_process_this_run": min(matched, s.max_sources_per_run),
        "max_sources_per_run": s.max_sources_per_run,
        "selection": {
            "languages": s.select_languages,
            "tags": s.select_tags,
            "source_types": s.select_source_types,
        },
        "by_language": dict(by_lang.most_common(20)),
        "by_source_type": dict(by_type.most_common(20)),
        "sample": [
            {
                "name": x.name,
                "domain": x.domain,
                "language": x.language,
                "source_type": x.source_type,
                "has_rss": bool(x.rss_url),
                "tags": [t.strip() for t in (x.tags or "").split(",") if t.strip()],
            }
            for x in sample_rows
        ],
    }


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
