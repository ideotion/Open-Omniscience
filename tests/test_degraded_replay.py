"""A heavy read that just failed or came back partial is answered again from that outcome, briefly, not rescanned.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

2026-10-16, a running install whose rollup build had been stopped: Home's 15 s tick asked /api/insights/trending-windows
533 times, 362 of them ended in the 60 s statement deadline (503), and the one connection to the corpus spent 75% of
the session on that question. Single-flight already shares ONE compute between concurrent identical calls; what was
missing is the call that arrives a moment AFTER a failed one. ``_deadlined(degraded_replay=True)`` keeps the outcome for
a stated window (``OO_DEGRADED_REPLAY_S``, default 30 s, 0 = off) in a store of its own: a 503 is replayed with a
``Retry-After`` of what is left; a ``partial: true`` payload is replayed marked ``replayed`` and is NEVER stored in the
normal cache as if it were whole; a full answer in the normal cache always wins. Only the polled trending-windows read
opts in.
"""

from __future__ import annotations

import contextlib

import pytest
from fastapi import HTTPException

import src.api.insights as ins
from src.database.maintenance import StatementTimeout


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    ins._read_cache._cache.clear()
    ins._degraded_cache._cache.clear()
    monkeypatch.setattr(ins, "statement_deadline", lambda db: contextlib.nullcontext())
    monkeypatch.setattr(ins, "run_heavy", lambda key, fn: fn())
    monkeypatch.setattr(ins, "flight_key", lambda db, key: key)
    monkeypatch.setattr(ins, "_degraded_window_s", lambda: 30.0)
    yield
    ins._read_cache._cache.clear()
    ins._degraded_cache._cache.clear()


class Counter:
    def __init__(self, result=None, raises=None):
        self.n, self.result, self.raises = 0, result, raises

    def __call__(self):
        self.n += 1
        if self.raises is not None:
            raise self.raises
        return dict(self.result)


def _ask(compute, *, replay=True):
    return ins._deadlined(object(), "tw|k", compute, degraded_replay=replay)


def test_a_deadline_503_is_replayed_without_a_second_scan_and_says_how_long_is_left():
    compute = Counter(raises=StatementTimeout("the read ran past its deadline"))
    with pytest.raises(HTTPException) as first:
        _ask(compute)
    with pytest.raises(HTTPException) as second:
        _ask(compute)
    assert compute.n == 1, "the second call must not start another scan"
    assert first.value.status_code == second.value.status_code == 503
    assert second.value.detail == first.value.detail
    assert 1 <= int(second.value.headers["Retry-After"]) <= 31


def test_a_partial_answer_is_replayed_still_partial_with_its_caveat_and_never_stored_as_a_whole_one():
    compute = Counter(result={"windows": [1], "partial": True, "caveat": "the 30 d window was not computed"})
    one = _ask(compute)
    ins._degraded_cache.get(next(iter(ins._degraded_cache._cache)))["stored_at"] -= 7.0  # the original is 7 s old
    two = _ask(compute)
    assert compute.n == 1
    assert one["partial"] and one["cached"] is False and "replayed" not in one
    assert two["partial"] is True and two["caveat"] == "the 30 d window was not computed", "still partial, still says so"
    assert two["cached"] is True and two["replayed"] is True
    assert 6.5 <= two["replayed_age_s"] <= 8.5 and two["replay_window_s"] == 30.0
    assert not isinstance(ins._read_cache.get(ins._bind_key(object(), "tw|k")), dict), "a partial is not a cached result"


def test_a_full_answer_is_cached_as_before_and_wins_over_a_replayable_outcome():
    ins._degraded_put(ins._bind_key(object(), "tw|k"), "failure", "a stale failure")
    ins._read_cache.set(ins._bind_key(object(), "tw|k"), {"windows": [1], "full": True})
    got = _ask(Counter(result={"never": "called"}))
    assert got["full"] is True and got["cached"] is True


def test_a_full_answer_computed_now_goes_to_the_normal_cache_only():
    compute = Counter(result={"windows": [1]})
    _ask(compute)
    _ask(compute)
    assert compute.n == 1
    assert ins._degraded_get(ins._bind_key(object(), "tw|k")) is None


def test_the_window_ends_and_the_next_call_scans_again(monkeypatch):
    compute = Counter(raises=StatementTimeout("late"))
    with pytest.raises(HTTPException):
        _ask(compute)
    item = ins._degraded_cache.get(next(iter(ins._degraded_cache._cache)))
    item["stored_at"] -= 31.0  # age the stored outcome past its window
    with pytest.raises(HTTPException):
        _ask(compute)
    assert compute.n == 2, "after the window the read is allowed to try again"


def test_a_window_of_zero_turns_it_off(monkeypatch):
    monkeypatch.setattr(ins, "_degraded_window_s", lambda: 0.0)
    compute = Counter(raises=StatementTimeout("late"))
    for _ in range(2):
        with pytest.raises(HTTPException):
            _ask(compute)
    assert compute.n == 2


def test_only_an_opted_in_read_replays():
    compute = Counter(raises=StatementTimeout("late"))
    for _ in range(2):
        with pytest.raises(HTTPException):
            _ask(compute, replay=False)
    assert compute.n == 2, "every other heavy read recomputes after a failure, exactly as before"
    part = Counter(result={"partial": True})
    _ask(part, replay=False)
    assert isinstance(ins._read_cache.get(ins._bind_key(object(), "tw|k")), dict), "unchanged for the others"


def test_busy_and_on_timeout_paths_are_untouched():
    compute = Counter(raises=StatementTimeout("late"))
    got = ins._deadlined(object(), "tw|k", compute, on_timeout=lambda exc: {"degraded": True}, degraded_replay=True)
    assert got == {"degraded": True}
    assert ins._degraded_get(ins._bind_key(object(), "tw|k")) is None, "an on_timeout payload is not a replayable failure"


def test_the_two_polled_or_opened_whole_corpus_reads_opt_in_and_nothing_else_does():
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(ins))
    users = [
        fn.name
        for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef)
        for call in ast.walk(fn)
        if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "_deadlined"
        and any(k.arg == "degraded_replay" and getattr(k.value, "value", None) is True for k in call.keywords)
    ]
    assert sorted(users) == ["insights_map", "insights_trending_windows"], "widening this is a decision, not a drift"
