"""The write gate counts the holders' CPU over EVERY hold, beside the seconds they held it (R458, finding F1 of the 07 Nov Windows bundle).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The Windows bundle kept 20 of 10,660 long holds and each carried ``cpu_ms``: the ten longest (6 to 21 minutes) used 0.2 to 13 % of their
seconds in CPU (the holder was waiting), the ten newest (36 to 68 s) used 83 to 97 % (it was computing). Those are the extremes the journal
keeps; nothing said what the typical hold was, so nothing said which regime the gate's 0.889 busy share was in. ``total_hold_cpu_s`` in
``stats()`` is the holders' thread CPU summed over every finished hold, the same holds ``total_held_s`` sums. What must hold:

* a hold that computes adds about its CPU, and a hold that only waits adds about nothing while ``total_held_s`` grows by its seconds
  (that pair is the whole point: it separates work from waiting);
* it is the HOLDER THREAD's CPU, not the process's: another thread burning CPU while the holder sleeps adds nothing;
* a reentrant hold counts once; a release by a thread that does not own the gate counts nothing;
* a clock the OS cannot give leaves it ``None`` (absent, not a 0 that would read as "the holders did no work"), whether it fails at the
  grant or at the release, and the gate still works.
"""

from __future__ import annotations

import threading
import time

import pytest

from src.database import writer

BURN_S = 0.05
#: ``stats()`` rounds each figure to 4 places, so the DIFFERENCE of two readings can fall short of the true one by up to 1e-4 (each
#: reading loses at most 5e-5), plus the float error of subtracting two totals near 33 s. CI read 33.1771 then 33.2271 for a hold of at
#: least 0.05 s, and 33.2271 - 33.1771 is 0.0499999... in floats. A test that compares such a difference allows exactly that much.
TWO_READINGS = 1e-4 + 1e-9


def _burn(seconds: float = BURN_S) -> None:
    """Use at least ``seconds`` of THIS thread's CPU (a loop until the thread's own clock has moved, never a sleep)."""
    t0 = time.thread_time()
    while time.thread_time() - t0 < seconds:
        pass


def test_no_hold_yet_is_absent_not_zero():
    assert writer.WriterGate().stats()["total_hold_cpu_s"] is None


def test_a_hold_that_computes_adds_its_cpu_and_one_that_waits_adds_about_none():
    gate = writer.WriterGate()
    assert gate.acquire()
    _burn()
    gate.release()
    worked = gate.stats()
    assert worked["total_hold_cpu_s"] >= BURN_S, "the burn is at least this much of the holder's own CPU"
    assert worked["total_hold_cpu_s"] <= worked["total_held_s"] + 0.02, "one thread cannot use more CPU than the seconds it held"

    assert gate.acquire()
    time.sleep(0.25)
    gate.release()
    waited = gate.stats()
    assert waited["total_held_s"] - worked["total_held_s"] >= 0.25 - TWO_READINGS, "the sleep is held time"
    assert waited["total_hold_cpu_s"] - worked["total_hold_cpu_s"] < BURN_S, "and it is not CPU: waiting is told from working"
    assert waited["total_hold_cpu_s"] >= worked["total_hold_cpu_s"], "a hold adds to the total, it never replaces it"


def test_the_total_is_summed_over_every_hold():
    gate = writer.WriterGate()
    for _ in range(2):
        assert gate.acquire()
        _burn()
        gate.release()
    assert gate.stats()["total_hold_cpu_s"] >= 2 * BURN_S, "two holds that each burn BURN_S add up to at least twice it"


def test_it_is_the_holders_cpu_not_the_processs():
    gate = writer.WriterGate()
    stop = threading.Event()
    burned = threading.Event()

    def burner() -> None:  # another thread computing the whole time the holder sleeps, outside the gate
        _burn(0.2)
        burned.set()
        stop.wait(5)

    t = threading.Thread(target=burner, daemon=True)
    t.start()
    assert gate.acquire()
    assert burned.wait(10), "the other thread finished its 0.2 s of CPU inside this hold"
    gate.release()
    stop.set()
    t.join(5)
    assert gate.stats()["total_hold_cpu_s"] < BURN_S, "a thread's CPU is its own: the process's would be 0.2 s or more here"


def test_a_reentrant_hold_counts_once():
    gate = writer.WriterGate()
    assert gate.acquire()
    assert gate.acquire()  # the nested write of a second session on the same thread
    _burn()
    gate.release()
    assert gate.stats()["total_hold_cpu_s"] is None, "the nested release ends no hold"
    gate.release()
    total = gate.stats()["total_hold_cpu_s"]
    assert BURN_S <= total < 2 * BURN_S, "once, not once per level"


def test_a_release_by_a_thread_that_does_not_own_the_gate_counts_nothing():
    gate = writer.WriterGate()
    holder_in = threading.Event()
    let_go = threading.Event()

    def hold() -> None:
        assert gate.acquire()
        holder_in.set()
        let_go.wait(10)
        gate.release()

    t = threading.Thread(target=hold, daemon=True)
    t.start()
    assert holder_in.wait(10)
    _burn()
    gate.release()  # not the owner: a no-op
    assert gate.stats()["total_hold_cpu_s"] is None
    let_go.set()
    t.join(5)
    assert gate.stats()["total_hold_cpu_s"] is not None, "the real holder's own release is counted"


def test_the_public_window_adds_to_the_process_gate(monkeypatch):
    monkeypatch.delenv("OO_WRITE_GATE", raising=False)  # with the gate switched off the window is a no-op
    before = writer.write_gate.stats()["total_hold_cpu_s"] or 0.0
    with writer.write_lock():
        _burn()
    assert (writer.write_gate.stats()["total_hold_cpu_s"] or 0.0) - before >= BURN_S - TWO_READINGS


@pytest.mark.parametrize("fails_at", ["grant", "release", "grant_only"])
def test_a_clock_the_os_cannot_give_leaves_it_absent_and_the_gate_working(monkeypatch, fails_at):
    gate = writer.WriterGate()

    def no_clock() -> float:
        raise OSError("no per-thread clock here")

    real = time.thread_time
    if fails_at in ("grant", "grant_only"):
        monkeypatch.setattr(time, "thread_time", no_clock)
    assert gate.acquire()
    if fails_at == "release":
        monkeypatch.setattr(time, "thread_time", no_clock)
    if fails_at == "grant_only":
        monkeypatch.setattr(time, "thread_time", real)  # the clock is back at the release, but the grant has no reading to subtract it from
    gate.release()
    stats = gate.stats()
    assert stats["total_hold_cpu_s"] is None, "absent, not 0"
    assert stats["grants"] == 1 and stats["total_held_s"] >= 0.0 and not stats["held"], "the hold itself was counted and the gate is free"
    assert gate.acquire(timeout=1.0), "and it can be taken again"
    gate.release()


def test_a_clock_that_runs_backwards_adds_nothing_rather_than_a_negative(monkeypatch):
    gate = writer.WriterGate()
    readings = iter([5.0, 4.0])  # the grant reads 5.0, the release 4.0
    # the clock is process-wide: another live thread's sampler may read it between the grant and the release, so the fake keeps answering 4.0
    monkeypatch.setattr(time, "thread_time", lambda: next(readings, 4.0))
    assert gate.acquire()
    gate.release()
    assert gate.stats()["total_hold_cpu_s"] == 0.0, "a measured hold that used no CPU is 0, and never below it"
