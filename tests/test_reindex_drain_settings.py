"""The backlog drain runs like the import, and says what it spends (F3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE THREE THINGS THIS PINS, from finding F3 of
``docs/audit/15_FIELD_INSTANCE_SLOWNESS_2026-09-21.md``:

1. **The settings.** Identical work -- the same ``index_article`` over the same articles
   -- ran at ONE COMMIT PER ARTICLE through this entry point and at 200 inside an
   import, for no reason but which caller reached it. Ruling R21 (maintainer 2026-09-22)
   lets the drain use the import's settings whenever the collector is idle. "Idle" is
   the strict reading: the scheduler LOOP is not alive. A live loop can start a pass
   between two articles, and a wide batch holds the single-writer gate across its whole
   commit -- so a reading of "no pass active right now" would hand the gate away for
   minutes to a collector that was about to want it.

2. **The instrumentation.** ``reindex_articles`` has computed the load / precompute /
   apply split since 2026-07-29 as an out-parameter, and this caller never asked for it.
   The one job that runs for days was the one job running blind. It is published LIVE,
   because a measurement that only arrives in the final result is worthless while the
   operator is deciding whether to keep waiting.

3. **The epoch.** ``bump_corpus_epoch`` takes the single-writer gate and commits, and
   its own docstring says to call it once per logical mutation, "never in a per-row
   loop". A drain over N import batches is ONE mutation of the derived rows.

No database is built here. Every test drives ``_reindex_resume_worker`` against fakes,
because what is under test is the CALLER's arithmetic and its choices -- which the real
re-index would hide behind hours of work.
"""

from __future__ import annotations

import pytest

from src.api import backup_v2 as bv2


class _Ctx:
    """The JobContext surface the worker uses, with the published values kept."""

    def __init__(self, *, stopping: bool = False) -> None:
        self.stopping = stopping
        self.progress: list[dict] = []
        self.metrics: dict | None = None
        self.metrics_history: list[dict | None] = []

    def set_progress(self, **kw) -> None:
        self.progress.append(kw)

    def set_metrics(self, metrics) -> None:
        self.metrics = metrics
        self.metrics_history.append(metrics)


@pytest.fixture
def drain(monkeypatch):
    """Wire the worker to fakes and hand back the knobs + the recorded calls."""
    rec: dict = {
        "calls": [], "bumps": [], "backlog_reads": 0,
        # R22: the deferral marker's lifecycle, which the worker owns for the whole run.
        "deferrals": [], "finishes": [],
    }
    state = {
        "batches": [{"batch_id": 7, "articles": 4}, {"batch_id": 9, "articles": 6}],
        "scheduler_running": False,
        "exclusive": False,
        # What OO_REINDEX_COMMIT_BATCH resolves to -- 1 unless the operator set it.
        "env_commit_batch": 1,
        # R22: whether the durable deferral marker can be written at all.
        "deferral_can_open": True,
        "stats": {
            "articles": 2,
            "wall_s": 10.0,
            "load_s": 1.0,
            "precompute_s": 2.0,
            "apply_s": 6.5,
            "apply_index_s": 4.0,
            "apply_commit_s": 2.0,
            "mentions_written": 20,
            "precompute": {"by_path": {"pool": 1}},
        },
    }

    def _backlog():
        rec["backlog_reads"] += 1
        return {
            "available": True,
            "articles_pending": sum(b["articles"] for b in state["batches"]),
            "batches": list(state["batches"]),
        }

    def _reindex(batch_id, *, commit_batch=None, stats=None, bump_epoch=True,
                 progress_cb=None, should_stop=None, **extra):
        # ``**extra`` so a knob the worker starts passing is RECORDED rather than
        # raising a TypeError that reads as a broken fake.
        rec["calls"].append(
            {
                "batch_id": batch_id,
                "commit_batch": commit_batch,
                "bump_epoch": bump_epoch,
                "extra": dict(extra),
            }
        )
        if stats is not None and state["stats"] is not None:
            stats.update(state["stats"])
        if progress_cb is not None:
            progress_cb(2, 2)
        return {"reindexed": 2, "failed": 0}

    class _Sched:
        def is_running(self):
            # A LIST means "one answer per read", which is how a drain that starts busy
            # and becomes exclusive (or the reverse) is expressed: `idle` is re-read per
            # batch precisely because the operator may go online while it runs.
            running = state["scheduler_running"]
            if isinstance(running, list):
                return running.pop(0) if running else False
            return running

    import contextlib

    monkeypatch.setattr("src.backup.merge.reindex_backlog", _backlog)
    monkeypatch.setattr("src.backup.merge.reindex_imported_articles", _reindex)
    monkeypatch.setattr("src.backup.merge.import_reindex_commit_batch", lambda: 200)
    monkeypatch.setattr(
        "src.backup.merge.default_reindex_commit_batch",
        lambda: int(state["env_commit_batch"]),
    )
    monkeypatch.setattr("src.scheduler.runner.get_scheduler", lambda: _Sched())
    monkeypatch.setattr(bv2, "exclusive_window_open", lambda: state["exclusive"])
    monkeypatch.setattr(
        "src.database.corpus_lease.corpus_lease", lambda *_a, **_k: contextlib.nullcontext()
    )
    monkeypatch.setattr(
        "src.database.session.session_scope", lambda *_a, **_k: contextlib.nullcontext(object())
    )
    monkeypatch.setattr(
        "src.analytics.corpus_epoch.bump_corpus_epoch",
        lambda _s, *, reason="": rec["bumps"].append(reason) or 1,
    )

    def _open(_s, *, reason="", now=None):
        if not state["deferral_can_open"]:
            raise RuntimeError("marker unavailable")
        rec["deferrals"].append(reason)
        return "2026-09-23T00:00:00+00:00"

    def _finish(_s):
        rec["finishes"].append(True)
        return {"reconciled": True, "closed": True, "complete": True}

    monkeypatch.setattr("src.analytics.counter_deferral.open_deferral", _open)
    monkeypatch.setattr("src.analytics.store.finish_deferral", _finish)
    return state, rec


