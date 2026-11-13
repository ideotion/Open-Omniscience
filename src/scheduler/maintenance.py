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

from src.monitoring.secret_scrub import log_failure

_LOG = logging.getLogger("scheduler.maintenance")

#: One batch is the Insights page's own (``/api/insights/reindex?limit=300``), so a slice writes in the same steps it always did.
BACKLOG_BATCH = 300
#: After a slice finds the backlog empty, the next check waits this long: a backlog comes back only through an import (whose own
#: re-index resume job owns it) or an article whose indexing failed at ingest, so an hour costs nothing and saves a scan a window.
BACKLOG_RECHECK_S = 3600.0
_backlog_clear_at = 0.0
#: The Insights page drains the same backlog itself (``POST /api/insights/reindex``, every few seconds while it is open), with no
#: lease and no job row: both writers would pick the same least-recently-attempted rows. The slice stands back for this long
#: after the page's last batch, so an open Insights page owns the backlog and the slice takes it back once the page is gone.
PAGE_DRAIN_QUIET_S = 30.0
_page_drain_at = 0.0


def note_page_drain() -> None:
    """The Insights page is about to index a batch of the backlog (called by its endpoint)."""
    import time

    global _page_drain_at
    _page_drain_at = time.monotonic()


def _page_draining() -> bool:
    import time

    return bool(_page_drain_at) and time.monotonic() - _page_drain_at < PAGE_DRAIN_QUIET_S


def backlog_budget_s() -> float:
    """The soft deadline of one backlog slice: ``OO_BACKLOG_BUDGET_S``, default 30 s (the orphan prune's own budget), 0 declines."""
    import os

    try:
        return max(0.0, float(os.getenv("OO_BACKLOG_BUDGET_S", "") or 30.0))
    except ValueError:
        return 30.0


def _backlog_busy_reason(exclude_kind: str | None = None) -> str | None:
    """Why the slice must not run now: work that already owns the unindexed articles. The collection loop's window does not pass
    through the offline timer's yield checks, so the slice makes the ones that matter to it here: a re-index drain (an import's
    resume picks the same least-recently-attempted rows, and both writers would race for every one), any registered corpus lease,
    and a running writer job, and the Insights page's own drain. Unknown state is treated as busy."""
    if _page_draining():
        return "page_drain_running"
    try:
        from src.analytics.reindex_job import get_reindex_manager

        if (get_reindex_manager().status() or {}).get("state") == "running":
            return "reindex_running"
    except Exception:  # noqa: BLE001
        return "reindex_unreadable"
    try:
        from src.database.corpus_lease import active_leases

        # The offline timer runs this window under a lease of its own; that one is this work, not a rival.
        if [n for n in active_leases() if n != "offline-maintenance"]:
            return "corpus_lease_held"
    except Exception:  # noqa: BLE001
        return "lease_unreadable"
    try:
        from src.jobs.background import all_job_statuses

        # ``exclude_kind``: the Insights backlog job (src/jobs/insights_backlog.py) asks this too, and is not its own rival.
        if any(st.get("running") and st.get("is_writer") and (exclude_kind is None or st.get("kind") != exclude_kind) for st in all_job_statuses()):
            return "writer_job_running"
    except Exception:  # noqa: BLE001
        return "jobs_unreadable"
    return None


