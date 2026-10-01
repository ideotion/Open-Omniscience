"""The three heavy start-up jobs run one after the other (diagnostics 2026-09-30, cause C).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The crashing instance began the cache warm-up, the in-memory rollup and the re-index resume within
the same minute and was SIGKILLed with all three running. ``src/api/boot_sequence.py`` runs them in
one thread: warm-up, then the rollup's first build, then the re-index resume. No clock and no
database here: the steps are fakes that record when they start and end.
"""

from __future__ import annotations

import logging
import threading

import pytest

from src.api import boot_sequence as bs


@pytest.fixture
def seq(monkeypatch):
    """The sequence with fake steps; ``log`` records ('start'|'end', step) in order."""
    log: list[tuple[str, str]] = []
    monkeypatch.setitem(bs._STATE, "reindex_pending", None)
    monkeypatch.setitem(bs._STATE, "warm", "pending")
    bs._reset()

    def step(name, *, raises=False):
        def _s():
            log.append(("start", name))
            if raises:
                raise RuntimeError(name)
            log.append(("end", name))
        return _s

    monkeypatch.setattr(bs, "_rollup_first_build", step("rollup"))
    import src.backup.volume_job as vj

    def _drain():
        log.append(("start", "reindex"))
        return True, None

    monkeypatch.setattr(vj, "start_reindex_drain", _drain)
    return log, step


def test_the_steps_run_in_order_and_each_ends_before_the_next_starts(seq):
    log, step = seq
    bs.request_reindex(5)
    bs.run(step("warm"))
    assert log == [("start", "warm"), ("end", "warm"), ("start", "rollup"), ("end", "rollup"), ("start", "reindex")]


def test_the_re_index_is_not_started_unless_it_was_asked_for(seq):
    log, step = seq
    bs.run(step("warm"))
    assert ("start", "reindex") not in log


@pytest.mark.parametrize("failing", ["warm", "rollup"])
def test_a_step_that_raises_is_logged_and_the_next_one_still_runs(seq, monkeypatch, caplog, failing):
    log, step = seq
    if failing == "rollup":
        monkeypatch.setattr(bs, "_rollup_first_build", step("rollup", raises=True))
    bs.request_reindex(5)
    with caplog.at_level(logging.WARNING, logger=bs.__name__):
        bs.run(step("warm", raises=failing == "warm"))
    assert ("start", "reindex") in log, "a failed step must not keep the re-index from starting"
    assert any("failed" in r.message for r in caplog.records)


def test_the_warm_flag_is_up_only_while_the_warm_step_runs(seq):
    log, _step = seq
    seen: list[bool] = []

    def warm():
        seen.append(bs.warm_running())

    assert bs.warm_running() is False
    bs.run(warm)
    assert seen == [True] and bs.warm_running() is False


def test_the_flag_comes_down_even_when_the_warm_step_raises(seq):
    def warm():
        raise RuntimeError("boom")

    bs.run(warm)
    assert bs.warm_running() is False


def test_a_slow_step_is_a_warning_naming_what_waited_behind_it(seq, monkeypatch, caplog):
    _log, step = seq
    ticks = iter([0.0, bs.SLOW_STEP_S, bs.SLOW_STEP_S, bs.SLOW_STEP_S + 1, bs.SLOW_STEP_S + 1, bs.SLOW_STEP_S + 2])
    monkeypatch.setattr(bs.time, "monotonic", lambda: next(ticks))
    with caplog.at_level(logging.WARNING, logger=bs.__name__):
        bs.run(step("warm"))
    assert any("warm-cache took" in r.message and "the rollup build and the re-index waited" in r.message
               for r in caplog.records)


# ----------------------------------------------------------------------------- what the bundle shows
def _by_step(snap):
    return {row["step"]: row for row in snap["steps"]}


