"""A-026 (audit P12): while the rollup is declined, a served read does not re-run the verdict chain on every request.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Measured with the real ``_build_and_swap`` and a verdict that always declines (mem-low): 200 served reads asked the verdict chain 200
times before (each read started a build thread), and once after, until ``_DECLINE_GAP_S`` passes.
"""

from __future__ import annotations

import threading

import pytest

from src.analytics import rollup_serve as rs


@pytest.fixture
def declining(monkeypatch):
    asked: list[int] = []

    def _verdict():
        asked.append(1)
        return {"reason": "mem-low", "guard_reason": "mem-low"}, "memory"

    monkeypatch.setattr(rs, "first_start_decline", _verdict)
    monkeypatch.setattr(rs, "serve_enabled", lambda: True)
    monkeypatch.setitem(rs._STATE, "con", None)
    monkeypatch.setitem(rs._DECLINED_AT, "t", None)
    clock = {"now": 1000.0}
    monkeypatch.setattr(rs.time, "monotonic", lambda: clock["now"])
    # Run the build inline so the count is deterministic (the thread would do exactly this).
    monkeypatch.setattr(rs.threading, "Thread", _InlineThread)
    yield asked, clock
    rs._DECLINED_AT["t"] = None


class _InlineThread:
    def __init__(self, target, name=None, daemon=None):
        self._target = target

    def start(self):
        self._target()


def test_a_declined_rollup_asks_the_verdicts_once_per_gap_not_once_per_read(declining):
    asked, clock = declining
    for _ in range(200):
        assert rs.windowed_rows(object(), days=7) is None  # the live fallback, unchanged
    assert len(asked) == 1, f"the verdict chain ran {len(asked)} times for 200 reads"
    clock["now"] += rs._DECLINE_GAP_S + 0.1
    rs.windowed_rows(object(), days=7)
    assert len(asked) == 2, "after the gap the next read asks again, so a recovered machine builds"
    assert not rs._BUILD_LOCK.locked()


def test_a_build_that_was_not_declined_clears_the_gap(declining, monkeypatch):
    asked, _clock = declining
    rs.windowed_rows(object(), days=7)
    assert rs._DECLINED_AT["t"] is not None
    monkeypatch.setattr(rs, "first_start_decline", lambda: (None, None))
    monkeypatch.setattr(rs, "_persisted_serve_active", lambda: (_ for _ in ()).throw(RuntimeError("stop here")))
    rs._DECLINED_AT["t"] = None
    rs.windowed_rows(object(), days=7)  # runs past the verdicts and fails: outcome "failed", not "declined"
    assert rs._DECLINED_AT["t"] is None


def test_the_gap_is_short():
    assert 0 < rs._DECLINE_GAP_S <= 60
    assert isinstance(threading.Lock(), type(rs._BUILD_LOCK))


def test_a_hold_decline_is_not_gated(declining, monkeypatch):
    """A hold or last-build decline changes on an event (a released hold): the next read must ask again at once."""
    asked, _clock = declining
    monkeypatch.setattr(rs, "first_start_decline", lambda: (asked.append(1) or {"reason": "build-failed"}, "stopped"))
    for _ in range(3):
        rs.windowed_rows(object(), days=7)
    assert len(asked) == 3
