"""Tests for src.backup.timing.StageTimings (field-feedback Session A §4).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The one property that MUST hold, above all others: a timer must NEVER swallow
an exception raised inside the timed block -- this module wraps the most
data-safety-critical function in the app (run_restore), and a timing helper
that turned a real failure into a silent success would be catastrophic.
"""

from __future__ import annotations

import time

import pytest

from src.backup.timing import StageTimings


def test_stage_records_a_real_elapsed_duration():
    t = StageTimings()
    with t.stage("sleep"):
        time.sleep(0.01)
    rep = t.report()
    assert rep["stages"]["sleep"] >= 0.01
    assert rep["wall_s"] >= rep["stages"]["sleep"]


def test_multiple_stages_preserve_first_recorded_order():
    t = StageTimings()
    with t.stage("b"):
        pass
    with t.stage("a"):
        pass
    with t.stage("c"):
        pass
    assert list(t.report()["stages"].keys()) == ["b", "a", "c"]


def test_record_accepts_an_externally_measured_duration():
    t = StageTimings()
    t.record("external", 2.5)
    assert t.report()["stages"]["external"] == 2.5


def test_re_recording_a_stage_overwrites_the_value_keeps_its_position():
    t = StageTimings()
    with t.stage("x"):
        pass
    with t.stage("y"):
        pass
    t.record("x", 9.999)
    rep = t.report()
    assert rep["stages"]["x"] == 9.999
    assert list(rep["stages"].keys()) == ["x", "y"]  # position unchanged, not re-appended


def test_wall_s_is_the_total_elapsed_never_the_sum_of_stages():
    """Two stages with an untimed gap between them: wall_s must reflect the
    REAL elapsed time (including the gap), never a fabricated sum-of-stages
    total that would understate it."""
    t = StageTimings()
    with t.stage("a"):
        time.sleep(0.01)
    time.sleep(0.01)  # untimed gap -- must still count toward wall_s
    with t.stage("b"):
        time.sleep(0.01)
    rep = t.report()
    stage_sum = rep["stages"]["a"] + rep["stages"]["b"]
    assert rep["wall_s"] > stage_sum  # the gap is real and must not be hidden


# --------------------------------------------------------------------------- #
# THE load-bearing property: an exception inside a timed block must propagate
# UNCHANGED (never swallowed, never wrapped, never replaced) -- and the
# partial timing up to the failure must still be recorded (useful for
# diagnosing WHERE a crash happened), never silently dropped.
# --------------------------------------------------------------------------- #


def test_an_exception_inside_a_stage_propagates_unchanged():
    t = StageTimings()

    class _Boom(RuntimeError):
        pass

    with pytest.raises(_Boom, match="specific failure"):
        with t.stage("doomed"):
            raise _Boom("a specific failure message")


def test_the_stage_that_raised_is_still_timed_before_propagating():
    t = StageTimings()

    with pytest.raises(ValueError):
        with t.stage("doomed"):
            time.sleep(0.005)
            raise ValueError("boom")

    # the partial duration up to the raise is real evidence, not discarded.
    assert t.report()["stages"]["doomed"] >= 0.005


def test_a_stage_after_a_failed_one_still_reports_correctly():
    """A caller that catches the exception from one stage and continues (as
    run_restore's own best-effort blocks do) must see BOTH stages' timings,
    the failed one included -- never a corrupted/half-written accumulator."""
    t = StageTimings()
    try:
        with t.stage("first"):
            raise RuntimeError("first failed")
    except RuntimeError:
        pass
    with t.stage("second"):
        pass
    rep = t.report()
    assert set(rep["stages"]) == {"first", "second"}


# --------------------------------------------------------------------------- #
# on_start -- live phase pings (field-feedback Session A §4, "progress
# everywhere": stages that otherwise have no progress callback of their own).
# --------------------------------------------------------------------------- #


def test_on_start_fires_with_the_stage_name_before_the_work_runs():
    seen: list[str] = []
    t = StageTimings(on_start=seen.append)
    with t.stage("a"):
        assert seen == ["a"]  # fired BEFORE the work, not after
        time.sleep(0.001)
    with t.stage("b"):
        pass
    assert seen == ["a", "b"]


def test_on_start_is_optional_and_defaults_to_none():
    t = StageTimings()  # no on_start given
    with t.stage("x"):
        pass  # must not raise -- the hook is genuinely optional


def test_a_raising_on_start_never_breaks_the_timed_stage():
    def _boom(name):
        raise RuntimeError("progress sink exploded")

    t = StageTimings(on_start=_boom)
    with t.stage("resilient"):
        pass  # the raising hook must not propagate or skip the stage
    assert t.report()["stages"]["resilient"] >= 0


def test_on_start_still_fires_even_when_the_stage_itself_raises():
    seen: list[str] = []
    t = StageTimings(on_start=seen.append)
    with pytest.raises(ValueError):
        with t.stage("doomed"):
            raise ValueError("boom")
    assert seen == ["doomed"]  # the ping happened before the failure


def test_negative_elapsed_never_produced_even_if_clock_is_odd():
    """record() defensively floors at 0 -- a caller handing in a negative
    duration (e.g. a mis-measured external timer) must never produce a
    nonsensical negative stage time in the report."""
    t = StageTimings()
    t.record("weird", -0.5)
    assert t.report()["stages"]["weird"] == 0.0
