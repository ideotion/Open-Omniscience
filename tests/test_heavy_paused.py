"""A scan paused on purpose reaches the screen as the named pause, never as a replayed failure or "No data".

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

While the write-ahead-log latch is engaged ``run_heavy`` raises a typed ``HeavyPaused`` for every uncached heavy
compute (cached answers are still served). ``_deadlined`` turns it into a 503 with ``Retry-After: 10`` and the pause's
own words, whether the class is a kind of ``HeavyBusy`` or not; nothing is stored (nothing was computed, and a replay
would go on naming a pause that has ended); the Home strip and the map show the words, and Home's back-off treats the
503 like any other refusal (the node suite, ``tests/heavy_paused_ui_node_test.js``). Until the real class lands this
file uses a stand-in of the same NAME, which is all ``_deadlined`` matches on.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

import src.api.insights as ins
from src.api.heavy import HeavyBusy

WORDS = "Scans are paused while the database log is being checkpointed (WAL pause); try again shortly."


class HeavyPaused(RuntimeError):  # the stand-in: matched by NAME
    pass


class HeavyPausedBusy(HeavyBusy):  # the other typing the real class might take: a kind of busy
    pass


HeavyPausedBusy.__name__ = "HeavyPaused"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    ins._read_cache._cache.clear()
    ins._degraded_cache._cache.clear()
    monkeypatch.setattr(ins, "statement_deadline", lambda db: contextlib.nullcontext())
    monkeypatch.setattr(ins, "flight_key", lambda db, key: key)
    monkeypatch.setattr(ins, "_degraded_window_s", lambda: 30.0)
    yield
    ins._read_cache._cache.clear()
    ins._degraded_cache._cache.clear()


def _paused_run_heavy(cls, calls):
    def run_heavy(_key, _fn):
        calls.append(1)
        raise cls(WORDS)

    return run_heavy


@pytest.mark.parametrize("cls", [HeavyPaused, HeavyPausedBusy])
@pytest.mark.parametrize("replay", [False, True])
def test_a_pause_is_a_503_with_retry_after_and_the_pauses_own_words(monkeypatch, cls, replay):
    calls: list[int] = []
    monkeypatch.setattr(ins, "run_heavy", _paused_run_heavy(cls, calls))
    with pytest.raises(HTTPException) as got:
        ins._deadlined(object(), "k", lambda: {}, degraded_replay=replay)
    assert got.value.status_code == 503, "not the 429 a busy server gets"
    assert got.value.headers["Retry-After"] == "10"
    assert got.value.headers["X-OO-Paused"] == "wal"
    assert WORDS in got.value.detail


@pytest.mark.parametrize("cls", [HeavyPaused, HeavyPausedBusy])
def test_a_pause_is_never_stored_and_the_next_call_asks_again(monkeypatch, cls):
    calls: list[int] = []
    monkeypatch.setattr(ins, "run_heavy", _paused_run_heavy(cls, calls))
    for _ in range(3):
        with pytest.raises(HTTPException):
            ins._deadlined(object(), "k", lambda: {}, degraded_replay=True)
    assert len(calls) == 3, "it is asked every time, so the answer follows the pause the moment it ends"
    key = ins._bind_key(object(), "k")
    assert not isinstance(ins._read_cache.get(key), dict) and ins._degraded_get(key) is None


def test_the_call_after_the_pause_ends_computes_normally(monkeypatch):
    state = {"paused": True}

    def run_heavy(_key, fn):
        if state["paused"]:
            raise HeavyPaused(WORDS)
        return fn()

    monkeypatch.setattr(ins, "run_heavy", run_heavy)
    with pytest.raises(HTTPException):
        ins._deadlined(object(), "k", lambda: {"v": 1}, degraded_replay=True)
    state["paused"] = False
    assert ins._deadlined(object(), "k", lambda: {"v": 1}, degraded_replay=True)["v"] == 1


def test_a_real_busy_is_still_a_429(monkeypatch):
    def busy(_key, _fn):
        raise HeavyBusy("at capacity")

    monkeypatch.setattr(ins, "run_heavy", busy)
    with pytest.raises(HTTPException) as got:
        ins._deadlined(object(), "k", lambda: {})
    assert got.value.status_code == 429 and got.value.headers["Retry-After"] == "2"


def test_other_errors_still_propagate_untouched(monkeypatch):
    def broken(_key, _fn):
        raise ValueError("not a pause")

    monkeypatch.setattr(ins, "run_heavy", broken)
    with pytest.raises(ValueError):
        ins._deadlined(object(), "k", lambda: {})


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_the_screens_show_the_named_pause_node_suite():
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(["node", str(root / "tests" / "heavy_paused_ui_node_test.js")],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ok -" in proc.stdout


class _HttpPaused(HTTPException):
    """The real ``HeavyPaused`` is an ``HTTPException``: it carries its own status, words and headers."""


_HttpPaused.__name__ = "HeavyPaused"


@pytest.mark.parametrize("replay", [False, True])
def test_a_pause_that_is_already_an_http_error_goes_out_as_it_is(monkeypatch, replay):
    """Rebuilt from ``str(exc)`` it answered ``503: Paused ...`` (the status twice) and lost its type and headers."""
    original = _HttpPaused(status_code=503, detail=WORDS, headers={"Retry-After": "7", "X-OO-Paused": "wal"})

    def run_heavy(_key, _fn):
        raise original

    monkeypatch.setattr(ins, "run_heavy", run_heavy)
    with pytest.raises(HTTPException) as got:
        ins._deadlined(object(), "k", lambda: {}, degraded_replay=replay)
    assert got.value is original, "the same object, so its type is kept"
    assert got.value.detail == WORDS and "503" not in got.value.detail
    assert got.value.headers == {"Retry-After": "7", "X-OO-Paused": "wal"}, "its own headers, not ours"
