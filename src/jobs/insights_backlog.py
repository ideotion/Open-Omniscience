"""The Insights indexing backlog, drained on the server (R600's second PR, OPEN_QUEUE item 40).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY. When Insights opened, the page drained the never-attempted backlog itself: a loop in the tab POSTing
``/api/insights/reindex?limit=300`` up to 40 times, then cooling down for a minute (``autoIndexInsights``). Closing the tab
stopped it after the batch in flight; only the idle-maintenance slice (30 s per collector-idle window) went on without it, so an
instance left running with its browser closed caught up slowly or, while collection kept the collector busy, not at all.

WHAT THIS IS. The same drain as a registered :class:`~src.jobs.background.BackgroundJob` (``insights-backlog``): the page starts
it (the same trigger as before, the Insights status poll seeing a backlog) and it goes on to the end on the server, visible in
the task manager with a Cancel. The rules are the page's own, which were the idle slice's (PRH-01): the backlog is
``never_attempted``, never ``remaining`` (an article with no indexable text stays in ``remaining`` forever); a batch that leaves
it unchanged ends the run instead of spending batches on a queue that is not rotating; and two runs in a row that end stuck at
the same count stop the restarts for the life of the process, where the page stopped them for the life of the tab.

WHAT KEEPS IT SAFE.
  * It writes in the same steps as the page did (``backfill_corpus``, 300 articles, its own short session per batch), so the
    single-writer gate is taken per article and released between them, as for every other writer job (``is_writer``).
  * It does not start, and stops between batches, while other work owns the same rows or the machine: a re-index, a corpus
    lease, another writer job, a restore holding the machine (the scheduler's exclusive hold), or the storage guard engaged.
    The result says which. The idle slice in turn stands back while this job runs (it is a writer job).
  * Nothing to resume after a restart: indexing is idempotent and the backlog is the state, so the next start (the page, or
    the idle slice) carries on from what is left. Counts only, no estimate; no network.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from src.jobs.background import BackgroundJob, Framed, JobContext, register_job

_LOG = logging.getLogger("jobs.insights_backlog")

KIND = "insights-backlog"
#: One batch is the page's own, so the drain writes in the steps it always did.
BATCH = 300

_state_lock = threading.Lock()
#: The backlog two consecutive runs ended stuck at; None while the last run was not stuck.
_stuck: dict[str, Any] = {"last": None, "refused": False}


def _busy_reason() -> str | None:
    """Why the drain must not run now (None when it may). Unknown state is treated as busy."""
    try:
        from src.scheduler.runner import get_scheduler

        if get_scheduler().holds_exclusive():
            return "exclusive_hold"
    except Exception:  # noqa: BLE001
        return "scheduler_unreadable"
    try:
        from src.scheduler.storage_guard import storage_guard

        if storage_guard.engaged:
            return "storage_guard"
    except Exception:  # noqa: BLE001
        return "storage_guard_unreadable"
    from src.scheduler.maintenance import _backlog_busy_reason

    # A re-index, a corpus lease, another writer job, or a caller of the old page endpoint (/api/insights/reindex) draining the
    # same least-recently-attempted rows.
    return _backlog_busy_reason(exclude_kind=KIND)


def _drain(ctx: JobContext) -> dict:
    from src.analytics.extract import get_extractor
    from src.analytics.store import backfill_corpus
    from src.database.session import SessionLocal

    extractor = get_extractor("baseline")
    batches = attempted = newly = failed = 0
    left: int | None = None
    last: int | None = None
    ended = "stopping"
    while not ctx.stopping:
        busy = _busy_reason()
        if busy:
            ended = busy
            break
        with SessionLocal() as session:
            r = backfill_corpus(session, extractor=extractor, limit=BATCH)
        batches += 1
        attempted += int(r.get("indexed") or 0)
        newly += int(r.get("newly_indexed") or 0)
        failed += int(r.get("failed") or 0)
        left = r.get("never_attempted")
        if left is None:
            left = r.get("remaining")
        ctx.set_progress(
            done=attempted,
            total=attempted + int(left or 0),
            detail=Framed(f"{int(left or 0)} article(s) never indexed left", "{n} article(s) never indexed left", n=int(left or 0)),
        )
        if not left:
            ended = "drained"
            break
        if left == last:
            ended = "not_shrinking"
            break
        last = left
    with _state_lock:
        if ended == "not_shrinking":
            # Stuck twice at the same count: something refuses to rotate. Stop restarting it for the life of the process.
            if _stuck["last"] == left:
                _stuck["refused"] = True
            _stuck["last"] = left
        elif ended == "drained":
            _stuck["last"] = None
    return {
        "ended": ended,
        "complete": left == 0,
        "batches": batches,
        "attempted": attempted,
        "newly_indexed": newly,
        "failed": failed,
        "never_attempted_left": left,
    }


# A writer: each batch commits keyword-index rows (tests/test_job_writer_flags.py).
_JOB = register_job(BackgroundJob(KIND, "Indexing articles for Insights", _drain, is_writer=True, cancellable=True))


def get_job() -> BackgroundJob:
    return _JOB


def start() -> dict:
    """Start the drain unless it runs already, a stuck backlog stopped the restarts, or other work owns the rows. Never raises:
    the answer says whether it started and why not."""
    status = _JOB.status()
    if status.get("running"):
        return {"started": False, "reason": "running", "status": status}
    with _state_lock:
        if _stuck["refused"]:
            return {"started": False, "reason": "stuck", "status": status}
    busy = _busy_reason()
    if busy:
        return {"started": False, "reason": busy, "status": status}
    try:
        return {"started": True, "reason": None, "status": _JOB.start()}
    except RuntimeError:
        return {"started": False, "reason": "running", "status": _JOB.status()}


def _reset_for_tests() -> None:
    with _state_lock:
        _stuck.update(last=None, refused=False)