# --------------------------------------------------------------------------- #
# 1. The settings                                                             #
# --------------------------------------------------------------------------- #


def test_an_idle_collector_gets_the_imports_wide_commit_batch(drain):
    state, rec = drain
    state["scheduler_running"] = False

    out = bv2._reindex_resume_worker(_Ctx())

    assert [c["commit_batch"] for c in rec["calls"]] == [200, 200]
    assert [b["exclusive_settings"] for b in out["batches"]] == [True, True]


def test_a_live_collector_keeps_the_conservative_default(drain):
    """``OO_REINDEX_COMMIT_BATCH``, whose default is 1 -- the right answer while a
    scrape needs the writer gate back between articles."""
    state, rec = drain
    state["scheduler_running"] = True

    out = bv2._reindex_resume_worker(_Ctx())

    assert [c["commit_batch"] for c in rec["calls"]] == [1, 1]
    assert [b["exclusive_settings"] for b in out["batches"]] == [False, False]


def test_the_reported_width_is_the_env_var_not_an_assumed_default(drain):
    """THE FABRICATION THIS AVOIDS: the audit's own operator step sets
    ``OO_REINDEX_COMMIT_BATCH=200``, so a reporter that assumed the default's default
    would publish "1" for a run that committed in batches of 200 -- a made-up number
    inside a measurement. The width is RESOLVED and passed explicitly."""
    state, rec = drain
    state["scheduler_running"] = True
    state["env_commit_batch"] = 200

    ctx = _Ctx()
    bv2._reindex_resume_worker(ctx)

    assert [c["commit_batch"] for c in rec["calls"]] == [200, 200]
    assert ctx.metrics["commit_batch_seen"] == [200]
    # ...and it is still the SHARED path: the settings are the operator's, not ours.
    assert ctx.metrics["shared_articles"] == 4
    assert ctx.metrics["exclusive_articles"] == 0


def _goes_online_after_the_first_read(monkeypatch) -> None:
    """The operator turns collection on mid-drain: idle for the first read, live after."""
    seen = {"n": 0}

    class _Flipping:
        def is_running(self):
            seen["n"] += 1
            return seen["n"] > 1

    monkeypatch.setattr("src.scheduler.runner.get_scheduler", lambda: _Flipping())


