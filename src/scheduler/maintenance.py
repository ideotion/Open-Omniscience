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
    (only when the counters are not fresh), the per-source article counter
    reconcile, the keyword cleanup (orphan prune + language reconcile,
    freshness-gated to ~12 h), a bounded incremental-vacuum slice (DB-10 §1a/§3),
    and — S2 (2026-07-23 field-feedback workflow) — an hourly snapshot of the
    Library-tab counters that otherwise have no history (sources/keywords/
    Wikipedia+law tracked counts; gated by the snapshot table's own (metric, hour)
    unique constraint, so most idle windows are a cheap no-op). Each step is
    isolated (one failing step never breaks the rest) and re-checks ``should_stop``
    between steps so a scheduler STOP is honoured promptly (a run-now during the
    window is handled by the caller's busy signal, not by yielding mid-slice).
    Never raises.
    """
    stop = should_stop or (lambda: False)
    out: dict = {}
    if stop():
        return {"skipped": "stopping"}
    # W5 (2026-07-26 hardware diagnostics): the time-driven backstop for
    # pre-restore-*.db safety-net snapshots, which the count-based
    # _prune_snapshots() only ever prunes as a side effect of a LATER restore
    # (a long-lived instance that stops restoring keeps them forever
    # otherwise -- the diagnosed 97.8 GB). A pure, fast filesystem sweep --
    # no DB session needed, so it runs before the session_scope() block
    # below -- gated by the SAME pre-check above (unlike the DB-heavy,
    # deadline-budgeted steps inside session_scope, this one is quick enough
    # that it doesn't need its OWN intervening should_stop check between it
    # and the pre-check; adding one here would double-count against a
    # caller's should_stop() that is only meant to fire once per "step
    # boundary" -- see test_run_idle_maintenance_yields_on_should_stop_before_and_between).
    try:
        from src.backup.merge import prune_pre_restore_snapshots_by_age

        out["pre_restore_snapshot_sweep"] = {"removed": prune_pre_restore_snapshots_by_age()}
    except Exception:  # noqa: BLE001 - a background safety net must never break
        _LOG.warning("off-peak pre-restore snapshot sweep failed", exc_info=True)
        out["pre_restore_snapshot_sweep"] = {"skipped": "error"}
    # ...and the ORPHANED STAGING dirs beside them, for the same reason. The janitor
    # (cleanup_stale_staging) runs at BOOT only, so on a long-lived instance -- which is
    # the explicit goal, K4 asks for a 14-day continuous run -- a .restore-*/.bak-build-*
    # dir orphaned in hour 1 survives every one of the remaining days. That matters more
    # than the bytes: for an ENCRYPTED corpus the staging tree holds a PLAINTEXT copy, so
    # an unswept one is an at-rest-encryption hole for as long as the app stays up.
    #
    # Field bundle 2026-08-02: .restore-5c81a74582890858, 809 MB, flagged
    # plaintext_snapshot by the app's own forensics, left by an import killed the previous
    # day. It was ~18 h old at boot, so the 24 h age guard correctly protected it then --
    # and nothing would have looked again until the next restart. Same age + registry
    # guards as the boot janitor; a live job's staging is never touched.
    try:
        from src.backup.artifact import cleanup_stale_staging

        out["stale_staging_sweep"] = {"removed": cleanup_stale_staging()}
    except Exception:  # noqa: BLE001 - a background safety net must never break
        _LOG.warning("off-peak stale-staging sweep failed", exc_info=True)
        out["stale_staging_sweep"] = {"skipped": "error"}
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
            # 2026-07-26 hardware diagnostics W2: refresh the /api/database/countries
            # in-memory rollup (mirrors source_counters above -- sources are few, a
            # full rebuild every idle window is cheap; see the module docstring for
            # why this DOESN'T need change-token gating like the DuckDB rollups).
            try:
                from src.analytics import source_country_rollup

                source_country_rollup.refresh(session)
                out["country_rollup"] = {"refreshed": True}
            except Exception:  # noqa: BLE001
                _LOG.warning("off-peak country rollup refresh failed", exc_info=True)
                out["country_rollup"] = {"skipped": "error"}
            if stop():
                out["cleanup"] = {"skipped": "stopping"}
                return out
            try:
                out["cleanup"] = maybe_cleanup_keywords(session)
            except Exception:  # noqa: BLE001
                _LOG.warning("off-peak keyword cleanup failed", exc_info=True)
                out["cleanup"] = {"skipped": "error"}
            if stop():
                out["incremental_vacuum"] = {"skipped": "stopping"}
                return out
            # DB-10 §1a/§3: reclaim a bounded slice of the freelist via
            # PRAGMA incremental_vacuum in this same idle window (a no-op,
            # honestly reported, on a pre-ruling auto_vacuum=NONE/FULL corpus).
            try:
                from src.database.maintenance import maybe_incremental_vacuum
                from src.database.session import engine as _engine

                out["incremental_vacuum"] = maybe_incremental_vacuum(_engine)
            except Exception:  # noqa: BLE001
                _LOG.warning("off-peak incremental vacuum failed", exc_info=True)
                out["incremental_vacuum"] = {"skipped": "error"}
            if stop():
                out["stat_snapshot"] = {"skipped": "stopping"}
                return out
            # S2 (2026-07-23 field-feedback workflow): an hourly snapshot of the
            # Library-tab counters that otherwise have no history (sources/keywords/
            # wiki+law tracked counts) — cheap COUNT(*)s, gated by the table's own
            # (metric, hour) unique constraint so this is a no-op most idle windows.
            try:
                from src.database.snapshots import maybe_snapshot_library_stats

                out["stat_snapshot"] = maybe_snapshot_library_stats(session)
            except Exception:  # noqa: BLE001
                _LOG.warning("off-peak stat snapshot failed", exc_info=True)
                out["stat_snapshot"] = {"skipped": "error"}
            # 2026-08-12 unattended-run ask: refresh the expedition digest right AFTER
            # the snapshot it reads back from, so the operator's copy-paste log is
            # never a snapshot stale by an hour. Cheap by construction (bounded index
            # reads over rows that already exist -- never a corpus scan), and armed
            # runs only: an unarmed machine writes nothing.
            try:
                from src.monitoring import expedition

                if (expedition.digest() or {}).get("armed"):
                    expedition.refresh(session)
                    out["expedition"] = {"refreshed": True}
            except Exception:  # noqa: BLE001 - a log must never break the run it describes
                _LOG.warning("expedition refresh failed", exc_info=True)
                out["expedition"] = {"skipped": "error"}
    except Exception:  # noqa: BLE001 - even opening the session must never break the loop
        _LOG.warning("off-peak maintenance could not open a session", exc_info=True)
        return {"skipped": "error"}
    return out
