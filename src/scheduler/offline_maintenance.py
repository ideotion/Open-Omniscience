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

WHAT EACH NUMBER PROTECTS (nothing here is a cap on the work, only on how it shares the
machine):

* the first tick waits :data:`_FIRST_TICK_DELAY_S` -- boot's own upkeep, the cache warm and
  a re-index auto-resume all start in the first minutes;
* the interval (300 s) is the collection loop's own cadence for the WHOLE window, whose
  rollup refreshes, snapshot and vacuum slice are not worth repeating faster;
* an unfinished orphan-prune sweep is different: while its last pass reported
  ``complete: false`` and nothing else owns the machine, passes run BACK TO BACK, each
  followed by a rest of :data:`_REST_FRACTION` of the pass's own duration (so the write gate
  is free at least ~20 % of the time whatever the machine's speed: a slow disk rests longer,
  a fast one shorter -- sized from the measured pass, not from a constant). A pass itself is
  bounded by the prune's soft deadline (``OO_PRUNE_BUDGET_S``, default 30 s), which keeps
  the single-writer gate held one slice at a time.

``OO_OFFLINE_MAINTENANCE=0`` declines it for one process;
``OO_OFFLINE_MAINT_INTERVAL_S`` sets the cadence (default 300 s, the loop's own cadence, floor 60 s).
"""

from __future__ import annotations

import logging
import os
import threading
import time

_LOG = logging.getLogger("scheduler.offline_maintenance")

#: Let boot settle first: the unlock path's upkeep, the cache warm and a boot re-index
#: resume all start in the first minutes and this must never compete with them.
_FIRST_TICK_DELAY_S = 180.0

#: After a continuation pass, rest this fraction of the time it took (0.25 -> at most an 80 %
#: duty cycle on the write gate).
_REST_FRACTION = 0.25
_MIN_REST_S = 1.0

#: Our own corpus lease. A restore's swap waits for every lease to drop (bounded) before it
#: replaces the corpus file, so a window that was already writing when the restore began is
#: waited out rather than left writing to the unlinked file.
_LEASE = "offline-maintenance"

_clock = time.monotonic

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
        from src.database.corpus_lease import active_leases

        # Every unit of live-corpus work that registers its presence: re-index batches,
        # the keyword fold, quarantine, search re-index, a newsletter import. The prune
        # decides what to delete outside the write gate, so a fold repointing mentions
        # under it could lose to the delete.
        held = [n for n in active_leases() if n != _LEASE]
        if held:
            return "offline_corpus_lease_held"
    except Exception:  # noqa: BLE001 - unknown lease state is treated as held
        return "offline_lease_unreadable"
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


def prune_incomplete() -> bool:
    """Did the last automatic cleanup leave its orphan-prune sweep unfinished?"""
    try:
        from src.analytics.store import keyword_cleanup_state

        prune = (keyword_cleanup_state().get("last_tally") or {}).get("prune") or {}
        return prune.get("complete") is False
    except Exception:  # noqa: BLE001 - unreadable means "not known to be unfinished"
        return False


def recompute_incomplete() -> bool:
    """Did the last stoplist recompute (R111 step T3) stop early on a list it has not finished?"""
    try:
        from src.analytics.stoplist_recompute import incomplete

        return incomplete()
    except Exception:  # noqa: BLE001 - unreadable means "not known to be unfinished"
        return False


def _cleanup_stamp():
    """When the cleanup AND the stoplist recompute last recorded a pass. A pass that could
    not write its marker leaves this unchanged, and the sweep predicates would then stay true
    forever."""
    try:
        from src.analytics.stoplist_recompute import state_stamp
        from src.analytics.store import keyword_cleanup_state

        return ((keyword_cleanup_state().get("last_tally") or {}).get("at"), state_stamp())
    except Exception:  # noqa: BLE001
        return None


def _stop_predicate(sched, should_stop=None):
    """When the window must end EARLY: a stop request, the collection loop starting (it
    owns the window), or an exclusive operation claiming the machine (a restore or import
    that begins mid-window -- the loop's own ``stop()`` reaches nothing here, so this
    is the only thing that lets the window notice)."""
    base = should_stop or _STOP.is_set

    def stop() -> bool:
        if base() or sched.is_running():
            return True
        try:
            from src.scheduler.runner import owns_the_machine

            return bool(owns_the_machine())
        except Exception:  # noqa: BLE001 - unknown ownership is treated as owned
            return True

    return stop


def _run_window(sched, stop, *, continuation: bool) -> bool:
    """One window under our corpus lease. Returns whether it ran."""
    from src.database.corpus_lease import corpus_lease

    with corpus_lease(_LEASE):
        return bool(sched._run_off_peak_maintenance(should_stop=stop, continuation=continuation))


def _continue_prune(sched, stop) -> int:
    """Back-to-back prune (or stoplist recompute) passes while a sweep is unfinished and the
    machine is free.

    Returns how many ran. Stops at the first yield reason, stop request, failed pass,
    pass that recorded nothing (a marker that cannot be written would otherwise loop
    forever) or finished sweep, so it can never outlive the condition that justified it."""
    ran = 0
    while not stop() and (prune_incomplete() or recompute_incomplete()):
        reason = yield_reason(sched)
        if reason:
            sched._note_maint_skip(reason)
            break
        before = _cleanup_stamp()
        t0 = _clock()
        if not _run_window(sched, stop, continuation=True):
            break
        ran += 1
        if _cleanup_stamp() == before:
            sched._note_maint_skip("offline_cleanup_recorded_nothing")
            break
        rest = max(_MIN_REST_S, (_clock() - t0) * _REST_FRACTION)
        if _STOP.wait(rest):
            break
    return ran


def tick(sched=None, *, should_stop=None) -> str:
    """One attempt. Returns ``"ran"``, ``"yielded"`` or the reason it yielded. Never raises."""
    try:
        if sched is None:
            from src.scheduler.runner import get_scheduler

            sched = get_scheduler()
        reason = yield_reason(sched)
        if reason:
            sched._note_maint_skip(reason)
            return reason
        stop = _stop_predicate(sched, should_stop)
        if not _run_window(sched, stop, continuation=False):
            return "yielded"
        _continue_prune(sched, stop)
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