def test_the_settings_are_re_read_per_batch(drain, monkeypatch):
    """A drain measured in days must follow the machine it is actually on: an operator
    who goes online mid-run gets the conservative default from the next batch."""
    state, rec = drain
    _goes_online_after_the_first_read(monkeypatch)
    bv2._reindex_resume_worker(_Ctx())
    assert [c["commit_batch"] for c in rec["calls"]] == [200, 1]


def test_an_unreadable_scheduler_is_never_idle(drain, monkeypatch):
    """Unknown ownership is never assumed ownership -- the same direction
    ``owns_the_machine`` fails in."""
    state, rec = drain

    def _boom():
        raise RuntimeError("no scheduler here")

    monkeypatch.setattr("src.scheduler.runner.get_scheduler", _boom)
    bv2._reindex_resume_worker(_Ctx())
    assert [c["commit_batch"] for c in rec["calls"]] == [1, 1]


def test_workers_are_left_alone(drain):
    """Audit §9.1 step 3. This machine is write-bound; more precompute cores would only
    fill the apply queue faster, and the worker count is what the A/B still must
    measure. Passing it would silently settle an open question."""
    state, rec = drain
    bv2._reindex_resume_worker(_Ctx())
    assert all("workers" not in c["extra"] for c in rec["calls"]), (
        "the worker count is what the A/B still has to measure; passing it settles it"
    )
    # The knob set is pinned too, so a future knob has to be added HERE deliberately
    # rather than arriving unnoticed -- which is what the original `extra == {}` was
    # really guarding, before R22 gave this call site its first legitimate extra.
    assert [set(c["extra"]) for c in rec["calls"]] == [{"defer_counters"}, {"defer_counters"}]


# --------------------------------------------------------------------------- #
# 2. The published split                                                      #
# --------------------------------------------------------------------------- #


def test_the_phase_split_is_published_live_and_accumulates(drain):
    state, rec = drain
    ctx = _Ctx()

    out = bv2._reindex_resume_worker(ctx)

    assert len(ctx.metrics_history) == 2, "one publish per finished batch"
    first, second = ctx.metrics_history
    assert first["articles"] == 2 and second["articles"] == 4
    assert second["apply_s"] == pytest.approx(13.0)
    assert second["apply_index_s"] == pytest.approx(8.0)
    assert second["apply_commit_s"] == pytest.approx(4.0)
    assert second["mentions_written"] == 40
    # ...and banked in the result, so a finished run is still readable.
    assert out["stats"] == second


def test_the_split_names_which_settings_produced_the_seconds(drain, monkeypatch):
    """The same apply_s means different things at commit batch 1 and at 200, and that
    comparison is the entire point of letting the drain use the import's settings."""
    state, rec = drain
    _goes_online_after_the_first_read(monkeypatch)
    ctx = _Ctx()
    bv2._reindex_resume_worker(ctx)

    assert ctx.metrics["exclusive_articles"] == 2
    assert ctx.metrics["shared_articles"] == 2
    assert ctx.metrics["commit_batch_seen"] == [1, 200]


def test_the_rate_is_computed_from_the_accumulated_totals(drain):
    """Not an average of per-batch rates, which would weight a tiny batch like a huge
    one: 8 articles across 4.0 s of wall clock is 2.0 a second."""
    state, rec = drain
    state["stats"] = {"articles": 4, "wall_s": 2.0}
    ctx = _Ctx()
    bv2._reindex_resume_worker(ctx)
    assert ctx.metrics["articles"] == 8
    assert ctx.metrics["wall_s"] == pytest.approx(4.0)
    assert ctx.metrics["articles_per_second"] == pytest.approx(2.0)


def test_a_rate_is_never_fabricated_from_a_zero_clock(drain):
    """Both sides of the division must be real -- never an infinity, never a 0.0 that
    reads as "stalled"."""
    state, rec = drain
    state["stats"] = {"articles": 4, "wall_s": 0.0}
    ctx = _Ctx()
    bv2._reindex_resume_worker(ctx)
    assert ctx.metrics["articles"] == 8
    assert ctx.metrics["articles_per_second"] is None


