"""The first-run preflight as a TASK-MANAGER-VISIBLE job (PRH-23).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY. Before this, both first-run preflights ran INLINE on the collect-pass thread
(``runner._do_run``, the "background" phase). Between them they make up to 50 source
checks plus one robots read per distinct feed host plus a per-provider sample -- every
one a real request, over Tor on the ruled default. On a first launch that is many
minutes during which the task manager shows only the coarse phase label "background
tasks: markets - calendars - checks", with no name, no count and no way to stop it.
A first launch therefore looks stalled while the app is in fact working correctly,
which is the whole complaint PRH-23 records.

WHAT CHANGED, and what deliberately did NOT. The work, its order, its bounds and its
network behaviour are unchanged -- this is a move onto the registry the repo already
has for exactly this shape (``src/jobs/background.py``, written for the 2026-07-08
"heavy button freezes the app" family), so ``/api/jobs`` enumerates it with live
progress and an honest Cancel. It is still kicked from the pass tail and still runs at
most ONCE ever, gated by the same ``has_run_before()`` log check.

THE CONCURRENCY, stated rather than glossed. Running as a job means the pass tail no
longer BLOCKS on those minutes of fetching -- which also means the preflight now
overlaps the housekeeping lane, and ruling R5 asked for a serialised pass tail. Two
things bound that, and both are load-bearing:

  * R5 serialised the two WHOLE-CORPUS DB consumers (the lane's qualification scan and
    the briefing refresh) because they contend for memory and the writer gate on two
    cores. This job is network-bound and bounded to 50 sources; its DB write is one
    ``SourceMetadata`` row per source, committed once at the end of its own session.
  * It runs on the FIRST pass of a fresh install and never again. The overlap it adds
    exists only on the launch this item is about, and on that launch the corpus is
    empty -- so the lane's whole-corpus scan has nothing to scan.

It takes its OWN session (``session_scope``), never the pass's: the pass thread is
still using that one, and a SQLAlchemy Session is not safe for concurrent use from two
threads. That is a real correctness requirement of the move, not a style choice.

DECLINES UNDER THE EXCLUSIVE HOLD. A pass already in flight when a restore/import/
bundle takes the machine continues into its tail, so this kick CAN fire under the hold
-- the "gate every entry point" shape the 2026-07-24 lesson records and S6.1 re-learned
for the two rollup builds. Declining is free here: nothing is logged, so
``has_run_before()`` stays false and the next pass runs it.
"""

from __future__ import annotations

import logging
from typing import Any

from src.jobs.background import BackgroundJob, JobContext, register_job

_LOG = logging.getLogger("monitoring.preflight_job")

#: The registry key. ``/api/jobs`` and the task manager address the job by this.
JOB_KIND = "first-run-preflight"


def _worker(ctx: JobContext, *, fetcher: Any = None) -> dict:
    """Source preflight, then feed preflight. Each is skipped if it already ran.

    Returns an honest per-half summary. A half that was cancelled reports
    ``complete: False`` and wrote no log, so the next pass retries it whole.
    """
    from src.database.session import session_scope
    from src.monitoring import feed_preflight, preflight

    out: dict[str, Any] = {}

    if not preflight.has_run_before():
        ctx.set_progress(detail="checking sources (robots + reachability)")
        # Its own session: the pass thread still holds the one it was using.
        with session_scope() as db:
            out["sources"] = preflight.preflight_sources(
                db,
                fetcher,
                progress=lambda done, total, domain: ctx.set_progress(
                    done=done, total=total, detail=f"source {done}/{total}: {domain}"
                ),
                should_stop=lambda: ctx.stopping,
            )
            # All-or-nothing (see preflight_sources): a cancelled half wrote no log, so
            # its partial SourceMetadata edits must not persist either -- otherwise the
            # retry would be judging sources against verdicts nothing recorded.
            if not out["sources"].get("complete"):
                db.rollback()
    else:
        out["sources"] = {"skipped": "already ran"}

    if ctx.stopping:
        return out

    if not feed_preflight.has_run_before():
        ctx.set_progress(detail="checking bundled calendar and market feeds")
        out["feeds"] = feed_preflight.run_feed_preflight(
            fetcher,
            progress=lambda done, total, host: ctx.set_progress(
                done=done, total=total, detail=f"feed host {done}/{total}: {host}"
            ),
            should_stop=lambda: ctx.stopping,
        )
    else:
        out["feeds"] = {"skipped": "already ran"}

    return out


#: ``is_writer=True``: the source half writes SourceMetadata, so it joins the writer
#: arbitration set /api/jobs publishes. ``cancellable=True`` is HONEST here -- both
#: halves consult ``ctx.stopping`` between checks and neither wraps an opaque call.
PREFLIGHT_JOB = register_job(
    BackgroundJob(
        JOB_KIND,
        "First-run preflight: checking sources and feeds",
        _worker,
        is_writer=True,
        cancellable=True,
    )
)


def pending() -> bool:
    """Is there any first-run preflight left to do? Cheap: two file-existence checks."""
    from src.monitoring import feed_preflight, preflight

    return not preflight.has_run_before() or not feed_preflight.has_run_before()


def kick(fetcher: Any = None) -> dict | None:
    """Start the job if it is pending and nothing else claims the machine.

    Returns the job status, or None when there was nothing to do / it declined. NEVER
    raises: this is called from the collect-pass tail and a preflight is instrumentation,
    not a gate -- it must not be able to end a pass.
    """
    try:
        if not pending():
            return None
        # Gate the entry point, not just the loop (the 2026-07-24 lesson; S6.1 relearned
        # it for the rollup builds). A declined kick logs nothing, so the next pass runs.
        from src.scheduler.runner import exclusive_window_open

        if exclusive_window_open():
            _LOG.info("first-run preflight: declined, an exclusive operation holds the machine")
            return None
        return PREFLIGHT_JOB.start(fetcher=fetcher)
    except RuntimeError:
        return None  # already running (the previous pass's kick is still going)
    except Exception:  # noqa: BLE001 - a preflight must never break a pass
        _LOG.warning("first-run preflight: could not start", exc_info=True)
        return None
