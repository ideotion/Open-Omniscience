"""An exception that lands inside a gate's own code leaves the gate usable and the exception intact.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Two ways a KeyboardInterrupt (or any exception delivered between two bytecodes) broke a gate, both found by the read of the lock work:

* THE ACQUIRE -> TRY GAP. ``if not gate.acquire(): ...`` then ``try: ... finally: release``: an exception after the gate was TAKEN and before the
  ``try`` opened left it held for ever (``write_lock``, the session events, the collector's pool slot, the library's shared lock). The tests below
  make the gate's own ``acquire`` take the gate and then raise, which is the same state seen from the caller.
* THE INTERRUPTED WAIT. ``Condition.wait`` gives the lock up and takes it back in a ``finally`` that only opens after a Python call returns; an
  interrupt in that code leaves the thread without the lock, so the ``with`` fails on exit with ``RuntimeError: cannot release un-acquired lock``
  in place of the interrupt, and the gate's own ``finally`` edits its queue and counters unlocked. (Measured on 3.13: the interrupt does NOT land
  in the lock's own re-take, which cannot be interrupted, but in the Python code around it.) ``FlakyRLock`` re-creates the two STATES a wait can
  be left in, not the place the signal lands: ``mode="lost"`` (the re-take raised and the lock is NOT owned) and ``mode="held"`` (the re-take
  happened and the exception came after; the helper must then do nothing, and a helper that re-takes anyway deadlocks).
"""

from __future__ import annotations

import threading
import time

import pytest

from src.database import writer
from src.scheduler.bandwidth import _AdjustableSemaphore


class FlakyRLock:
    """A reentrant lock whose first ``_acquire_restore`` (the re-take at the end of ``Condition.wait``) raises KeyboardInterrupt.

    ``mode="lost"``: raised WITHOUT having taken the lock. ``mode="held"``: the lock is taken back, then the exception is raised."""

    def __init__(self, mode: str = "lost") -> None:
        self._real = threading.RLock()
        self.mode = mode
        self.interrupts_left = 1
        self.raised = 0

    def acquire(self, *a, **k):
        return self._real.acquire(*a, **k)

    def release(self):
        return self._real.release()

    __enter__ = acquire

    def __exit__(self, *exc):
        return self._real.release()

    def _is_owned(self):
        return self._real._is_owned()

    def _release_save(self):
        return self._real._release_save()

    def _acquire_restore(self, state):
        if self.interrupts_left:
            self.interrupts_left -= 1
            self.raised += 1
            if self.mode == "held":
                self._real._acquire_restore(state)
            raise KeyboardInterrupt
        return self._real._acquire_restore(state)

    def free_for_another_thread(self) -> bool:
        """Can a DIFFERENT thread take the lock now? A lock left taken (a helper that re-took it twice) says no."""
        box: list[bool] = []

        def probe():
            ok = self._real.acquire(timeout=1)
            if ok:
                self._real.release()
            box.append(ok)

        t = threading.Thread(target=probe, daemon=True)
        t.start()
        t.join(5)
        return bool(box and box[0])


def _until(predicate, what: str, seconds: float = 5.0) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, f"never became true: {what}"
        time.sleep(0.005)


def _waiting_on(cond: threading.Condition) -> int:
    return len(cond._waiters)  # type: ignore[attr-defined]