def test_no_measurement_is_never_a_zeroed_split(drain):
    """A batch whose articles were all already re-indexed returns before
    ``reindex_articles`` runs, so it has genuinely nothing to report. Zeros would put a
    fabricated sample in the mean and read as "instant"."""
    state, rec = drain
    state["stats"] = None
    ctx = _Ctx()
    out = bv2._reindex_resume_worker(ctx)
    assert ctx.metrics is None
    assert out["stats"] is None


def test_the_precompute_path_is_carried_so_a_silent_fallback_shows(drain):
    """"pool" versus "serial" is the difference between every core and one."""
    state, rec = drain
    state["stats"] = dict(state["stats"], precompute={"by_path": {"serial": 2}})
    ctx = _Ctx()
    bv2._reindex_resume_worker(ctx)
    assert ctx.metrics["precompute_by_path"] == {"serial": 4}


# --------------------------------------------------------------------------- #
# 3. The epoch                                                                #
# --------------------------------------------------------------------------- #


def test_the_epoch_is_bumped_once_per_run_not_once_per_batch(drain):
    state, rec = drain
    bv2._reindex_resume_worker(_Ctx())

    assert all(c["bump_epoch"] is False for c in rec["calls"]), "the batches must not bump"
    assert rec["bumps"] == ["reindex-resume:start", "reindex-resume:end"]


def test_the_closing_bump_lands_even_when_the_run_is_cancelled(drain):
    """A cancel still leaves every finished article delete-then-reinserted, so a rollup
    snapshotted mid-run must be invalidated whatever ended the run."""
    state, rec = drain

    class _StopsAfterOne(_Ctx):
        @property
        def stopping(self):  # type: ignore[override]
            return len(rec["calls"]) >= 1

        @stopping.setter
        def stopping(self, _v):
            pass

    out = bv2._reindex_resume_worker(_StopsAfterOne())
    assert out["stopped"] is True
    assert len(rec["calls"]) == 1
    assert rec["bumps"] == ["reindex-resume:start", "reindex-resume:end"]


def test_a_run_that_reindexed_nothing_does_not_bump_at_the_end(drain):
    state, rec = drain
    state["batches"] = []
    bv2._reindex_resume_worker(_Ctx())
    assert rec["bumps"] == []


def test_a_failing_epoch_bump_never_breaks_the_drain(drain, monkeypatch):
    """A cache-coordination write may never break, or mask, the work it rides."""
    state, rec = drain

    def _boom(_s, *, reason=""):
        raise RuntimeError("gate unavailable")

    monkeypatch.setattr("src.analytics.corpus_epoch.bump_corpus_epoch", _boom)
    out = bv2._reindex_resume_worker(_Ctx())
    assert out["articles_reindexed"] == 4


# --------------------------------------------------------------------------- #
# 4. R22 — the counters are deferred for the RUN, and the disclosure is lifted  #
#    by the run's own reconcile                                                 #
# --------------------------------------------------------------------------- #


def test_the_marker_opens_once_for_the_run_not_once_per_batch(drain):
    """THE COST GUARD. Per-batch ownership would make every batch reconcile the whole
    corpus at its own end -- two batches here, ten on a real backlog, each a GROUP BY
    over 11 M keywords. That is slower than never deferring, which would make the
    optimisation a pessimisation nobody measured."""
    state, rec = drain
    state["scheduler_running"] = False

    out = bv2._reindex_resume_worker(_Ctx())

    assert rec["deferrals"] == ["reindex-resume"], "opened exactly once for the run"
    assert rec["finishes"] == [True], "and reconciled exactly once, at the end"
    assert [c["extra"]["defer_counters"] for c in rec["calls"]] == [True, True]
    assert [b["counters_deferred"] for b in out["batches"]] == [True, True]
    assert out["counter_reconcile"]["closed"] is True


