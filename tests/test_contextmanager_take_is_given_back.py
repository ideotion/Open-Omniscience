"""The context managers that take shared state give it back when an interrupt lands right after the take (R171).

Each was ``take; try: yield; finally: give back``: an interrupt delivered after the take and before the ``try`` began skipped the give-back.
The scan that finds the shape is ``tests/test_contextmanager_acquire_before_try.py``; ``scripts/signal_leak_probe.py gate_corpus_lease``
(and ``gate_user_batch_hold``, ``gate_inflight``, ``gate_pass_in_flight``) measures it with a real signal. These tests do it
deterministically: the lock the take runs under raises a KeyboardInterrupt when the take's ``with`` block exits, i.e. after the state was
changed and before the caller saw the context manager enter.
"""

from __future__ import annotations

import threading

import pytest


class _InterruptOnFirstExit:
    """A lock that raises KeyboardInterrupt when the FIRST ``with`` block over it ends, after releasing the real lock."""

    def __init__(self) -> None:
        self._real = threading.RLock()
        self.fired = False

    def __enter__(self):
        self._real.acquire()
        return self

    def __exit__(self, *exc):
        self._real.release()
        if not self.fired:
            self.fired = True
            raise KeyboardInterrupt
        return False


def test_a_corpus_lease_interrupted_right_after_it_was_taken_is_given_back(monkeypatch):
    from src.database import corpus_lease as cl

    lock = _InterruptOnFirstExit()
    monkeypatch.setattr(cl, "_LOCK", lock)
    monkeypatch.setattr(cl, "_HELD", {})
    with pytest.raises(KeyboardInterrupt), cl.corpus_lease("probe"):
        pytest.fail("the body must not run")
    assert lock.fired
    assert cl.active_leases() == [], "a lease stayed raised: a library swap would wait for it for ever"


def test_nested_leases_of_one_name_give_back_one_each(monkeypatch):
    from src.database import corpus_lease as cl

    monkeypatch.setattr(cl, "_HELD", {})
    with cl.corpus_lease("a"):
        with cl.corpus_lease("a"):
            assert cl.active_leases() == ["a"]
        assert cl.active_leases() == ["a"]
    assert cl.active_leases() == []


def test_a_user_batch_hold_interrupted_right_after_it_was_taken_is_given_back(monkeypatch):
    from src.ai_layer import coordinator as co

    lock = _InterruptOnFirstExit()
    monkeypatch.setattr(co, "_hold_lock", lock)
    monkeypatch.setattr(co, "_hold_count", 0)
    monkeypatch.setattr(co, "_hold_reasons", {})
    with pytest.raises(KeyboardInterrupt), co.user_batch_hold("probe"):
        pytest.fail("the body must not run")
    assert lock.fired
    assert co._hold_count == 0 and not co._hold_reasons, "the coordinator would stand down for ever"


def test_two_holds_with_the_same_reason_give_back_one_each(monkeypatch):
    from src.ai_layer import coordinator as co

    monkeypatch.setattr(co, "_hold_count", 0)
    monkeypatch.setattr(co, "_hold_reasons", {})
    with co.user_batch_hold("same"):
        with co.user_batch_hold("same"):
            assert co.user_batch_active()["holders"] == ["same", "same"]
        assert co.user_batch_active()["holders"] == ["same"] and co._hold_count == 1
    assert not co.user_batch_active()["held"]


def test_an_inflight_call_interrupted_right_after_it_was_recorded_is_cleared(monkeypatch):
    from src.llm import inflight as inf

    lock = _InterruptOnFirstExit()
    monkeypatch.setattr(inf, "_LOCK", lock)
    monkeypatch.setattr(inf, "_OPEN", {})
    with pytest.raises(KeyboardInterrupt), inf.generating("m", backend="b"):
        pytest.fail("the body must not run")
    assert lock.fired
    assert not inf._OPEN, "the pill would say 'working' for ever"


def test_a_pass_interrupted_right_after_it_was_named_clears_the_name(monkeypatch):
    from src.database import verify as vf

    lock = _InterruptOnFirstExit()
    monkeypatch.setattr(vf, "_LOCK", lock)
    monkeypatch.setattr(vf, "_PASS_FILE", None)
    with pytest.raises(KeyboardInterrupt), vf._pass_in_flight("x"):  # noqa: SLF001
        pytest.fail("the body must not run")
    assert lock.fired
    assert vf._PASS_FILE is None
