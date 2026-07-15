"""
Off-peak background maintenance (A10) — scheduler-owned, collector-idle only.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The deadline-budgeted, resumable keyword maintenance (counter reconcile + orphan
prune + language reconcile) used to run COUPLED to the tail of every collect pass
(via ``api.insights.warm_cache`` inside ``refresh_briefing``) and once at boot.
That put an 86-104 s/pass reconcile (measured at 3.06 M keywords) INSIDE the pass,
inflating pass timing and paying the freshness check on every 5 s continuous gap.

A10 makes it scheduler-owned and OFF-PEAK: the scheduler runs :func:`run_idle_maintenance`
in the IDLE window between passes, mutually exclusive with any collect pass (the
scheduler holds ``_run_lock`` while calling it, so a run-now pass is never
concurrent), throttled to a minimum interval so it does not fire every gap, and
interruptible (``should_stop``) so it yields promptly to a stop or a new pass.

Ordering, never exclusion: the freshness gates inside ``maybe_reconcile_counters``
/ ``maybe_cleanup_keywords`` stay (usually a no-op), the deadline budgets +
resumable watermarks stay, and the ``complete: false`` disclosure until a sweep
finishes stays. This module only changes WHEN the existing maintenance runs, never
WHAT it does or how honestly it reports.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

_LOG = logging.getLogger("scheduler.maintenance")


def run_idle_maintenance(*, should_stop: Callable[[], bool] | None = None) -> dict:
    """Run the budgeted keyword maintenance ONCE, in its own session, best-effort.

    Called by the scheduler in a collector-idle window. Runs the counter reconcile
    (only when the counters are not fresh) then the keyword cleanup (orphan prune +
    language reconcile, freshness-gated to ~12 h). Each is a deadline-budgeted,
    resumable slice, so a whole sweep spans several idle windows and discloses
    ``complete: false`` in between. Re-checks ``should_stop`` between the two so a
    scheduler STOP is honoured promptly (a run-now during the window is handled by
    the caller's busy signal, not by yielding mid-slice). Never raises.
    """
    stop = should_stop or (lambda: False)
    out: dict = {}
    if stop():
        return {"skipped": "stopping"}
    from src.database.session import session_scope

    try:
        with session_scope() as session:
            from src.analytics.store import (
                maybe_cleanup_keywords,
                maybe_reconcile_counters,
            )

            try:
                out["reconcile"] = maybe_reconcile_counters(session)
            except Exception:  # noqa: BLE001 - a background safety net must never break
                _LOG.warning("off-peak counter reconcile failed", exc_info=True)
                out["reconcile"] = {"skipped": "error"}
            # S6: the per-source article counter (cheap whole-table GROUP BY; keeps
            # source_io/sources + the reader off a live per-source COUNT).
            try:
                from src.analytics.store import reconcile_source_counters

                out["source_counters"] = reconcile_source_counters(session)
            except Exception:  # noqa: BLE001
                _LOG.warning("off-peak source counter reconcile failed", exc_info=True)
                out["source_counters"] = {"skipped": "error"}
            if stop():
                out["cleanup"] = {"skipped": "stopping"}
                return out
            try:
                out["cleanup"] = maybe_cleanup_keywords(session)
            except Exception:  # noqa: BLE001
                _LOG.warning("off-peak keyword cleanup failed", exc_info=True)
                out["cleanup"] = {"skipped": "error"}
    except Exception:  # noqa: BLE001 - even opening the session must never break the loop
        _LOG.warning("off-peak maintenance could not open a session", exc_info=True)
        return {"skipped": "error"}
    return out
