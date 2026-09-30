"""
Idle maintenance for an instance that is NOT collecting (airplane mode).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE GAP THIS CLOSES (keyword session, 2026-09-30). The off-peak maintenance window --
counter reconcile, the orphan-keyword prune, the keyword-language reconcile, the
incremental vacuum, the hourly library snapshot -- is run by
:meth:`BackgroundScheduler._run_off_peak_maintenance`, which is called from exactly one
place: the scheduler's own collection loop. The app boots in airplane mode and starts
no scheduler until the operator crosses online, and going offline stops it again. So an
instance that lives offline -- the one that imports backups and re-indexes them, the
big one -- got NONE of that maintenance, ever: the field bundle read
``auto_cleanup.last_run: null`` AND ``auto_incremental_vacuum.last_run: null`` while
7.9 M of 9.5 M keyword rows had no mention.

This runs the SAME window on a slow timer, but ONLY while the scheduler loop is not
running (the loop owns it otherwise), and yields -- recording why -- to anything that
already owns the machine: an import's exclusive window, a re-index drain, any
registered writer job. It changes WHEN the existing maintenance runs, never WHAT it does
or how honestly it reports; the freshness gates, the deadline budgets and the
``complete: false`` disclosure are all the maintenance's own. No network is touched.

``OO_OFFLINE_MAINTENANCE=0`` declines it for one process;
``OO_OFFLINE_MAINT_INTERVAL_S`` sets the cadence (default 300 s, the loop's own cadence, floor 60 s).
"""

from __future__ import annotations

import logging
import os
import threading

_LOG = logging.getLogger("scheduler.offline_maintenance")

#: Let boot settle first: the unlock path's upkeep, the cache warm and a boot re-index
#: resume all start in the first minutes and this must never compete with them.
_FIRST_TICK_DELAY_S = 180.0

_THREAD: threading.Thread | None = None
_STOP = threading.Event()
_LOCK = threading.Lock()


def enabled() -> bool:
    return os.environ.get("OO_OFFLINE_MAINTENANCE", "1").strip() != "0"


def interval_s() -> float:
    try:
        return max(60.0, float(os.environ.get("OO_OFFLINE_MAINT_INTERVAL_S", "300")))
    except ValueError:
        return 300.0


def yield_reason(sched) -> str | None:
    """Why this tick must NOT run maintenance, or ``None`` when it may.

    Order matters only for the label: the scheduler loop first (it owns the window and
    its own throttle), then an exclusive operation, then a running writer job."""
    if sched.is_running():
        return "offline_loop_owns_window"
    try:
        from src.scheduler.runner import owns_the_machine

        if owns_the_machine():
            return "offline_exclusive_operation"
    except Exception:  # noqa: BLE001 - unknown ownership is treated as owned
        return "offline_ownership_unknown"
    try:
        from src.analytics.reindex_job import get_reindex_manager

        if (get_reindex_manager().status() or {}).get("state") == "running":
            return "offline_reindex_running"
    except Exception:  # noqa: BLE001 - a status read must not decide for us
        return "offline_reindex_unreadable"
    try:
        from src.jobs.background import all_job_statuses

        for st in all_job_statuses():
            if st.get("running") and st.get("is_writer"):
                return "offline_writer_job_running"
    except Exception:  # noqa: BLE001
        return "offline_jobs_unreadable"
    return None


def tick(sched=None, *, should_stop=None) -> str:
    """One attempt. Returns ``"ran"`` or the reason it yielded. Never raises."""
    try:
        if sched is None:
            from src.scheduler.runner import get_scheduler

            sched = get_scheduler()
        reason = yield_reason(sched)
        if reason:
            sched._note_maint_skip(reason)
            return reason
        sched._run_off_peak_maintenance(should_stop=should_stop or _STOP.is_set)
        return "ran"
    except Exception:  # noqa: BLE001 - a background safety net must never break the app
        _LOG.warning("offline maintenance tick failed", exc_info=True)
        return "error"


def _loop() -> None:
    if _STOP.wait(_FIRST_TICK_DELAY_S):
        return
    while not _STOP.is_set():
        tick()
        if _STOP.wait(interval_s()):
            return


def start() -> bool:
    """Start the timer thread once per process. ``False`` when declined or already up."""
    global _THREAD
    if not enabled():
        return False
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return False
        _STOP.clear()
        _THREAD = threading.Thread(target=_loop, name="oo-offline-maintenance", daemon=True)
        _THREAD.start()
        return True


def stop() -> None:
    _STOP.set()