def test_the_snapshot_says_every_steps_final_state(seq, monkeypatch):
    log, step = seq
    bs.request_reindex(5)
    monkeypatch.setattr(bs, "_rollup_first_build", step("rollup", raises=True))
    bs.run(step("warm"))
    rows = _by_step(bs.snapshot())
    assert {k: v["state"] for k, v in rows.items()} == {
        "warm-cache": "done", "rollup": "failed", "reindex-resume": "done",
    }
    assert bs.snapshot()["order"] == ["warm-cache", "rollup", "reindex-resume"]
    assert all(v["started_at"] and v["seconds"] is not None for v in rows.values())


def test_a_step_with_nothing_to_do_is_skipped_not_failed(seq):
    log, step = seq
    bs.run(step("warm"))  # no re-index was asked for
    assert _by_step(bs.snapshot())["reindex-resume"]["state"] == "skipped"


def test_a_stuck_step_shows_as_running_with_its_seconds_and_the_ones_behind_it_as_waiting(seq):
    """No timeout, so the wait has to be visible: who is running, for how long, who waits."""
    _log, _step = seq
    inside = threading.Event()
    release = threading.Event()
    seen: dict = {}

    def warm():
        inside.set()
        release.wait(5)

    t = threading.Thread(target=bs.run, args=(warm,))
    t.start()
    assert inside.wait(5)
    seen = _by_step(bs.snapshot())
    release.set()
    t.join(5)
    assert seen["warm-cache"]["state"] == "running" and seen["warm-cache"]["seconds"] >= 0
    assert seen["rollup"]["state"] == "pending" and "waited_s" in seen["rollup"]
    assert seen["reindex-resume"]["state"] == "pending" and "waited_s" in seen["reindex-resume"]


def test_the_snapshot_reaches_the_diagnostics_bundle_and_says_what_it_does_not_wait_for():
    from src.api.diagnostics import columnar_status

    block = columnar_status()["boot_sequence"]
    assert block["order"] == ["warm-cache", "rollup", "reindex-resume"]
    assert "beside it" in block["method"] and "memory" in block["method"]


# ------------------------------------------------------------------------------- the rollup side
def test_the_rollup_declines_while_the_warm_step_runs_and_says_why(monkeypatch):
    from src.analytics import rollup_serve

    monkeypatch.setitem(bs._STATE, "warm", "running")
    verdict = rollup_serve._boot_order_verdict()
    assert verdict is not None and verdict["reason"] == "boot_order"
    monkeypatch.setitem(bs._STATE, "warm", "done")
    assert rollup_serve._boot_order_verdict() is None


def test_build_now_and_wait_builds_in_the_calling_thread_and_releases_the_lock(monkeypatch):
    from src.analytics import rollup_serve

    ran: list[int] = []

    def fake_build():
        ran.append(threading.get_ident())
        rollup_serve._BUILD_LOCK.release()  # the real one releases in its own finally

    monkeypatch.setattr(rollup_serve, "_build_and_swap", fake_build)
    rollup_serve.build_now_and_wait()
    assert ran == [threading.get_ident()]
    assert not rollup_serve._BUILD_LOCK.locked()


def test_build_now_and_wait_waits_for_a_build_already_running_instead_of_starting_a_second(monkeypatch):
    from src.analytics import rollup_serve

    started: list[int] = []
    monkeypatch.setattr(rollup_serve, "_build_and_swap", lambda: started.append(1))
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
    done = threading.Event()
    t = threading.Thread(target=lambda: (rollup_serve.build_now_and_wait(), done.set()))
    t.start()
    assert not done.wait(0.2), "it returned while a build still held the lock"
    rollup_serve._BUILD_LOCK.release()
    assert done.wait(5)
    t.join(5)
    assert started == [], "a second build was started beside the running one"


def test_the_sequence_does_not_ask_the_rollup_for_a_build_when_serving_is_off(monkeypatch):
    from src.analytics import rollup_serve

    monkeypatch.setattr(rollup_serve, "serve_enabled", lambda: False)
    monkeypatch.setattr(rollup_serve, "build_now_and_wait", lambda: pytest.fail("built with serving off"))
    with pytest.raises(bs._Skipped):
        bs._rollup_first_build()
