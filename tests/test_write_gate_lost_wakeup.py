"""A wake-up lost in the write gate's release costs a waiting writer one step, not the rest of the process (the WAL thread, 17 Oct 2026).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE HAZARD. ``WriterGate.release`` frees the gate (the owner is cleared) and THEN wakes the head of the queue; the head is the only writer FIFO lets
take a free gate. A KeyboardInterrupt (a script's ``write_lock`` release on the main thread) or a MemoryError inside that wake-up leaves the gate
free and the head asleep on its own condition, which nobody will notify: a second ``release`` returns at the depth check, and every later writer
queues behind the head. The same wake-up is the last statement of an ``acquire`` that gave up (its ``finally``). The wait had no timeout, so nothing but
another release could end it, and with the gate free there is no other release. The tests force BOTH paths: the failing wake-up of ``release``, and the
failing wake-up of the ``finally`` of a head that was interrupted in its wait and gave up on a free gate.

THE FIX AND WHAT IT IS NOT. A waiting writer looks again every ``_WAKE_STEP_S`` seconds (``acquire`` waits in steps). That bounds a lost wake-up; it
is not a timeout: an ``acquire`` without one still waits as long as the gate is held, and a bounded one still gives up at its own deadline, not at
a multiple of the step. The tests inject the failure into the real ``release`` with a gate built here (never the process's ``write_gate``) and shorten
the step, which the module reads at call time, so a passing run takes tenths of a second and the production second is never waited for.

RED WITHOUT. With the waits made untimed again (the controls that stub ``_wait``), the same lost wake-up leaves the writer asleep, so the injection tests
are not vacuous. On the old ``acquire`` with ``_WAKE_STEP_S`` merely defined the injection tests fail on behaviour (the writer never gets through); on the
module literally as it was they fail earlier, at the ``monkeypatch.setattr`` of the constant that does not exist yet.
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
from tests.wallclock_helpers import HANG_GUARD_S

#: How long a test waits for a thread that SHOULD get through; a passing run never waits for it.
GET_THROUGH_S = HANG_GUARD_S
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

    def start_and_wait_until_queued(self, behind: int = 0) -> None:
        self.thread.start()
        _wait_until_queued(self.gate, behind + 1)


def _wait_until_queued(gate: writer.WriterGate, n: int) -> None:
    deadline = time.monotonic() + GET_THROUGH_S
    while gate.waiters() != n:
        assert time.monotonic() < deadline, f"{n} writers never queued"
        time.sleep(0.005)


def _release_whose_wake_up_fails(gate: writer.WriterGate, exc: type[BaseException]) -> None:
    """The REAL ``release``, with the wake-up that follows the free raising once (the gate keeps ``_wake_head`` as a method, so it is replaced on
    the instance and put back in the ``finally`` below)."""
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
def test_a_wake_up_lost_in_release_does_not_strand_a_waiting_writer(monkeypatch, exc):
    monkeypatch.setattr(writer, "_WAKE_STEP_S", TEST_STEP_S)
    gate = writer.WriterGate()
    assert gate.acquire()
    waiter = _Waiter(gate)
    waiter.start_and_wait_until_queued()
    _release_whose_wake_up_fails(gate, exc)
    assert gate._owner is None, "the gate was left owned: the free comes before the wake-up"
    # the bound is GET_THROUGH_S (100 test steps), generous for a slow CI: this proves "not for ever"; the one-step figure is the module's arithmetic
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


def _give_up_with_the_gate_free(
    monkeypatch, gate: writer.WriterGate, exc: type[BaseException], *, untimed: bool
) -> tuple[threading.Thread, list[BaseException]]:
    """Writer A (the queue head, untimed) is interrupted in its wait at the moment the gate is free, so it GIVES UP, and the wake-up its ``finally`` owes
    the next head raises as well: the other lost-wake-up path, ``acquire``'s ``finally`` and not ``release``. The module's ``_wait`` and the instance's
    ``_wake_head`` are replaced for A's thread only, so the writer behind A runs the real code. ``untimed`` makes the real waits ignore the step."""
    errors: list[BaseException] = []

    def run() -> None:
        try:
            gate.acquire()
        except BaseException as e:  # the interrupt A is given
            errors.append(e)

    a = threading.Thread(target=run, daemon=True)
    real_wait = (lambda cond, lock, timeout=None: interrupts.wait(cond, lock)) if untimed else writer._wait
    real_wake = gate._wake_head

    def wait(cond, lock, timeout=None):
        woke = real_wait(cond, lock, timeout)
        if threading.current_thread() is a and gate._owner is None:
            raise exc  # the interrupt lands in A's wait with the gate free: A gives up
        return woke

    def wake() -> None:
        if threading.current_thread() is a:
            raise exc  # and the wake-up A's finally owes the next head fails
        real_wake()

    monkeypatch.setattr(writer, "_wait", wait)
    monkeypatch.setattr(gate, "_wake_head", wake)
    return a, errors


@pytest.mark.parametrize("exc", [KeyboardInterrupt, MemoryError], ids=["interrupt", "memory_error"])
def test_a_wake_up_lost_in_the_finally_of_a_gave_up_acquire_does_not_strand_the_next_writer(monkeypatch, exc):
    monkeypatch.setattr(writer, "_WAKE_STEP_S", TEST_STEP_S)
    gate = writer.WriterGate()
    assert gate.acquire()
    a, errors = _give_up_with_the_gate_free(monkeypatch, gate, exc, untimed=False)
    a.start()
    _wait_until_queued(gate, 1)
    waiter = _Waiter(gate)
    waiter.start_and_wait_until_queued(behind=1)
    gate.release()  # the real release wakes A; A's wait raises with the gate free, and the wake-up of A's finally fails
    a.join(GET_THROUGH_S)
    assert len(errors) == 1 and isinstance(errors[0], exc), "A was not given up and then failed to wake: the test proved nothing"
    assert gate._timeouts == 1, "A's give-up was not the path under test"
    assert waiter.got.wait(GET_THROUGH_S), "the writer behind the head that gave up never got through: the lost wake-up is for ever"
    assert waiter.result is True
    waiter.thread.join(GET_THROUGH_S)
    assert gate.waiters() == 0 and gate._owner is None


def test_without_the_step_the_same_lost_wake_up_in_the_finally_leaves_the_next_writer_asleep(monkeypatch):
    """The control of the finally path: waits that ignore the step never see the free gate, so the test above proves something."""
    monkeypatch.setattr(writer, "_WAKE_STEP_S", TEST_STEP_S)
    gate = writer.WriterGate()
    assert gate.acquire()
    a, errors = _give_up_with_the_gate_free(monkeypatch, gate, KeyboardInterrupt, untimed=True)
    a.start()
    _wait_until_queued(gate, 1)
    waiter = _Waiter(gate)
    waiter.start_and_wait_until_queued(behind=1)
    gate.release()
    a.join(GET_THROUGH_S)
    assert len(errors) == 1 and gate._timeouts == 1
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
    monkeypatch.setattr(writer, "_WAKE_STEP_S", 3 * GET_THROUGH_S)  # outlasts the wait for the thread: only the deadline can end it in time
    gate = writer.WriterGate()
    assert gate.acquire()
    started = time.monotonic()
    result: list[bool] = []
    t = threading.Thread(target=lambda: result.append(gate.acquire(timeout=0.2)), daemon=True)
    t.start()
    t.join(GET_THROUGH_S)
    elapsed = time.monotonic() - started
    assert result == [False]
    assert elapsed >= 0.15, elapsed  # it waited for its deadline; coming back at the step instead would have outlasted the join above
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
