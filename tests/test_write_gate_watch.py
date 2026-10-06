"""The write gate keeps the holds of a thread that asked to be watched (2026-10-06).

``total_held_s`` is the whole process's, so a per-drain share cannot be read from it. A thread asks to
be watched (keyed by its ident, never its name), takes its own figures once (which stops the watch),
and nobody else's holds are in them.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import contextlib
import threading
import time

from src.database.writer import WriterGate


def _hold(gate: WriterGate, seconds: float) -> None:
    gate.acquire()
    time.sleep(seconds)
    gate.release()


def test_a_watched_thread_reads_its_own_grants_and_holds_once():
    gate = WriterGate()
    me = threading.get_ident()
    gate.watch(me)
    _hold(gate, 0.02)
    _hold(gate, 0.04)
    taken = gate.take_watched(me)
    assert taken is not None and taken["grants"] == 2
    assert 0.06 <= taken["held_s"] < 0.5 and 0.04 <= taken["longest_s"] <= taken["held_s"]
    assert gate.take_watched(me) is None, "reading stops the watch: the table does not keep dead entries"
    assert gate._watched == {}


def test_another_threads_holds_are_in_the_process_total_and_not_in_the_watched_figure():
    gate = WriterGate()
    me = threading.get_ident()
    gate.watch(me)
    t = threading.Thread(target=_hold, args=(gate, 0.1), name="somebody-else")
    t.start()
    t.join()
    taken = gate.take_watched(me)
    assert taken == {"grants": 0, "held_s": 0.0, "longest_s": 0.0}
    assert gate.stats()["total_held_s"] >= 0.1


def test_two_threads_with_one_name_keep_separate_figures():
    """A restart that lands while the old drain thread is still running gives two threads the same
    name; keyed by name they would read each other's holds."""
    gate = WriterGate()
    out: dict[str, dict | None] = {}
    watched = threading.Barrier(2)

    def work(label: str, seconds: float, grants: int) -> None:
        me = threading.get_ident()
        gate.watch(me)
        watched.wait()
        for _ in range(grants):
            _hold(gate, seconds)
        out[label] = gate.take_watched(me)

    a = threading.Thread(target=work, args=("a", 0.01, 1), name="oo-wiki-drain")
    b = threading.Thread(target=work, args=("b", 0.01, 3), name="oo-wiki-drain")
    a.start()
    b.start()
    a.join()
    b.join()
    assert out["a"] is not None and out["a"]["grants"] == 1
    assert out["b"] is not None and out["b"]["grants"] == 3


def test_an_unwatched_thread_reads_none_not_zero():
    assert WriterGate().take_watched(threading.get_ident()) is None


def test_a_reentrant_hold_is_one_grant_and_one_hold():
    gate = WriterGate()
    me = threading.get_ident()
    gate.watch(me)
    gate.acquire()
    gate.acquire()
    time.sleep(0.02)
    gate.release()
    gate.release()
    taken = gate.take_watched(me)
    assert taken is not None and taken["grants"] == 1 and taken["held_s"] < 0.3


def test_the_gate_is_free_and_the_next_waiter_woken_before_the_bookkeeping_runs():
    """The watched bookkeeping comes AFTER the owner is cleared: even if it failed the gate is free."""
    gate = WriterGate()
    me = threading.get_ident()
    gate.watch(me)
    gate.acquire()
    gate._watched[me] = None  # type: ignore[assignment]  # a corrupt entry: the bookkeeping raises
    with contextlib.suppress(TypeError):
        gate.release()
    assert gate._owner is None and gate._holder is None and gate.stats()["held"] is False
    assert gate.acquire(timeout=0.5) is True
    gate.release()
