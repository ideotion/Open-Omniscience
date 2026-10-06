"""The write gate keeps the holds of a thread that asked to be watched (2026-10-06).

``total_held_s`` is the whole process's, so a per-drain share cannot be read from it. A thread asks
to be watched by name, takes its own figures (and clears them), and nobody else's holds are in them.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import threading
import time

from src.database.writer import WriterGate


def _hold(gate: WriterGate, seconds: float) -> None:
    gate.acquire()
    time.sleep(seconds)
    gate.release()


def test_a_watched_thread_reads_its_own_grants_and_holds_and_they_clear():
    gate = WriterGate()
    name = threading.current_thread().name
    gate.watch(name)
    _hold(gate, 0.02)
    _hold(gate, 0.04)
    taken = gate.take_watched(name)
    assert taken is not None and taken["grants"] == 2
    assert 0.06 <= taken["held_s"] < 0.5 and 0.04 <= taken["longest_s"] <= taken["held_s"]
    again = gate.take_watched(name)
    assert again == {"grants": 0, "held_s": 0.0, "longest_s": 0.0}, "reading clears it"


def test_another_threads_holds_are_in_the_process_total_and_not_in_the_watched_figure():
    gate = WriterGate()
    gate.watch(threading.current_thread().name)
    t = threading.Thread(target=_hold, args=(gate, 0.1), name="somebody-else")
    t.start()
    t.join()
    taken = gate.take_watched(threading.current_thread().name)
    assert taken == {"grants": 0, "held_s": 0.0, "longest_s": 0.0}
    assert gate.stats()["total_held_s"] >= 0.1


def test_an_unwatched_thread_reads_none_not_zero():
    assert WriterGate().take_watched("never-asked") is None


def test_a_reentrant_hold_is_one_grant_and_one_hold():
    gate = WriterGate()
    name = threading.current_thread().name
    gate.watch(name)
    gate.acquire()
    gate.acquire()
    time.sleep(0.02)
    gate.release()
    gate.release()
    taken = gate.take_watched(name)
    assert taken is not None and taken["grants"] == 1 and taken["held_s"] < 0.3
