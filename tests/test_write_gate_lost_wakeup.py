"""A wake-up lost in the write gate's release costs a waiting writer one step, not the rest of the process (the WAL thread, 17 Oct 2026).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE HAZARD. ``WriterGate.release`` frees the gate (the owner is cleared) and THEN wakes the head of the queue; the head is the only writer FIFO lets
take a free gate. A KeyboardInterrupt (a script's ``write_lock`` release on the main thread) or a MemoryError inside that wake-up leaves the gate
free and the head asleep on its own condition, which nobody will notify: a second ``release`` returns at the depth check, and every later writer
queues behind the head. The same wake-up is the last statement of an ``acquire`` that gave up. The wait had no timeout, so nothing but another
release could end it, and with the gate free there is no other release.

THE FIX AND WHAT IT IS NOT. A waiting writer looks again every ``_WAKE_STEP_S`` seconds (``acquire`` waits in steps). That bounds a lost wake-up; it
is not a timeout: an ``acquire`` without one still waits as long as the gate is held, and a bounded one still gives up at its own deadline, not at
a multiple of the step. The tests inject the failure into the real ``release`` with a gate built here (never the process's ``write_gate``) and shorten
the step, which the module reads at call time, so a passing run takes tenths of a second and the production second is never waited for.

RED WITHOUT. With the waits made untimed again (the test that stubs ``_wait``), the same lost wake-up leaves the writer asleep, so the first test is not
vacuous; on the module as it was before the step the first test fails.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
import threading
import time

import pytest

from src.database import writer
from src.utils import interrupts

#: How long a test waits for a thread that SHOULD get through; a passing run never waits for it.
GET_THROUGH_S = 5.0
#: The step the tests shorten the module's to, so a lost wake-up costs this much here and not the production second.
TEST_STEP_S = 0.05


class _Waiter:
    """One writer that takes the gate (untimed unless told) and releases it at once, from a thread of its own."""

    def __init__(self, gate: writer.WriterGate, timeout: float | None = None) -> None:
        self.gate = gate
        self.got = threading.Event()
        self.result: bool | None = None
        self.thread = threading.Thread(target=self._run, args=(timeout,), daemon=True)

    def _run(self, timeout: float | None) -> None:
        self.result = self.gate.acquire(timeout=timeout)
        self.got.set()
        if self.result:
            self.gate.release()

    def start_and_wait_until_queued(self) -> None:
        self.thread.start()
        deadline = time.monotonic() + GET_THROUGH_S
        while self.gate.waiters() != 1:
            assert time.monotonic() < deadline, "the writer never queued"
            time.sleep(0.005)


def _release_whose_wake_up_fails(gate: writer.WriterGate, exc: type[BaseException]) -> None:
    """The REAL ``release``, with the wake-up that follows the free raising once (the gate keeps ``_wake_head`` as a method, so it is replaced on
    the instance and put back by the caller's gate going out of scope)."""
    real = gate._wake_head
    raised = []

    def failing() -> None:
        raised.append(True)
        raise exc

    gate._wake_head = failing  # type: ignore[method-assign]
    try:
        with pytest.raises(exc):
            gate.release()
    finally:
        gate._wake_head = real  # type: ignore[method-assign]
    assert raised, "the wake-up was never reached: the test proved nothing"


@pytest.mark.parametrize("exc", [KeyboardInterrupt, MemoryError], ids=["interrupt", "memory_error"])
def test_a_wake_up_lost_in_release_costs_a_waiting_writer_one_step(monkeypatch, exc):
    monkeypatch.setattr(writer, "_WAKE_STEP_S", TEST_STEP_S)
    gate = writer.WriterGate()
    assert gate.acquire()
    waiter = _Waiter(gate)
    waiter.start_and_wait_until_queued()
    _release_whose_wake_up_fails(gate, exc)
    assert gate._owner is None, "the gate was left owned: the free comes before the wake-up"
    assert waiter.got.wait(GET_THROUGH_S), "the writer behind a free gate never got through: the lost wake-up is for ever"
    assert waiter.result is True
    waiter.thread.join(GET_THROUGH_S)
    assert gate.waiters() == 0 and gate._owner is None


def test_without_the_step_the_same_lost_wake_up_leaves_the_writer_asleep(monkeypatch):
    """The control: waits that ignore the step (what ``acquire`` did before it) never see the free gate. This is why the first test proves anything."""
    monkeypatch.setattr(writer, "_WAKE_STEP_S", TEST_STEP_S)
    monkeypatch.setattr(writer, "_wait", lambda cond, lock, timeout=None: interrupts.wait(cond, lock))
    gate = writer.WriterGate()
    assert gate.acquire()
    waiter = _Waiter(gate)
    waiter.start_and_wait_until_queued()
    _release_whose_wake_up_fails(gate, KeyboardInterrupt)
    assert gate._owner is None
    assert not waiter.got.wait(10 * TEST_STEP_S), "the writer got through without a wake-up or a step: the scenario does not lose the wake-up"
    with gate._lock:  # the wake-up that never came, so the thread ends
        gate._wake_head()
    assert waiter.got.wait(GET_THROUGH_S)
    waiter.thread.join(GET_THROUGH_S)


def test_the_step_is_not_a_timeout_a_writer_waits_as_long_as_the_gate_is_held(monkeypatch):
    monkeypatch.setattr(writer, "_WAKE_STEP_S", TEST_STEP_S)
    gate = writer.WriterGate()
    assert gate.acquire()
    waiter = _Waiter(gate)
    waiter.start_and_wait_until_queued()
    assert not waiter.got.wait(8 * TEST_STEP_S), "the writer got through while the gate was held: the step acted as a timeout"
    assert gate.waiters() == 1
    gate.release()
    assert waiter.got.wait(GET_THROUGH_S)
    assert waiter.result is True
    waiter.thread.join(GET_THROUGH_S)
    assert gate._timeouts == 0, "a step was counted as a gave-up acquire"


def test_a_bounded_acquire_still_gives_up_at_its_own_deadline_not_at_a_step(monkeypatch):
    monkeypatch.setattr(writer, "_WAKE_STEP_S", 30.0)  # far longer than the bound: only the deadline can end the wait
    gate = writer.WriterGate()
    assert gate.acquire()
    started = time.monotonic()
    result: list[bool] = []
    t = threading.Thread(target=lambda: result.append(gate.acquire(timeout=0.2)), daemon=True)
    t.start()
    t.join(GET_THROUGH_S)
    elapsed = time.monotonic() - started
    assert result == [False]
    assert 0.15 <= elapsed < 3.0, elapsed
    assert gate._timeouts == 1
    gate.release()


def test_the_step_is_one_second_and_every_wait_of_acquire_passes_it():
    """The number names what it protects (the longest a lost wake-up may cost) and is pinned here, not left to a reader. Both waits of ``acquire``
    pass a step: the untimed one the step itself, the bounded one the smaller of the step and the time left."""
    assert writer._WAKE_STEP_S == 1.0
    tree = ast.parse(textwrap.dedent(inspect.getsource(writer.WriterGate.acquire)))
    waits = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_wait"]
    assert len(waits) == 2, "acquire waits in two places (untimed and bounded)"
    for call in waits:
        assert len(call.args) == 3, ast.dump(call)
        names = {n.id for n in ast.walk(call.args[2]) if isinstance(n, ast.Name)}
        assert "_WAKE_STEP_S" in names, ast.dump(call.args[2])