def index_backlog_slice(session, *, should_stop: Callable[[], bool] | None = None, budget_s: float | None = None) -> dict:
    """Index never-attempted articles in batches until the backlog is empty, stops shrinking, the budget runs out or a stop is asked.

    The same rules as the Insights page's drain (PRH-01): the backlog is ``never_attempted``, never ``remaining`` (an article with no
    indexable text stays in ``remaining`` forever), and a batch that leaves it unchanged ends the slice instead of spending the budget
    on a queue that is not rotating. A cheap existence check comes first, so a corpus with no backlog pays one indexed lookup and
    never re-attempts its duds every window. Counts only; ``complete`` says whether the backlog is empty."""
    import time

    from sqlalchemy import exists

    from src.analytics.store import backfill_corpus
    from src.database.derived_views import KeywordMentionRead
    from src.database.models import Article
    from src.database.stand_in import not_a_stand_in_article_id

    stop = should_stop or (lambda: False)
    budget = backlog_budget_s() if budget_s is None else budget_s
    if budget <= 0:
        return {"skipped": "disabled"}
    busy = _backlog_busy_reason()
    if busy:
        return {"skipped": busy}
    global _backlog_clear_at
    if _backlog_clear_at and time.monotonic() - _backlog_clear_at < BACKLOG_RECHECK_S:
        return {"complete": True, "skipped": "checked_recently"}
    # NOT EXISTS per row, not backfill's NOT IN over every mention: an article indexed before keyword_indexed_at existed also
    # reads NULL, so the NULL rows alone are not the backlog, and materialising the distinct ids of every mention each window
    # is the cost this check exists to avoid.
    has_mention = exists().where(KeywordMentionRead.article_id == Article.id)
    pending = (
        session.query(Article.id)
        .filter(Article.keyword_indexed_at.is_(None), ~has_mention, not_a_stand_in_article_id(Article.id))
        .limit(1)
        .first()
    )
    if pending is None:
        _backlog_clear_at = time.monotonic()
        return {"complete": True, "batches": 0}
    from src.analytics.extract import get_extractor

    extractor = get_extractor("baseline")
    deadline = time.monotonic() + budget
    batches = attempted = newly = failed = 0
    left: int | None = None
    last: int | None = None
    ended = "budget"
    while True:
        if stop():
            ended = "stopping"
            break
        if _page_draining():  # the page opened mid-slice: it owns the backlog now
            ended = "page_drain_running"
            break
        r = backfill_corpus(session, extractor=extractor, limit=BACKLOG_BATCH)
        batches += 1
        attempted += int(r.get("indexed") or 0)
        newly += int(r.get("newly_indexed") or 0)
        failed += int(r.get("failed") or 0)
        left = r.get("never_attempted")
        if not left:
            ended = "drained"
            break
        if left == last:
            ended = "not_shrinking"
            break
        last = left
        if time.monotonic() >= deadline:
            break
    drained = left == 0  # never None: a slice stopped before its first batch knows nothing new, and must not mark the backlog clear
    if drained:
        _backlog_clear_at = time.monotonic()
    return {
        "complete": drained,
        "ended": ended,
        "batches": batches,
        "attempted": attempted,
        "newly_indexed": newly,
        "failed": failed,
        "never_attempted_left": left,
    }


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
    except Exception as exc:  # noqa: BLE001 - a background safety net must never break
        log_failure(_LOG, "off-peak pre-restore snapshot sweep failed", exc, level=logging.WARNING)
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
    except Exception as exc:  # noqa: BLE001 - a background safety net must never break
        log_failure(_LOG, "off-peak stale-staging sweep failed", exc, level=logging.WARNING)
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
            except Exception as exc:  # noqa: BLE001 - a background safety net must never break
                log_failure(_LOG, "off-peak counter reconcile failed", exc, level=logging.WARNING)
                out["reconcile"] = {"skipped": "error"}
            # S6: the per-source article counter (cheap whole-table GROUP BY; keeps
            # source_io/sources + the reader off a live per-source COUNT).
            try:
                from src.analytics.store import reconcile_source_counters

                out["source_counters"] = reconcile_source_counters(session)
            except Exception as exc:  # noqa: BLE001
                log_failure(_LOG, "off-peak source counter reconcile failed", exc, level=logging.WARNING)
                out["source_counters"] = {"skipped": "error"}
            # 2026-07-26 hardware diagnostics W2: refresh the /api/database/countries
            # in-memory rollup (mirrors source_counters above -- sources are few, a
            # full rebuild every idle window is cheap; see the module docstring for
            # why this DOESN'T need change-token gating like the DuckDB rollups).
            try:
                from src.analytics import source_country_rollup

                source_country_rollup.refresh(session)
                out["country_rollup"] = {"refreshed": True}
            except Exception as exc:  # noqa: BLE001
                log_failure(_LOG, "off-peak country rollup refresh failed", exc, level=logging.WARNING)
                out["country_rollup"] = {"skipped": "error"}
            # D3 (2026-09-11): the /api/insights/source-types rollup, on the same
            # off-peak cadence -- but unlike country_rollup above, its own refresh()
            # is change-token gated (this aggregate scans articles, not the few
            # sources rows), so most idle windows are a cheap watermark-only no-op.
            try:
                from src.analytics import source_type_rollup

                out["source_type_rollup"] = source_type_rollup.refresh(session)
            except Exception as exc:  # noqa: BLE001
                log_failure(_LOG, "off-peak source-type rollup refresh failed", exc, level=logging.WARNING)
                out["source_type_rollup"] = {"skipped": "error"}
            if stop():
                out["cleanup"] = {"skipped": "stopping"}
                return out
            try:
                out["cleanup"] = maybe_cleanup_keywords(session)
            except Exception as exc:  # noqa: BLE001
                log_failure(_LOG, "off-peak keyword cleanup failed", exc, level=logging.WARNING)
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
            except Exception as exc:  # noqa: BLE001
                log_failure(_LOG, "off-peak incremental vacuum failed", exc, level=logging.WARNING)
                out["incremental_vacuum"] = {"skipped": "error"}
            if stop():
                out["day_counts"] = {"skipped": "stopping"}
                return out
            # R625: fold the per-day keyword counts' stale days (the mentions added since the last fold, and the days
            # a delete or a move marked), so Home trending reads them from the table; or start their build when they
            # are not current. Here, between passes, is the throttle. It stands back while a re-index or another
            # writer job owns the mentions (a drain bumps the corpus epoch every batch, which would restart a build).
            try:
                busy = _backlog_busy_reason()
                if busy:
                    out["day_counts"] = {"skipped": busy}
                else:
                    from src.analytics.day_counts import fold_tail
                    from src.database.session import engine as _dc_engine

                    out["day_counts"] = fold_tail(_dc_engine, should_stop=stop)
            except Exception as exc:  # noqa: BLE001
                log_failure(_LOG, "off-peak daily keyword counts fold failed", exc, level=logging.WARNING)
                out["day_counts"] = {"skipped": "error"}
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
            except Exception as exc:  # noqa: BLE001
                log_failure(_LOG, "off-peak stat snapshot failed", exc, level=logging.WARNING)
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
            except Exception as exc:  # noqa: BLE001 - a log must never break the run it describes
                log_failure(_LOG, "expedition refresh failed", exc, level=logging.WARNING)
                out["expedition"] = {"skipped": "error"}
            # The never-attempted indexing backlog, drained on the server (2026-11-08, the background-mode thread). Only the
            # Insights page drained it before, through its 6 s status poll, so an instance left running with its browser closed
            # never caught up. New articles are indexed at ingest; this is the rest (an import's leftovers, an old corpus).
            # LAST in the window and budgeted (OO_BACKLOG_BUDGET_S), so it never delays the steps above.
            if stop():
                out["index_backlog"] = {"skipped": "stopping"}
            else:
                try:
                    out["index_backlog"] = index_backlog_slice(session, should_stop=stop)
                except Exception as exc:  # noqa: BLE001
                    log_failure(_LOG, "off-peak index backlog slice failed", exc, level=logging.WARNING)
                    out["index_backlog"] = {"skipped": "error"}
    except Exception as exc:  # noqa: BLE001 - even opening the session must never break the loop
        log_failure(_LOG, "off-peak maintenance could not open a session", exc, level=logging.WARNING)
        return {"skipped": "error"}
    if not stop():
        # After the session above has closed: the recompute takes its own short transaction per
        # chunk, and no read transaction of this window may be open under it.
        out["stoplist_recompute"] = _stoplist_recompute(stop)
    return out


