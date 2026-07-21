"""
Scheduler API: start/stop the background ingester, run now, edit its config.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The scheduler runs in-process (a daemon thread); these endpoints are the GUI's
control surface. Status reflects the *real* thread state and the last actual run
result -- never a simulated "healthy".
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.database.models import Source
from src.database.session import get_db
from src.scheduler.coverage import DEFAULT_FRESH_WINDOW_HOURS, tag_coverage
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
    # Continuous collection (default on): passes run back-to-back when online.
    continuous: bool | None = None
    # Bandwidth-governed collection (the user-facing control is download rate):
    #   collect_rate_mode  : "target" | "maximum"
    #   collect_target_kbps: best-effort download-rate goal in KiB/s
    #   collect_parallelism: hard ceiling on concurrent fetches (1 = sequential)
    collect_rate_mode: str | None = None
    collect_target_kbps: int | None = None
    collect_parallelism: int | None = None
    mode: str | None = None
    max_sources_per_run: int | None = None
    crawl_max_depth: int | None = None
    crawl_max_pages: int | None = None
    select_languages: list[str] | None = None
    select_tags: list[str] | None = None
    select_source_types: list[str] | None = None
    # Opt-in drop-folder export (WP3/RM-06); empty string switches it off.
    export_dir: str | None = None
    # Offline discovery budget per run (WP5/RM-19); 0 disables.
    discovery_per_run: int | None = None
    # WORLD discovery ride-along: countries advanced per online pass (2026-07-15
    # "background and automated" ruling); 0 disables. Finds stay DISABLED for review.
    world_discovery_per_pass: int | None = None
    # QUALIFICATION ride-along (0.3 CLOSE GATE ruling): candidate sources trial-fetched +
    # judged per online pass, like the world-discovery ride-along; 0 disables.
    qualification_per_pass: int | None = None
    # Optional per-language cadence lever (default OFF): a {lang: weight} target
    # the operator opts into; {} or omitted keeps the pure random rotation.
    language_equilibrium: dict | None = None
    equilibrium_floor: float | None = None
    # Opt-in per-country PRIORITY LADDER (default OFF): a {country: weight} map so chosen
    # countries scrape FIRST under constrained bandwidth. Orders only, never excludes.
    country_priority: dict | None = None


def _status_payload() -> dict:
    from src.ingest import kill_switch_active

    status = get_scheduler().status()
    status["valid_modes"] = list(VALID_MODES)
    # Network state rides every scheduler response so the UI repaints the
    # airplane toggle IMMEDIATELY on implicit transitions (a collect start
    # clears the kill switch server-side) instead of waiting for the 5 s poll.
    status["online"] = not kill_switch_active()
    return status


@router.get("/status")
def scheduler_status() -> dict:
    """Live scheduler state: running, in-progress, last/next run, last result."""
    return _status_payload()


@router.get("/activity")
def scheduler_activity(db: Session = Depends(get_db)) -> dict:
    """The collection-activity panel (the top-bar chip's detail view): live run
    progress (domains only), the next pass's targets + an honest duration
    estimate (method stated), and per-host transfer rates measured from the
    app's OWN fetches — never OS-wide counters."""
    payload = get_scheduler().activity(db)
    payload["valid_modes"] = list(VALID_MODES)
    return payload


@router.get("/coverage")
def scheduler_coverage(
    fresh_window_hours: int = Query(DEFAULT_FRESH_WINDOW_HOURS, ge=1, le=8760),
    db: Session = Depends(get_db),
) -> dict:
    """Per-tag scraping coverage — which tags have been reached, how many
    sources remain, at what percentage — built only from the collector's own
    fetch timestamps (reach + freshness, never a completion claim or a score).
    """
    return tag_coverage(db, fresh_window_hours=fresh_window_hours)


@router.get("/equilibrium")
def scheduler_equilibrium(db: Session = Depends(get_db)) -> dict:
    """The optional per-language cadence lever (DEFAULT OFF): current corpus
    language shares vs the operator's target, and the resulting pace (re-check
    multiplier per language). Read-only — the target is set via PUT /config.
    """
    from src.scheduler.equilibrium import (
        PRESETS,
        corpus_language_shares,
        language_pace,
        normalize_target,
    )

    s = load_settings()
    shares = corpus_language_shares(db)
    target = normalize_target(s.language_equilibrium)
    pace = language_pace(shares, s.language_equilibrium, floor=s.equilibrium_floor)
    rnd = lambda m: {k: round(v, 4) for k, v in m.items()}  # noqa: E731
    return {
        "enabled": bool(target),
        "floor": s.equilibrium_floor,
        "corpus_shares": rnd(dict(sorted(shares.items(), key=lambda x: -x[1]))),
        "target": rnd(target),
        "pace": rnd(pace),
        "presets": PRESETS,
        "method": (
            "Pace = min(1, target_share / corpus_share) per language, floored; "
            "an over-represented language is re-checked less often. Corpus shares "
            "are stored-article counts by language. Counts only, no score."
        ),
        "caveat": (
            "Off by default. A cadence nudge, never an exclusion — a hard "
            "freshness floor keeps every source re-checked within the cap. The "
            "presets are one dated measure of a contested quantity, not the app’s "
            "opinion; the target is whatever the operator sets."
        ),
    }


@router.post("/start")
def scheduler_start() -> dict:
    """Start the background ingestion loop (the first run begins immediately)."""
    from src.ingest import clear_kill_switch
    from src.scheduler import memguard

    clear_kill_switch()
    # An explicit start is a USER ACTION: release a paused-low-memory latch and
    # try again (the guard re-trips after fresh sustained samples if memory is
    # still genuinely low — a retry, never a permanent override).
    memguard.memory_guard.reset(reason="operator started collection")
    started = get_scheduler().start()
    return {"started": started, **_status_payload()}


@router.post("/stop")
def scheduler_stop() -> dict:
    # KILL SWITCH (§0.5): refuse every further fetch immediately, then stop the
    # loop. The one in-flight request finishes; nothing else leaves the machine.
    from src.ingest import activate_kill_switch

    activate_kill_switch()
    """Stop the background ingestion loop."""
    stopped = get_scheduler().stop()
    return {"stopped": stopped, **_status_payload()}


@router.post("/run-now")
def scheduler_run_now() -> dict:
    from src.ingest import clear_kill_switch
    from src.scheduler import memguard

    clear_kill_switch()
    # A user-triggered run releases a paused-low-memory latch (see /start).
    memguard.memory_guard.reset(reason="operator ran collection now")
    """Trigger one immediate run. Returns started=False if a run is already active."""
    started = get_scheduler().run_now()
    return {"started": started, **_status_payload()}


@router.post("/memory-guard/resume")
def memory_guard_resume() -> dict:
    """Release the paused-low-memory latch explicitly (P0.3 E3 user action).

    The guard re-engages after fresh sustained over-threshold samples if
    memory is still genuinely low — this is a retry, never an override of the
    measurement. Status (incl. the guard's numbers) rides the response.
    """
    from src.scheduler import memguard

    memguard.memory_guard.reset(reason="operator resumed via the API")
    return _status_payload()


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
        # 0 (the default) = UNBOUNDED: every matched source runs. The old
        # min(matched, cap) reported 0 for every default install (cap=0) — a latent bug.
        "will_process_this_run": (
            matched if s.max_sources_per_run <= 0 else min(matched, s.max_sources_per_run)
        ),
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


@router.get("/runs")
def scheduler_runs(limit: int = 20) -> dict:
    """The most recent scheduler run reports (one auditable line per run)."""
    from src.scheduler.runlog import recent_runs

    runs = recent_runs(limit=limit)
    return {"count": len(runs), "runs": runs}
