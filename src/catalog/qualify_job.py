"""
Bulk source QUALIFICATION as a background job — draining the candidate backlog.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

2026-07-23 field-feedback workflow, slice S1.2 (see the ledger CLAUDE.md "SOURCE
QUALIFICATION" thread). The steady-state RIDE-ALONG
(:func:`src.catalog.qualification.advance_qualification`, ``qualification_per_pass=5``
per online collection pass) cannot honestly drain a backlog of tens of thousands of
Wikidata-discovered candidates in reasonable time — measured on the maintainer's
2026-07-23 field diagnostics: 42,612–66,697 candidates at 5/pass (~4 passes/hour) is
90+ days. This worker runs :func:`src.catalog.qualification.run_qualification_pass`
REPEATEDLY, in bounded BATCHES, as a cancellable background job, until the backlog is
drained or the run is stopped/paused.

NO PERSISTED CURSOR (unlike ``src.catalog.discover_job``'s ``world_discovery.json``):
the correctness net here is the DATABASE ITSELF — ``Source.status`` is the durable
progress marker (a candidate LEAVES the unqualified pool the moment it is stamped
qualified/disqualified, and the re-qualification ladder's own append-only attempt
history already tracks disqualified retries), so a cancel/crash/restart just means
"run again": :func:`~src.catalog.qualification.select_unqualified` /
:func:`~src.catalog.qualification.select_due_disqualified` will never re-propose an
already-stamped source. This is a deliberate simplification versus the world-discovery
job, which DOES need a file cursor because "a country" isn't a persisted row with its
own durable state the way a Source row is.

Memory-guard aware, exactly like the collector's own pass loop: before each batch the
run polls the SAME process-wide ``MemoryGuard`` singleton the scheduler consults
(``src.scheduler.memguard.memory_guard``) and pauses cleanly — honestly named, never a
silent stall — when it is engaged, so a bulk run never pushes a low-RAM machine over
the edge just to drain the backlog faster. It does NOT auto-resume (the same
convention as the world-discovery job): a paused run is restarted explicitly.

No score anywhere. A NO-PROGRESS run (several consecutive batches that judge nothing —
e.g. a persistent glut of feed-less, evidence-less candidates sitting at the front of
the FIFO queue, per the 2026-07-23 zero-evidence fix in ``qualification.py``) is
detected and the run stops HONESTLY rather than spinning forever on candidates it can
never resolve — mirrors ``discover_job.py``'s ``_MAX_CONSECUTIVE_FAILURES`` convention.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

_LOG = logging.getLogger(__name__)

# Consecutive batches with ZERO stamped progress (qualified + disqualified == 0)
# before an honest stop — protects against spinning forever on a run of candidates
# that can never be resolved (no reachable feed, no prior evidence).
_MAX_CONSECUTIVE_NO_PROGRESS = 10

# A small pause between batches: politeness + a chance for the memory guard's next
# poll to reflect a fresh reading, never a tight hot loop.
_DEFAULT_SLEEP_S = 0.5


def initial_backlog_estimate(session) -> dict:
    """Cheap COUNTS only (never a fabricated total) of what a bulk run would face:
    the never-yet-qualified pool (the bulk of any real backlog) and the currently-due
    re-qualification pool (small, and itself grows/shrinks on the ladder's own clock —
    stated honestly as a SEPARATE, dynamic figure, not folded into one misleading
    total)."""
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    from src.catalog.qualification import STATUS_UNQUALIFIED, select_due_disqualified
    from src.database.models import Source

    unqualified = int(session.query(Source).filter_by(status=STATUS_UNQUALIFIED).count())
    due = len(select_due_disqualified(session, now=_dt.now(_UTC), limit=10_000))
    return {"unqualified": unqualified, "due_disqualified": due}


def run_bulk_qualification(
    ctx,
    *,
    batch_size: int = 20,
    fetcher=None,
    session_factory=None,
    sleep_s: float = _DEFAULT_SLEEP_S,
    now_fn=None,
) -> dict:
    """Drain the qualification backlog in bounded batches until it is empty, the run
    is cancelled, airplane mode engages, or the memory guard trips.

    ``ctx`` is the :class:`src.jobs.background.JobContext` (cooperative stop +
    progress). ``fetcher``/``session_factory``/``now_fn`` are test seams; production
    builds a real :class:`~src.safety.fetcher.EthicalFetcher` via
    :func:`src.safety.fetcher.make_fetcher` and uses the app's ``session_scope``.
    Returns an honest summary — ``complete`` is True only when a batch call finds
    NOTHING left to evaluate; a pause/stop names its reason.
    """
    from src.ingest import kill_switch_active
    from src.scheduler import memguard

    if session_factory is None:
        from src.database.session import session_scope

        session_factory = session_scope
    if fetcher is None:
        from src.safety.fetcher import make_fetcher

        fetcher = make_fetcher()

    with session_factory() as db:
        backlog = initial_backlog_estimate(db)
    total_backlog = backlog["unqualified"] + backlog["due_disqualified"]

    totals = {
        "batches_run": 0, "evaluated": 0, "qualified": 0, "disqualified": 0,
        "no_evidence": 0, "trial_fetch_errors": 0,
    }
    consecutive_no_progress = 0
    paused_reason: str | None = None
    complete = False

    ctx.set_progress(done=0, total=total_backlog, detail="starting…")

    while True:
        if ctx.stopping:
            paused_reason = "cancelled — progress is saved (each source's status), start again to resume"
            break
        if kill_switch_active():
            paused_reason = "airplane mode engaged — progress is saved, start again to resume"
            break
        if memguard.memory_guard.poll():
            paused_reason = (
                "paused: "
                + (memguard.memory_guard.state().get("reason") or "memory pressure")
                + " — progress is saved, start again once memory recovers"
            )
            break

        now = now_fn() if now_fn is not None else datetime.now(UTC)
        with session_factory() as db:
            result = qualification_pass(db, fetcher, batch_size, now)

        evaluated = int(result.get("evaluated", 0))
        totals["batches_run"] += 1
        if evaluated == 0:
            complete = True
            break

        qualified = int(result.get("qualified", 0))
        disqualified = int(result.get("disqualified", 0))
        totals["evaluated"] += evaluated
        totals["qualified"] += qualified
        totals["disqualified"] += disqualified
        totals["no_evidence"] += int(result.get("no_evidence", 0))
        totals["trial_fetch_errors"] += int(result.get("trial_fetch_errors", 0))

        progressed = qualified + disqualified
        consecutive_no_progress = 0 if progressed else consecutive_no_progress + 1
        if consecutive_no_progress >= _MAX_CONSECUTIVE_NO_PROGRESS:
            paused_reason = (
                f"stopped after {consecutive_no_progress} consecutive batches with no "
                "evidence to judge — the remaining candidates could not be evaluated "
                "(no reachable feed / no prior articles); they stay unqualified and "
                "will be retried on a later run"
            )
            break

        ctx.set_progress(
            done=totals["evaluated"],
            total=max(total_backlog, totals["evaluated"]),  # the estimate is a floor, not a cap
            detail=(
                f"{totals['qualified']} qualified · {totals['disqualified']} disqualified · "
                f"{totals['no_evidence']} no-evidence so far"
            ),
        )
        if sleep_s and evaluated:
            time.sleep(sleep_s)

    summary: dict = {"complete": complete, **totals, "initial_backlog": backlog}
    if paused_reason:
        summary["paused_reason"] = paused_reason
    return summary


def qualification_pass(db, fetcher, batch_size: int, now: datetime) -> dict:
    """Thin seam so tests can stub the underlying pass without patching a module-level
    import inside :func:`run_bulk_qualification`."""
    from src.catalog.qualification import run_qualification_pass

    return run_qualification_pass(db, fetcher, per_pass=batch_size, now=now)