def _stoplist_recompute(stop: Callable[[], bool]) -> dict:
    """R111 step T3: bring the stored top keywords up to the shipped stoplist, resumably.

    A no-op (``{"skipped": "current"}``) once the shipped list's fingerprint is recorded. It
    never raises and yields to a stop request and to the storage and memory guards at every
    chunk, which is why the window itself can stay a plain call."""
    try:
        from src.analytics.stoplist_recompute import maybe_recompute_top_keywords

        return maybe_recompute_top_keywords(should_stop=stop)
    except Exception:  # noqa: BLE001 - a background safety net must never break the loop
        _LOG.warning("off-peak stoplist recompute failed")
        return {"skipped": "error"}


def run_cleanup_continuation(*, should_stop: Callable[[], bool] | None = None) -> dict:
    """Resume ONLY the keyword cleanup (and an unfinished stoplist recompute), best-effort. Never raises.

    ``maybe_cleanup_keywords`` already resumes just the incomplete orphan prune while its
    12-hour freshness gate still holds, so calling it alone is the whole continuation.
    Used by the offline timer (:mod:`src.scheduler.offline_maintenance`) to run passes
    back to back while a big sweep is unfinished and nothing else is writing."""
    stop = should_stop or (lambda: False)
    if stop():
        return {"skipped": "stopping"}
    from src.database.session import session_scope

    out: dict = {}
    try:
        with session_scope() as session:
            from src.analytics.store import maybe_cleanup_keywords

            out["cleanup"] = maybe_cleanup_keywords(session)
    except Exception as exc:  # noqa: BLE001 - even opening the session must never break the loop
        log_failure(_LOG, "keyword cleanup continuation failed", exc, level=logging.WARNING)
        return {"skipped": "error"}
    if not stop():
        out["stoplist_recompute"] = _stoplist_recompute(stop)
    return out