def test_a_live_collector_never_defers_the_counters(drain):
    """Deferral rides the same exclusivity signal as the commit width. A run that never
    gets the machine must not publish an `estimated` it did not earn."""
    state, rec = drain
    state["scheduler_running"] = True

    out = bv2._reindex_resume_worker(_Ctx())

    assert rec["deferrals"] == [] and rec["finishes"] == []
    assert [c["extra"]["defer_counters"] for c in rec["calls"]] == [False, False]
    assert [b["counters_deferred"] for b in out["batches"]] == [False, False]
    assert "counter_reconcile" not in out


def test_the_marker_opens_lazily_at_the_first_exclusive_batch(drain):
    """`idle` is re-read per batch because the operator may go online mid-run. A drain
    that starts busy and becomes exclusive defers from that batch on, and the marker
    opens THERE -- never at the top, where a run that turns out to never get the machine
    would have published an `estimated` it did not earn."""
    state, rec = drain
    state["scheduler_running"] = [True, False]  # busy for batch 1, idle for batch 2

    out = bv2._reindex_resume_worker(_Ctx())

    assert [c["extra"]["defer_counters"] for c in rec["calls"]] == [False, True]
    assert rec["deferrals"] == ["reindex-resume"], "opened at the first exclusive batch"
    assert rec["finishes"] == [True]
    assert [b["counters_deferred"] for b in out["batches"]] == [False, True]


def test_a_run_that_goes_busy_keeps_the_disclosure_until_its_own_reconcile(drain):
    """The mirror case, and the one where getting it wrong is dishonest rather than
    slow: batch 1 deferred, so its counters ARE drifted. Batch 2 going back to inline
    maintenance must not lift the disclosure early -- only the run's reconcile may."""
    state, rec = drain
    state["scheduler_running"] = [False, True]  # exclusive for batch 1, busy for batch 2

    out = bv2._reindex_resume_worker(_Ctx())

    assert [c["extra"]["defer_counters"] for c in rec["calls"]] == [True, False]
    assert rec["deferrals"] == ["reindex-resume"], "still only opened once"
    assert rec["finishes"] == [True], "and still reconciled once, at the end of the run"
    assert [b["counters_deferred"] for b in out["batches"]] == [True, False], (
        "each batch publishes the regime that produced its numbers"
    )
    assert out["counter_reconcile"]["closed"] is True, (
        "and the run's OWN reconcile is what lifts the disclosure, at the end"
    )


def test_a_marker_that_cannot_open_declines_the_deferral_rather_than_hiding_it(drain):
    """No marker, no deferral. Losing the speed-up is a cost we may pay; losing the
    disclosure is not ours to trade away."""
    state, rec = drain
    state["scheduler_running"] = False
    state["deferral_can_open"] = False

    out = bv2._reindex_resume_worker(_Ctx())

    assert [c["extra"]["defer_counters"] for c in rec["calls"]] == [False, False]
    assert rec["finishes"] == [], "nothing to reconcile if nothing was deferred"
    assert [b["counters_deferred"] for b in out["batches"]] == [False, False]


def test_an_interrupted_drain_still_reconciles_what_it_stopped_maintaining(drain):
    """A cancel does not un-commit the articles already re-indexed, so the counters the
    drain stopped maintaining are drifted whether or not it finished. The reconcile sits
    in a `finally` for exactly that reason -- without it, a cancelled drain would leave
    a corpus whose counters are wrong and whose marker says so forever."""
    state, rec = drain
    state["scheduler_running"] = False

    class _StopAfterFirstBatch(_Ctx):
        """`stopping` flips once the first batch has actually been re-indexed, so the
        top-of-loop check breaks the run with one batch's work committed."""

        def __init__(self, recorded):
            super().__init__()
            self._recorded = recorded

        @property
        def stopping(self):  # type: ignore[override]
            return len(self._recorded["calls"]) >= 1

        @stopping.setter
        def stopping(self, _value):  # the base __init__ assigns it; ignore that
            pass

    out = bv2._reindex_resume_worker(_StopAfterFirstBatch(rec))

    assert out["stopped"] is True
    assert len(rec["calls"]) == 1, "precondition: exactly one batch ran before the stop"
    assert rec["calls"][0]["extra"]["defer_counters"] is True
    assert rec["finishes"] == [True], "the cancelled run still reconciled its own drift"
    assert out["counter_reconcile"]["closed"] is True