def _in_thread(fn):
    """Run ``fn`` on its own thread; return ``(result_or_exception, thread)`` once it has finished (bounded)."""
    box: dict = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - the point is what comes out
            box["exc"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(5)
    assert not t.is_alive(), "the thread did not finish: a gate was left held"
    return box


def test_the_rlock_privates_the_helper_relies_on_exist():
    lock = threading.RLock()
    assert hasattr(lock, "_is_owned"), "src.utils.interrupts asks the lock whether it is owned"
    assert hasattr(lock, "_acquire_restore"), "src.utils.interrupts takes the lock back the way Condition.wait does"
    lock._acquire_restore((1, threading.get_ident()))  # the form the helper uses
    assert lock._is_owned()
    lock.release()
    assert not lock._is_owned()


MODES = pytest.mark.parametrize("mode", ["lost", "held"])


def _waiter_thread(fn):
    box: dict = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - the point is what comes out
            box["exc"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, box


def _finish(t, flaky, box):
    t.join(5)
    assert not t.is_alive(), "the waiter never finished"
    assert flaky.raised == 1
    assert isinstance(box.get("exc"), KeyboardInterrupt), f"the interrupt must come out as itself, got {box!r}"
    assert flaky.free_for_another_thread(), "the lock was left taken (a helper that re-takes a lock it already owns)"


@MODES
@pytest.mark.parametrize("timeout", [None, 3], ids=["unbounded wait", "bounded wait"])
def test_an_interrupted_wait_on_the_write_gate_stays_the_interrupt_and_leaves_the_gate_working(timeout, mode):
    gate = writer.WriterGate()
    flaky = FlakyRLock(mode)
    gate._lock = flaky
    gate._cond = threading.Condition(flaky)
    assert gate.acquire()  # the main thread holds it, so the next acquire queues and waits
    t, box = _waiter_thread(lambda: gate.acquire(timeout=timeout))
    _until(lambda: gate.waiters() == 1, "the waiter queued")
    gate.release()  # wakes the head: its wait is interrupted
    _finish(t, flaky, box)
    assert gate.waiters() == 0 and not gate._queue, "the interrupted waiter must leave the queue and the count"
    # and the gate still works, for the same thread and another
    assert gate.acquire(timeout=1)
    gate.release()
    other = _in_thread(lambda: (gate.acquire(timeout=1), gate.release()))
    assert other.get("value") == (True, None), other


@MODES
def test_an_interrupted_wait_in_the_pool_slots_stays_the_interrupt(mode):
    from src.database.pool_reserve import _Slots

    slots = _Slots(1)
    flaky = FlakyRLock(mode)
    slots._lock = flaky
    slots._cond = threading.Condition(flaky)
    assert slots.acquire(1, 1.0)
    t, box = _waiter_thread(lambda: slots.acquire(2, 3.0))
    _until(lambda: _waiting_on(slots._cond) == 1, "the waiter waits")
    slots.release(1)
    _finish(t, flaky, box)
    assert slots.held == 0 and slots.acquire(3, 1.0), "the slot table must be intact"


@MODES
def test_an_interrupted_wait_in_the_governor_stays_the_interrupt(mode):
    sem = _AdjustableSemaphore(1)
    flaky = FlakyRLock(mode)
    sem._lock = flaky
    sem._cond = threading.Condition(flaky)
    sem.acquire()
    t, box = _waiter_thread(sem.acquire)
    _until(lambda: _waiting_on(sem._cond) == 1, "the waiter waits")
    sem.release()
    _finish(t, flaky, box)
    sem.acquire()  # not stuck


@MODES
def test_an_interrupted_wait_in_the_settings_hold_stays_the_interrupt(monkeypatch, mode):
    from src.config import kv_store

    flaky = FlakyRLock(mode)
    cond = threading.Condition(flaky)
    monkeypatch.setattr(kv_store, "_hold_lock", flaky)
    monkeypatch.setattr(kv_store, "_hold", cond)
    token = object()
    with kv_store._hold_lock:
        kv_store._inflight.add(token)  # a write in flight: the hold has to wait for it

    def hold():
        with kv_store.hold_writes(3.0):
            return True

    t, box = _waiter_thread(hold)
    _until(lambda: _waiting_on(cond) == 1, "the hold waits")
    kv_store._inflight.discard(token)
    with kv_store._hold_lock:
        cond.notify_all()
    _finish(t, flaky, box)
    assert kv_store._hold_by is None, "an interrupted hold must not stay set"


@MODES
def test_an_interrupted_wait_in_the_library_lock_stays_the_interrupt(mode):
    from src.database import library_generation as lg

    lock = lg._Lock()
    flaky = FlakyRLock(mode)
    lock._lock = flaky
    lock._cond = threading.Condition(flaky)
    lock.exclusive(1.0)  # held by this thread: a shared open has to wait for it
    t, box = _waiter_thread(lock.shared)
    _until(lambda: _waiting_on(lock._cond) == 1, "the open waits")
    lock.release_exclusive()
    _finish(t, flaky, box)
    assert lock._shared == 0, "an interrupted open must not leave a shared level raised"


@MODES
def test_an_interrupted_bounded_wait_in_the_library_swap_stays_the_interrupt(mode):
    from src.database import library_generation as lg

    lock = lg._Lock()
    flaky = FlakyRLock(mode)
    lock._lock = flaky
    lock._cond = threading.Condition(flaky)
    assert lock.shared()  # an open in flight: the swap has to wait for it
    t, box = _waiter_thread(lambda: lock.exclusive(3.0))
    _until(lambda: _waiting_on(lock._cond) == 1, "the swap waits")
    lock.release_shared()
    _finish(t, flaky, box)
    assert lock._holder is None and lock._shared == 0, "an interrupted swap must not stay the holder"


def test_the_lock_is_taken_back_even_when_another_thread_took_it_in_the_gap():
    """The re-take blocks until the other holder lets go; a try-once take would skip it and the caller's ``with`` would fail on the way out."""
    from src.utils import interrupts

    class Contended(FlakyRLock):
        def _acquire_restore(self, state):
            if self.interrupts_left:
                self.interrupts_left -= 1
                self.raised += 1
                taken = threading.Event()

                def other():
                    with self._real:
                        taken.set()
                        time.sleep(0.3)

                threading.Thread(target=other, daemon=True).start()
                assert taken.wait(5)
                raise KeyboardInterrupt
            return self._real._acquire_restore(state)

    flaky = Contended("lost")
    cond = threading.Condition(flaky)

    def waiter():
        with flaky:
            interrupts.wait(cond, flaky, 3.0)

    t, box = _waiter_thread(waiter)
    notifier = threading.Thread(target=lambda: (_until(lambda: _waiting_on(cond) == 1, "waits"), flaky.acquire(), cond.notify_all(), flaky.release()))
    notifier.start()
    _finish(t, flaky, box)


# --- the back-edge of a wait loop ------------------------------------------------------------------------------------------------------


def _uncovered_back_edges(fn) -> list[int]:
    """Line numbers of ``JUMP_BACKWARD`` instructions, in ``fn`` and the functions nested in it, whose loop head an exception-table entry covers and
    whose own offset none does."""
    import dis
    import inspect
    import types

    def walk(code):
        yield code
        for const in code.co_consts:
            if isinstance(const, types.CodeType):
                yield from walk(const)

    out: list[int] = []
    for code in walk(inspect.unwrap(fn).__code__):
        ranges = [(e.start, e.end) for e in dis.Bytecode(code).exception_entries]
        for ins in dis.get_instructions(code):
            if ins.opname != "JUMP_BACKWARD" or any(start <= ins.offset < end for start, end in ranges):
                continue
            # the loop's head is protected but its back-edge is not: a loop in a function with no handler at all has nothing to skip
            if any(start <= ins.argval < end for start, end in ranges):
                out.append(ins.positions.lineno if ins.positions else -1)
    return out


def _uncovered_loop_heads(relpath: str, funcname: str) -> set[str]:
    """The source text of the first line of the head of every loop of ``funcname`` in the repo file ``relpath`` (and of the functions nested in
    it) whose ``JUMP_BACKWARD`` lies outside an exception-table entry that covers the loop's head: what :func:`_uncovered_back_edges` finds, but
    read from the file's SOURCE without importing it (a script may import a library this machine lacks), and named by text, which survives edits
    elsewhere in the file where a line number does not.

    A ``while <cond>:`` loop is reported by its first body line, since that is where CPython 3.13 puts its head. A list or dict comprehension is
    inlined into its function there, with a cleanup entry of its own, so one inside a function that has a handler is reported too: callers name
    the heads they watch and ignore the rest."""
    import dis
    import linecache
    import types
    from pathlib import Path

    path = str(Path(__file__).resolve().parents[1] / relpath)

    def walk(code):
        yield code
        for const in code.co_consts:
            if isinstance(const, types.CodeType):
                yield from walk(const)

    out: set[str] = set()
    for code in walk(compile(Path(path).read_text(encoding="utf-8"), path, "exec")):
        if code.co_name != funcname:
            continue
        ranges = [(e.start, e.end) for e in dis.Bytecode(code).exception_entries]
        instructions = list(dis.get_instructions(code))
        for ins in instructions:
            if ins.opname != "JUMP_BACKWARD" or any(start <= ins.offset < end for start, end in ranges):
                continue
            if any(start <= ins.argval < end for start, end in ranges):
                head = next(i for i in instructions if i.offset == ins.argval)
                lineno = head.positions.lineno if head.positions else None
                out.add(linecache.getline(path, lineno).strip() if lineno else "?")
    return out


def _loop_shaped_like_the_gates_used_to_be(lock, cond, held):
    with lock:
        while held():
            cond.wait()


def _loop_shaped_like_the_gates_are_now(lock, cond, held):
    with lock:
        while True:
            if not held():
                break
            cond.wait()


def test_the_probe_function_sees_the_old_loop_shape_as_uncovered_and_the_new_one_as_covered():
    """The measurement the next test rests on, pinned: if a Python covers the old shape too, the next test is vacuous and this one says so."""
    assert _uncovered_back_edges(_loop_shaped_like_the_gates_used_to_be), (
        "this Python covers the back-edge of `while cond:` inside a `with` too: re-run scripts/signal_leak_probe.py gate_pool --plain "
        "and src/utils/interrupts.py's account of the loop form before keeping the rewrite"
    )
    assert not _uncovered_back_edges(_loop_shaped_like_the_gates_are_now)


def test_no_wait_loop_leaves_its_back_edge_outside_the_with():
    """CPython 3.13 leaves the ``JUMP_BACKWARD`` of ``while cond:`` outside the exception table of a ``with`` around it, so an interrupt delivered
    there skips the lock's release: measured 0.7 % of interrupts left the pool slots' lock owned for ever. ``while True: if not cond: break`` keeps
    the jump inside (see :func:`_loop_shaped_like_the_gates_are_now`). Every gate's wait loop is written that way."""
    from src.config import kv_store
    from src.database import library_generation as lg
    from src.database import pool_reserve
    from src.scheduler.bandwidth import _AdjustableSemaphore

    gates = {
        "pool_reserve._Slots.acquire": pool_reserve._Slots.acquire,
        "bandwidth._AdjustableSemaphore.acquire": _AdjustableSemaphore.acquire,
        "library_generation._Lock.shared": lg._Lock.shared,
        "library_generation._Lock.exclusive": lg._Lock.exclusive,
        "kv_store._write_slot": kv_store._write_slot,
        "kv_store.hold_writes": kv_store.hold_writes,
        "writer.WriterGate.acquire": writer.WriterGate.acquire,
    }
    bad = {name: _uncovered_back_edges(fn) for name, fn in gates.items() if _uncovered_back_edges(fn)}
    assert not bad, f"a wait loop's back-edge is outside the with (lines): {bad}"


def test_the_other_locked_loops_of_this_lane_keep_their_back_edge_inside_the_with():
    """R162: a loop that holds a lock and can run on the main thread is written in the covered shape, or lives in a helper called from inside
    the ``with`` (a function with no handler has nothing to skip; the interrupt propagates to the caller's call, which the ``with`` covers)."""
    from src.config import kv_store
    from src.custody import pending

    owned = {"kv_store.kv_invalidate": kv_store.kv_invalidate, "custody.pending.drain": pending.drain}
    bad = {name: _uncovered_back_edges(fn) for name, fn in owned.items() if _uncovered_back_edges(fn)}
    assert not bad, f"a loop's back-edge is outside the with (lines): {bad}"


def test_the_reindex_precompute_loops_keep_their_back_edge_inside_the_finally():
    """R163: a loop reachable on the main thread through a CLI or subprocess entry counts as main-thread reachable. ``_serial`` and ``precompute_batch``
    set a watchdog's stop event in a ``finally``; their loops are functions of their own, called from inside the ``try``."""
    from src.analytics import reindex_parallel

    owned = {"reindex_parallel._serial": reindex_parallel._serial, "reindex_parallel.precompute_batch": reindex_parallel.precompute_batch}
    bad = {name: _uncovered_back_edges(fn) for name, fn in owned.items() if _uncovered_back_edges(fn)}
    assert not bad, f"a loop's back-edge is outside the try (lines): {bad}"


_WORKER_ONLY_REPORT = "/mnt/project-files/fix-source-qualification/main-thread-reachability-2026-10-17.md"


def _worker_only_loops() -> dict:
    """The locked or try/finally loops whose every caller is a worker thread, each with the reason (R162 allowlist, R163).

    A name is here ONLY because the call graph in :data:`_WORKER_ONLY_REPORT` shows no path to the main thread; a new caller that can run on the
    main thread voids the entry and the loop is converted instead (see ``_loop_shaped_like_the_gates_are_now``)."""
    from src.ai_layer import coordinator
    from src.analytics import keyword_fold, source_topics
    from src.database import article_indexes, maintenance

    why = f"worker-only: see {_WORKER_ONLY_REPORT}"
    return {
        "keyword_fold.fold_page": (keyword_fold.fold_page, why + " (thread keyword-fold-job)"),
        "source_topics._apply_source_topics_on_a_shared_session": (source_topics._apply_source_topics_on_a_shared_session, why + " (sync route, scheduler threads)"),
        "source_topics.apply_source_topics": (source_topics.apply_source_topics, why + " (sync route, scheduler threads)"),
        "article_indexes._refresh_stats": (article_indexes._refresh_stats, why + " (index-build BackgroundJob)"),
        "maintenance.maybe_incremental_vacuum": (maintenance.maybe_incremental_vacuum, why + " (oo-scheduler, oo-offline-maintenance)"),
        "coordinator.run_coordinator": (coordinator.run_coordinator, why + " (BackgroundJob ai-coordinator)"),
    }


_EVENT_LOOP_REPORT = "/mnt/project-files/rc-diagnostics/sigint-probe-2026-10-17/REPORT.md"


def _event_loop_loops() -> dict:
    """The loops that run on the event loop's thread (the lifespan's boot code, a request middleware) and nowhere else on the main thread.

    R165: they are exempt because uvicorn takes SIGINT and SIGTERM, so no KeyboardInterrupt is raised in them (measured 18 of 18 by
    :data:`_EVENT_LOOP_REPORT`). The exemption holds only while the app is served that way, which tests/test_event_loop_signal_exemption.py pins:
    every reason below names it, so removing it leaves these entries without their precondition."""
    from src.monitoring import vitals_history

    why = f"event-loop: server handles signals; see {_EVENT_LOOP_REPORT} and tests/test_event_loop_signal_exemption.py"
    return {
        "vitals_history.start": (vitals_history.start, why + " (lifespan -> record_session_start)"),
    }


def test_each_exempt_loop_names_its_reason_and_still_needs_it():
    """An entry without a reason exempts nothing, and an entry whose loop is already written in the covered shape is stale: it would go on
    exempting the function after somebody wrote the old shape back. Both fail here, so the allowlists can only shrink."""
    workers, events = _worker_only_loops(), _event_loop_loops()
    assert workers and events
    no_reason = [name for name, (_fn, reason) in workers.items() if _WORKER_ONLY_REPORT not in reason]
    no_reason += [name for name, (_fn, reason) in events.items() if _EVENT_LOOP_REPORT not in reason or "test_event_loop_signal_exemption" not in reason]
    assert not no_reason, f"exempt entries without their report (and, for the event loop, its pinning test) as the reason: {no_reason}"
    stale = [name for name, (fn, _reason) in {**workers, **events}.items() if not _uncovered_back_edges(fn)]
    assert not stale, f"these loops are already in the covered shape: delete their entries from the allowlists: {stale}"
    twice = sorted(set(workers) & set(events))
    assert not twice, f"an entry is in both allowlists: {twice}"


def test_kv_invalidate_still_forgets_exactly_the_entries_of_its_key():
    from src.config import kv_store

    table = {("a", "k1"): 1, ("b", "k1"): 2, ("a", "k2"): 3}
    kv_store._forget_key(table, "k1")
    assert table == {("a", "k2"): 3}


class _AppendThenInterrupt(list):
    """A queue whose first ``append`` stores the entry and then raises: an interrupt landing right after the thread joined the queue."""

    def __init__(self) -> None:
        super().__init__()
        self.armed = False

    def append(self, item):
        super().append(item)
        if self.armed:
            self.armed = False
            raise KeyboardInterrupt


@pytest.mark.parametrize("timeout", [None, 3], ids=["unbounded wait", "bounded wait"])
def test_a_writer_interrupted_right_after_joining_the_queue_leaves_no_entry_behind(timeout):
    """The head of the queue is the one thread FIFO lets take a free gate: an entry nobody owns would hold every later writer for ever."""
    gate = writer.WriterGate()
    assert gate.acquire()  # held by this thread
    queue = _AppendThenInterrupt()
    gate._queue = queue

    def waiter():
        queue.armed = True
        return gate.acquire(timeout=timeout)

    box = _in_thread(waiter)
    assert isinstance(box.get("exc"), KeyboardInterrupt), box
    assert not gate._queue and gate.waiters() == 0, "the interrupted writer left its entry queued or counted"
    gate.release()
    other = _in_thread(lambda: (gate.acquire(timeout=1), gate.release()))
    assert other.get("value") == (True, None), f"a later writer could not take the free gate: {other}"


# --- the acquire -> try gap ---------------------------------------------------------------------------------------------------------------


@pytest.fixture
def interrupting_acquire(monkeypatch):
    """The gate's ``acquire`` takes the window and THEN raises: the state a caller is left in by an interrupt after the take."""
    real = writer.write_gate.acquire

    def acquire_then_raise(timeout=None):
        real(timeout=timeout)
        raise KeyboardInterrupt

    monkeypatch.setattr(writer.write_gate, "acquire", acquire_then_raise)
    monkeypatch.setattr(writer, "gate_enabled", lambda: True)
    return acquire_then_raise


def test_write_lock_gives_the_window_back_when_the_acquire_raises_after_taking_it(interrupting_acquire):
    with pytest.raises(KeyboardInterrupt), writer.write_lock():
        pytest.fail("the body must not run")
    assert not writer.write_gate.held_by_current_thread(), "the window was left held"


def test_write_lock_nested_gives_back_only_its_own_level(monkeypatch):
    monkeypatch.setattr(writer, "gate_enabled", lambda: True)
    real = writer.write_gate.acquire
    with writer.write_lock():  # the outer level
        assert writer.write_gate.depth_of_current_thread() == 1

        def acquire_then_raise(timeout=None):
            real(timeout=timeout)
            raise KeyboardInterrupt

        monkeypatch.setattr(writer.write_gate, "acquire", acquire_then_raise)
        with pytest.raises(KeyboardInterrupt), writer.write_lock():
            pass
        monkeypatch.setattr(writer.write_gate, "acquire", real)
        assert writer.write_gate.depth_of_current_thread() == 1, "the outer level must still be held, exactly once"
    assert not writer.write_gate.held_by_current_thread()


def test_write_lock_nested_does_not_give_back_the_outer_level_when_the_acquire_raises_before_taking(monkeypatch):
    monkeypatch.setattr(writer, "gate_enabled", lambda: True)
    with writer.write_lock():
        real = writer.write_gate.acquire

        def raise_before_taking(timeout=None):
            raise KeyboardInterrupt

        monkeypatch.setattr(writer.write_gate, "acquire", raise_before_taking)
        with pytest.raises(KeyboardInterrupt), writer.write_lock():
            pass
        monkeypatch.setattr(writer.write_gate, "acquire", real)
        assert writer.write_gate.depth_of_current_thread() == 1, "the outer level was given back by a call that never took one"
    assert not writer.write_gate.held_by_current_thread()


def test_a_session_interrupted_just_after_it_was_marked_is_unmarked_and_holds_nothing():
    class _MarkThenRaise(dict):
        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            raise KeyboardInterrupt

    class _Session:
        pass

    session = _Session()
    session.info = _MarkThenRaise()
    with pytest.raises(KeyboardInterrupt):
        writer._take_for_session(session)
    assert not writer.write_gate.held_by_current_thread()
    assert writer._SESSION_FLAG not in session.info, "a flag with no window behind it makes a later release_if_held drop someone else's level"


def test_a_session_that_is_interrupted_after_the_window_was_taken_holds_nothing(interrupting_acquire):
    class _Session:
        pass

    session = _Session()
    session.info = {}
    with pytest.raises(KeyboardInterrupt):
        writer._take_for_session(session)
    assert not writer.write_gate.held_by_current_thread()
    assert writer._SESSION_FLAG not in session.info


def test_a_session_takes_the_window_once_and_marks_itself(monkeypatch):
    class _Session:
        pass

    session = _Session()
    session.info = {}
    try:
        writer._take_for_session(session)
        assert session.info[writer._SESSION_FLAG] is True
        assert writer.write_gate.depth_of_current_thread() == 1
    finally:
        writer.release_if_held(session)
    assert not writer.write_gate.held_by_current_thread()


def test_the_collector_slot_is_given_back_when_the_reservation_raises_after_taking_it():
    import sqlite3

    from sqlalchemy import create_engine

    from src.database.pool_reserve import ReservingQueuePool, collector_role

    engine = create_engine(
        "sqlite://",
        creator=lambda: sqlite3.connect(":memory:", check_same_thread=False),
        poolclass=ReservingQueuePool,
        pool_size=2,
        max_overflow=4,
        pool_timeout=0.3,
    )
    pool = engine.pool
    real = pool._reserve.acquire

    def take_then_raise(key, timeout):
        real(key, timeout)
        raise KeyboardInterrupt

    pool._reserve.acquire = take_then_raise
    with collector_role(), pytest.raises(KeyboardInterrupt):
        engine.connect()
    assert pool._reserve.held == 0, "the slot was leaked"


def test_write_lock_still_gives_its_level_back_when_the_body_commits_a_session_that_held_the_window(tmp_path, monkeypatch):
    """The regression the read found in the first version: the release was decided by comparing depths AFTER the body, so a body that
    ended a transaction which had taken the window earlier (its commit gives one level back) left the level write_lock took held for ever."""
    from sqlalchemy import Column, Integer, create_engine, event
    from sqlalchemy.orm import declarative_base, sessionmaker

    monkeypatch.setattr(writer, "gate_enabled", lambda: True)
    Base = declarative_base()

    class Row(Base):
        __tablename__ = "rows"
        id = Column(Integer, primary_key=True)

    engine = create_engine(f"sqlite:///{tmp_path / 'g.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, future=True)
    event.listen(maker, "before_flush", writer._on_before_flush)
    event.listen(maker, "after_transaction_end", writer._on_after_transaction_end)
    s = maker()
    try:
        s.add(Row())
        s.flush()  # the session now holds one level, with its flag set
        assert writer.write_gate.depth_of_current_thread() == 1
        with writer.write_lock():
            assert writer.write_gate.depth_of_current_thread() == 2
            s.add(Row())
            s.commit()  # ends the transaction: gives back the SESSION's level
        assert not writer.write_gate.held_by_current_thread(), "write_lock's own level was never given back"
    finally:
        s.close()
        writer.release_if_held(s)
    assert other_can_take_the_gate()


def other_can_take_the_gate() -> bool:
    box = _in_thread(lambda: (writer.write_gate.acquire(timeout=1), writer.write_gate.release()))
    return box.get("value", (False,))[0] is True


def test_a_session_taking_the_window_does_not_give_back_a_level_of_the_thread_when_the_acquire_raises_before_taking(monkeypatch):
    monkeypatch.setattr(writer, "gate_enabled", lambda: True)

    class _Session:
        pass

    outer = _Session()
    outer.info = {}
    writer._take_for_session(outer)  # this thread holds one level, through a session
    try:
        inner = _Session()
        inner.info = {}

        def raise_before_taking(timeout=None):
            raise KeyboardInterrupt

        real = writer.write_gate.acquire
        monkeypatch.setattr(writer.write_gate, "acquire", raise_before_taking)
        with pytest.raises(KeyboardInterrupt):
            writer._take_for_session(inner)
        monkeypatch.setattr(writer.write_gate, "acquire", real)
        assert writer.write_gate.depth_of_current_thread() == 1, "the thread's level was given back by a call that never took one"
        assert writer._SESSION_FLAG not in inner.info
    finally:
        writer.release_if_held(outer)
    assert not writer.write_gate.held_by_current_thread()


def test_a_session_that_already_holds_the_window_is_left_alone_by_a_second_take():
    class _Session:
        pass

    session = _Session()
    session.info = {}
    writer._take_for_session(session)
    try:
        writer._take_for_session(session)  # a caller that forgot to check the flag: nothing is taken, nothing undone
        assert writer.write_gate.depth_of_current_thread() == 1 and session.info[writer._SESSION_FLAG] is True
    finally:
        writer.release_if_held(session)
    assert not writer.write_gate.held_by_current_thread()


def test_a_library_open_interrupted_after_the_shared_level_was_raised_leaves_none_raised():
    from src.database import library_generation as lg

    lock = lg._Lock()
    real_shared = lock.shared

    def shared_then_raise():
        real_shared()
        raise KeyboardInterrupt

    lock.shared = shared_then_raise  # type: ignore[method-assign]
    old = lg._LOCK
    lg._LOCK = lock
    try:
        with pytest.raises(KeyboardInterrupt), lg.connecting():
            pytest.fail("the body must not run")
    finally:
        lg._LOCK = old
    assert lock._shared == 0 and lock.shared_held_here() == 0, "a shared level stayed raised: every later library swap would time out"


def test_a_nested_library_open_gives_back_exactly_its_own_level():
    from src.database import library_generation as lg

    with lg.connecting():
        assert lg._LOCK.shared_held_here() == 1
        with lg.connecting():
            assert lg._LOCK.shared_held_here() == 2
        assert lg._LOCK.shared_held_here() == 1
    assert lg._LOCK.shared_held_here() == 0 and lg._LOCK._shared == 0


def _swap_window_with(monkeypatch, tmp_path, lock):
    from src.database import library_generation as lg

    source = tmp_path / "library.db"
    source.write_bytes(b"x")  # still there when the window ends: the swap did not happen
    monkeypatch.setattr(lg, "_LOCK", lock)
    return lg, source


def test_a_swap_window_interrupted_right_after_the_exclusive_lock_was_set_releases_it(monkeypatch, tmp_path):
    from src.database import library_generation as lg

    lock = lg._Lock()
    real_exclusive = lock.exclusive

    def exclusive_then_raise(timeout):
        real_exclusive(timeout)
        raise KeyboardInterrupt  # the holder is set, and the caller never saw the answer

    lock.exclusive = exclusive_then_raise  # type: ignore[method-assign]
    lg, source = _swap_window_with(monkeypatch, tmp_path, lock)
    with pytest.raises(KeyboardInterrupt), lg.swap_window(source, timeout=5.0):
        pytest.fail("the body must not run")
    assert lock._holder is None, "the swap window stayed held: every later connection to the library would wait for ever"
    assert lg._WINDOW_STAMP is None


def test_a_swap_window_interrupted_before_its_try_begins_releases_the_lock(monkeypatch, tmp_path):
    """The statements between the acquire and the ``try`` are where the old form lost the lock: the first one that calls anything."""
    from src.database import library_generation as lg

    lock = lg._Lock()
    lg, source = _swap_window_with(monkeypatch, tmp_path, lock)

    class _Raises:
        def __init__(self):
            self.raised = False

        def __enter__(self):
            if not self.raised:
                self.raised = True
                raise KeyboardInterrupt
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(lg, "_STATE", _Raises())
    with pytest.raises(KeyboardInterrupt), lg.swap_window(source, timeout=5.0):
        pytest.fail("the body must not run")
    assert lock._holder is None, "the swap window stayed held: every later connection to the library would wait for ever"


def test_a_swap_window_that_could_not_be_had_leaves_a_holders_window_alone(monkeypatch, tmp_path):
    """The cleanup releases only what this call took: a window another thread holds, and its stamp, are not ours to clear."""
    from src.database import library_generation as lg

    lock = lg._Lock()
    lg, source = _swap_window_with(monkeypatch, tmp_path, lock)
    taken = threading.Event()
    done = threading.Event()

    def other_holds() -> None:
        lock.exclusive(5.0)
        lg._open_window()
        taken.set()
        done.wait(10.0)

    t = threading.Thread(target=other_holds, daemon=True)
    t.start()
    assert taken.wait(5.0)
    try:
        stamp = lg._WINDOW_STAMP
        with pytest.raises(lg.LibraryBusy), lg.swap_window(source, timeout=0.05):
            pytest.fail("the body must not run")
        assert lock._holder == t.ident and stamp == lg._WINDOW_STAMP
    finally:
        done.set()
        t.join(5.0)
        lg._close_window(swapped=True)
