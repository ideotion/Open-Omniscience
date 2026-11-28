"""Row 446 (P1): the re-index drain holds the writer longer only while nothing else should be writing, and gives it back as before.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Measured on a 150k encrypted store: a commit writes about 3.6 MB of WAL per article, so batches of 500 instead of about 160 cut
commit time by half. While the collector is stopped and no import window is open (the drain's idle branch), or while an import owns
the machine, a batch may now hold the single-writer gate for 30 s instead of 10 s, up to the 500-article precompute window. Pinned:

1. a queued writer (a UI save) still ends the batch after 1 s of held gate;
2. if the collector starts mid-batch, it is a queued writer under that same rule, and the next question reads the general 10 s,
   never 30 (the next batch then takes R724's 2 s);
3. the worst-case hold stays well under the write-gate watchdog's 60 s, and no override can raise the target past the cap;
4. the restore's inline re-index takes the higher target only inside the exclusive window, and falls back the moment it closes.
"""

from __future__ import annotations

import pytest

from src.api import backup_v2 as bv2
from src.backup import merge as M
from tests.test_reindex_drain_settings import _Ctx, drain  # noqa: F401 - the fixture is used by name

_ENV = (
    "OO_REINDEX_HOLD_TARGET_S",
    "OO_REINDEX_OWNED_HOLD_TARGET_S",
    "OO_IMPORT_REINDEX_COMMIT_BATCH",
    "OO_WRITE_GATE_WARN_S",
)


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    for var in _ENV:
        monkeypatch.delenv(var, raising=False)


class _Sched:
    def __init__(self, running: bool = False) -> None:
        self.running = running

    def is_running(self) -> bool:
        return self.running


def _idle_policy(drain, monkeypatch, waiters):  # noqa: ANN001, ANN202, F811
    state, rec = drain
    sched = _Sched(False)
    monkeypatch.setattr("src.scheduler.runner.get_scheduler", lambda: sched)
    monkeypatch.setattr("src.database.writer.write_gate_waiters", lambda: waiters["n"])
    ctx = _Ctx()
    bv2._reindex_resume_worker(ctx)
    return rec["calls"][0], sched, ctx


def test_the_idle_drain_takes_the_wide_batch_under_the_owned_target(drain, monkeypatch):  # noqa: F811
    waiters = {"n": 0}
    call, _sched, ctx = _idle_policy(drain, monkeypatch, waiters)
    assert call["commit_batch"] == M.REINDEX_OWNED_COMMIT_BATCH == 500
    policy = call["extra"]["should_flush"]
    assert policy(50, 10.0) is False and policy(50, 29.9) is False, "nobody else writes: the batch keeps the gate past 10 s"
    assert policy(50, 30.0) is True, "the owned target, thirty seconds"
    assert ctx.metrics["hold_target_seen"] == [30.0], "the target in force is the one published"


def test_a_queued_ui_save_still_ends_the_idle_batch_after_one_second(drain, monkeypatch):  # noqa: F811
    waiters = {"n": 0}
    call, _sched, _ctx = _idle_policy(drain, monkeypatch, waiters)
    policy = call["extra"]["should_flush"]
    waiters["n"] = 1  # a save from the UI arrives and queues on the gate
    assert policy(5, 0.9) is False, "the 1 s floor still protects the drain's apply cost"
    assert policy(5, 1.0) is True, "the save waits about a second, not thirty"


def test_a_collector_that_starts_mid_batch_is_a_queued_writer_and_the_target_falls_back(drain, monkeypatch):  # noqa: F811
    waiters = {"n": 0}
    call, sched, _ctx = _idle_policy(drain, monkeypatch, waiters)
    policy = call["extra"]["should_flush"]
    assert policy(50, 15.0) is False, "idle: still under the owned target"
    sched.running = True  # the operator starts collecting while this batch is open
    assert policy(50, 15.0) is True, "re-read at the very next question: the general 10 s, never 30"
    assert policy(50, 9.9) is False
    waiters["n"] = 1  # the collector's first flush queues on the gate
    assert policy(3, 1.0) is True, "the collector wins the gate after 1 s, as every queued writer does"


def test_an_unreadable_scheduler_mid_batch_is_never_ownership(drain, monkeypatch):  # noqa: F811
    """The question re-reads the scheduler; one that cannot be read is never idle, so the general target applies."""
    waiters = {"n": 0}
    call, _sched, _ctx = _idle_policy(drain, monkeypatch, waiters)
    policy = call["extra"]["should_flush"]

    def _boom():
        raise RuntimeError("no scheduler")

    monkeypatch.setattr("src.scheduler.runner.get_scheduler", _boom)
    assert policy(50, 10.0) is True, "unknown ownership is never ownership"


def test_the_worst_case_hold_stays_well_under_the_watchdog():
    """A hold is the target, plus the article in flight, plus the commit. The bench's slowest commit at width 500 was about 7 s and
    its longest hold 37.8 s; even doubling the commit and allowing 5 s for one article leaves a margin under the 60 s threshold."""
    from src.database.writer import _watchdog_threshold_s

    worst_commit_s, worst_article_s = 2 * 7.0, 5.0
    worst = M.REINDEX_OWNED_HOLD_TARGET_S + worst_article_s + worst_commit_s
    assert worst <= _watchdog_threshold_s() - 10.0, worst
    assert M.REINDEX_OWNED_HOLD_TARGET_S <= M.REINDEX_HOLD_TARGET_S * 3


@pytest.mark.parametrize(
    ("raw", "want"),
    [("", 30.0), ("junk", 30.0), ("nan", 30.0), ("-1", 30.0), ("90", 30.0), ("20", 20.0), ("0", 10.0)],
)
def test_no_override_raises_the_owned_target_past_its_cap(monkeypatch, raw, want):
    monkeypatch.setenv("OO_REINDEX_OWNED_HOLD_TARGET_S", raw)
    assert M.reindex_owned_hold_target_s() == want


def test_the_operators_general_target_is_the_owned_one_too(monkeypatch):
    monkeypatch.setenv("OO_REINDEX_HOLD_TARGET_S", "5")
    assert M.reindex_owned_hold_target_s() == 5.0
    monkeypatch.setenv("OO_REINDEX_HOLD_TARGET_S", "0")
    assert M.reindex_owned_hold_target_s() == 0.0, "count-only in general is count-only when owned"
    assert M.reindex_flush_policy(0.0, owned_target_s=30.0, owned=lambda: True) is None


def test_the_operators_width_wins(monkeypatch):
    monkeypatch.setenv("OO_IMPORT_REINDEX_COMMIT_BATCH", "50")
    assert M.reindex_owned_commit_batch() == 50
    monkeypatch.delenv("OO_IMPORT_REINDEX_COMMIT_BATCH")
    assert M.reindex_owned_commit_batch() == 500


def test_the_restore_takes_the_owned_target_only_inside_the_window(monkeypatch):
    window = {"open": True}
    monkeypatch.setattr("src.scheduler.runner.exclusive_window_open", lambda: window["open"])
    monkeypatch.setattr("src.database.writer.write_gate_waiters", lambda: 0)
    stats: dict = {}
    policy = M._restore_reindex_policy(stats)
    assert stats == {"hold_target_s": 10.0, "owned_hold_target_s": 30.0}
    assert policy(50, 29.9) is False and policy(50, 30.0) is True
    window["open"] = False  # the import's exclusive window ends while the batch is open
    assert policy(50, 10.0) is True, "the target falls back to 10 s the moment the window ends"
    assert policy(50, 9.9) is False
