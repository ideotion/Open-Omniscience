"""The extraction lock's live gauge: what is held and waited on RIGHT NOW, readable while a hold is still open.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``src/ingest/lock_stats.py`` counts a hold when it ENDS, so a pass that never ends (a crash, a hang) leaves nothing and
a hold still open (the 85 s page that makes every other extraction wait) is invisible. The live gauge keeps two
cumulative totals, seconds held and thread-seconds waited, and ``live_reading()`` adds the part of a hold or a wait
that is still open. The difference between two readings is exact for the interval between them.

What each group of tests guards, and what fails without it:

* the readings themselves (an open hold counts, an open wait counts, nesting is one hold, an idle gauge reads zero);
* the exactness claim, against an independent log built from the clock values the gauge itself used, under eight
  threads and a sampler (the totals double counted, a wait dropped, a hold closed twice, a reading that sees more
  held time than elapsed);
* the cleanup (an exception, a ``BaseException`` and an interrupted acquire each leave no phantom holder or waiter;
  a skipped or failed ``holding`` leaves no waiter that outlives the call, the totals never go backwards, and a holder
  whose release was skipped is closed by the next take from ANOTHER thread; the same thread's next take deepens it
  instead, which is a documented edge and pinned as one);
* a step that raises changes nothing (every new total is computed before any is stored), so a ``MemoryError`` at the
  float arithmetic cannot make an open hold or an open wait vanish from a reading;
* the window and the gauge stay apart (a pass ``reset()`` does not touch the gauge);
* the marks sit where they say (``asking`` outside the lock and INSIDE the outer ``try``, ``holding`` and ``released``
  inside the hold, the clock read under the gauge's own lock) and do nothing but arithmetic: the step bodies have no
  call, no backward jump and no ``with`` (checked on the bytecode, since CPython 3.13 looks for an interrupt at each of
  those), which is what makes one mark apply whole or not at all when an interrupt arrives;
* a broken gauge never breaks an extraction.
"""

from __future__ import annotations

import ast
import dis
import inspect
import textwrap
import threading
import time

import pytest

import src.ingest.extract as extract_mod
from src.ingest import lock_stats
from src.ingest.extract import extract_article
from tests.wallclock_helpers import wait_until

_WAIT = 10.0
_PAGE = "<p>" + "x" * 40 + "</p>"


class _Clock:
    """A clock the test moves by hand."""

    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture(autouse=True)
def _fresh_gauge(monkeypatch):
    """Every test starts with an idle gauge and leaves the process-wide one as it found it."""
    monkeypatch.setattr(lock_stats, "_waiters", {})
    monkeypatch.setattr(
        lock_stats, "_live", {"depth": 0, "since": None, "holder": None, "occupied_s": 0.0, "waited_s": 0.0}
    )
    lock_stats.reset()
    yield
    lock_stats.reset()


@pytest.fixture
def clock(monkeypatch):
    fake = _Clock()
    monkeypatch.setattr(lock_stats, "now", fake)
    return fake


def _doc() -> extract_mod.ExtractedDoc:
    return extract_mod.ExtractedDoc("t", "x" * 300, None, None, None, None)


def _until(predicate, what: str) -> None:
    deadline = time.monotonic() + _WAIT
    while not predicate():
        assert time.monotonic() < deadline, f"never became true: {what}"
        time.sleep(0.001)


def _idle() -> bool:
    r = lock_stats.live_reading()
    return r["holder_age_s"] is None and r["waiting"] == 0 and lock_stats._live["depth"] == 0


# --------------------------------------------------------------------------
# the readings
# --------------------------------------------------------------------------
def test_an_idle_gauge_reads_zero_and_no_holder(clock):
    first = lock_stats.live_reading()
    clock.t += 7.0
    second = lock_stats.live_reading()
    assert first == {"now": 100.0, "occupied_s": 0.0, "waited_s": 0.0, "holder_age_s": None, "waiting": 0}
    assert second["occupied_s"] == 0.0 and second["waited_s"] == 0.0 and second["holder_age_s"] is None
    assert second["now"] - first["now"] == 7.0


def test_a_hold_still_open_counts_and_has_an_age(clock, monkeypatch):
    seen: list[dict] = []

    def body(html, *, url=None):
        clock.t += 4.0
        seen.append(lock_stats.live_reading())  # the hold is open: nothing has "ended" yet
        clock.t += 2.5
        seen.append(lock_stats.live_reading())
        return _doc()

    monkeypatch.setattr(extract_mod, "_extract_locked", body)
    extract_article(_PAGE)
    assert [r["holder_age_s"] for r in seen] == [4.0, 6.5]
    assert [r["occupied_s"] for r in seen] == [4.0, 6.5], "an open hold is in the total before it ends"
    after = lock_stats.live_reading()
    assert after["occupied_s"] == 6.5 and after["holder_age_s"] is None and after["waiting"] == 0
    clock.t += 50.0
    assert lock_stats.live_reading()["occupied_s"] == 6.5, "a free lock adds nothing"


def test_a_wait_still_open_counts_before_the_lock_is_got(clock, monkeypatch):
    holding = threading.Event()
    release = threading.Event()

    def body(html, *, url=None):
        if threading.current_thread().name == "holder":
            holding.set()
            assert release.wait(_WAIT)
        return _doc()

    monkeypatch.setattr(extract_mod, "_extract_locked", body)
    holder = threading.Thread(target=extract_article, args=(_PAGE,), name="holder", daemon=True)
    holder.start()
    assert holding.wait(_WAIT)
    waiters = [threading.Thread(target=extract_article, args=(_PAGE,), name=f"w{i}", daemon=True) for i in range(2)]
    for w in waiters:
        w.start()
    _until(lambda: lock_stats.live_reading()["waiting"] == 2, "both waiters registered")
    base = lock_stats.live_reading()
    clock.t += 3.0
    mid = lock_stats.live_reading()
    assert mid["waiting"] == 2
    assert mid["waited_s"] - base["waited_s"] == 6.0, "two threads waiting for 3 s are 6 thread-seconds"
    assert mid["occupied_s"] - base["occupied_s"] == 3.0 and mid["holder_age_s"] == base["holder_age_s"] + 3.0
    release.set()
    holder.join(_WAIT)
    for w in waiters:
        w.join(_WAIT)
    assert not holder.is_alive() and not any(w.is_alive() for w in waiters)
    end = lock_stats.live_reading()
    assert end["waiting"] == 0 and end["holder_age_s"] is None
    assert end["waited_s"] == mid["waited_s"], "the waits ended at the same instant the clock stood at: nothing more accrues"


def test_a_nested_extraction_deepens_the_hold_and_does_not_restart_or_double_count_it(clock, monkeypatch):
    seen: list[dict] = []

    def body(html, *, url=None):
        if html == _PAGE:
            clock.t += 2.0
            extract_article("<p>inner</p>")  # the RLock lets the same thread in again
            clock.t += 1.0
            seen.append(lock_stats.live_reading())
        else:
            clock.t += 5.0
            seen.append(lock_stats.live_reading())
        return _doc()

    monkeypatch.setattr(extract_mod, "_extract_locked", body)
    extract_article(_PAGE)
    inner, outer = seen
    assert inner["holder_age_s"] == 7.0 and inner["occupied_s"] == 7.0, "the age counts from the OUTERMOST take"
    assert outer["holder_age_s"] == 8.0 and outer["occupied_s"] == 8.0, "still held once the inner call has left"
    assert lock_stats._live["depth"] == 0
    end = lock_stats.live_reading()
    assert end["occupied_s"] == 8.0 and end["holder_age_s"] is None and end["waited_s"] == 0.0


# --------------------------------------------------------------------------
# the totals are exact, whatever else happened in the interval
# --------------------------------------------------------------------------
def test_differences_of_readings_match_an_independent_log_under_eight_threads_and_a_sampler(monkeypatch):
    """The log is built from the clock values the gauge ITSELF read, labelled by the mark that read them (the tape wraps
    ``_mark`` and keeps the value it returns), so what is checked is the accounting and not the clock or the order of the
    statements: the union of holds and the sum of waits inside any window, open ones included, to float rounding."""
    reads: dict[str, list[tuple[str, float]]] = {}  # by thread NAME: an ident is reused once its thread has ended
    real_mark = lock_stats._mark

    def tape(step):
        t = real_mark(step)
        reads.setdefault(threading.current_thread().name, []).append((step.__name__, t))
        return t

    monkeypatch.setattr(lock_stats, "_mark", tape)

    def body(html, *, url=None):
        time.sleep(0.0005)
        return _doc()

    monkeypatch.setattr(extract_mod, "_extract_locked", body)
    samples: list[dict] = []
    stop = threading.Event()

    def sample() -> None:
        while not stop.is_set():
            samples.append(lock_stats.live_reading())
            time.sleep(0.0007)

    def work() -> None:
        for _ in range(25):
            extract_article(_PAGE)

    sampler = threading.Thread(target=sample, name="sampler", daemon=True)
    workers = [threading.Thread(target=work, name=f"hammer-{i}", daemon=True) for i in range(8)]
    sampler.start()
    for w in workers:
        w.start()
    for w in workers:
        w.join(_WAIT * 3)
    wait_until(lambda: len(samples) > 20)  # the sampler has taken enough readings: waited for, not a count the hammers' running time allowed
    stop.set()
    sampler.join(_WAIT)
    samples.append(lock_stats.live_reading())
    assert not any(w.is_alive() for w in workers) and len(samples) > 20

    holds: list[tuple[float, float]] = []
    waits: list[tuple[float, float]] = []
    for n in range(8):
        marks = reads[f"hammer-{n}"]
        assert [m[0] for m in marks] == ["_on_ask", "_on_hold", "_on_release", "_on_give_up"] * 25, "four marks per extraction"
        for i in range(0, len(marks), 4):
            (_, ask), (_, hold), (_, release), (_, _closing) = marks[i : i + 4]
            waits.append((ask, hold))
            holds.append((hold, release))
    assert len(holds) == 8 * 25
    ordered = sorted(holds)
    assert all(a[1] <= b[0] + 1e-9 for a, b in zip(ordered, ordered[1:], strict=False)), "holds never overlap: one lock"

    def overlap(span: tuple[float, float], lo: float, hi: float) -> float:
        return max(0.0, min(span[1], hi) - max(span[0], lo))

    worst_held = worst_waited = 0.0
    for i in range(0, len(samples) - 1, 3):
        for j in range(i + 1, min(len(samples), i + 30), 4):
            lo, hi = samples[i]["now"], samples[j]["now"]
            truth_held = sum(overlap(h, lo, hi) for h in holds)
            truth_waited = sum(overlap(w, lo, hi) for w in waits)
            worst_held = max(worst_held, abs((samples[j]["occupied_s"] - samples[i]["occupied_s"]) - truth_held))
            worst_waited = max(worst_waited, abs((samples[j]["waited_s"] - samples[i]["waited_s"]) - truth_waited))
    assert worst_held < 1e-6 and worst_waited < 1e-6, (worst_held, worst_waited)
    for a, b in zip(samples, samples[1:], strict=False):
        assert b["occupied_s"] >= a["occupied_s"] and b["waited_s"] >= a["waited_s"], "the totals only grow"
        assert b["occupied_s"] - a["occupied_s"] <= (b["now"] - a["now"]) + 1e-6, "more held time than elapsed"


# --------------------------------------------------------------------------
# cleanup: nothing is left holding or waiting
# --------------------------------------------------------------------------
class _Interrupt(BaseException):
    """Stands for a KeyboardInterrupt / SystemExit: not an ``Exception``."""


@pytest.mark.parametrize("error", [RuntimeError("boom"), _Interrupt()], ids=["exception", "base_exception"])
def test_a_raising_extraction_leaves_no_holder_and_no_waiter(clock, monkeypatch, error):
    def body(html, *, url=None):
        clock.t += 2.0
        raise error

    monkeypatch.setattr(extract_mod, "_extract_locked", body)
    with pytest.raises(type(error)):
        extract_article(_PAGE)
    assert _idle()
    assert lock_stats.live_reading()["occupied_s"] == 2.0, "the hold that raised still counts"


def test_an_acquire_that_is_interrupted_leaves_no_waiter_and_keeps_the_time_it_waited(clock, monkeypatch):
    class _InterruptedLock:
        def __enter__(self):
            clock.t += 3.0
            raise _Interrupt()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(extract_mod, "_LXML_LOCK", _InterruptedLock())
    with pytest.raises(_Interrupt):
        extract_article(_PAGE)
    assert _idle()
    end = lock_stats.live_reading()
    assert end["waited_s"] == 3.0 and end["occupied_s"] == 0.0, "it waited three seconds and never held"


def test_a_release_with_no_matching_hold_is_clamped_not_negative(clock):
    lock_stats.released()
    lock_stats.released()
    assert lock_stats._live["depth"] == 0
    lock_stats.holding()
    clock.t += 1.5
    lock_stats.released()
    assert lock_stats.live_reading()["occupied_s"] == 1.5
    lock_stats.gave_up()  # a thread that is not waiting is left alone
    assert _idle()


# --------------------------------------------------------------------------
# the window and the gauge are two things
# --------------------------------------------------------------------------
def test_a_pass_reset_does_not_touch_the_gauge_and_a_hold_open_across_it_continues(clock, monkeypatch):
    seen: list[dict] = []

    def body(html, *, url=None):
        clock.t += 4.0
        lock_stats.reset()  # the next pass opens its window in the middle of this hold
        clock.t += 1.0
        seen.append(lock_stats.live_reading())
        return _doc()

    monkeypatch.setattr(extract_mod, "_extract_locked", body)
    extract_article(_PAGE)
    assert seen[0]["holder_age_s"] == 5.0 and seen[0]["occupied_s"] == 5.0
    lock_stats.reset()
    assert lock_stats.live_reading()["occupied_s"] == 5.0, "the cumulative totals survive a window reset"


# --------------------------------------------------------------------------
# where the marks sit
# --------------------------------------------------------------------------
def _owned() -> bool:
    return getattr(extract_mod._LXML_LOCK, "_is_owned")()  # noqa: B009 - the RLock type does not declare it


def test_the_marks_run_on_the_right_side_of_the_lock(clock, monkeypatch):
    seen: list[tuple[str, bool]] = []
    for name in ("asking", "holding", "released", "gave_up"):
        real = getattr(lock_stats, name)

        def spy(real=real, name=name):
            seen.append((name, _owned()))
            return real()  # released() returns the clock reading the hold ended at

        monkeypatch.setattr(lock_stats, name, spy)
    monkeypatch.setattr(extract_mod, "_extract_locked", lambda html, *, url=None: _doc())
    extract_article(_PAGE)
    assert seen == [("asking", False), ("holding", True), ("released", True), ("gave_up", False)]


def test_a_gave_up_runs_when_the_lock_was_never_taken(clock, monkeypatch):
    names: list[str] = []
    real = lock_stats.gave_up
    monkeypatch.setattr(lock_stats, "gave_up", lambda: (names.append("gave_up"), real())[1])

    class _Refused:
        def __enter__(self):
            raise _Interrupt()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(extract_mod, "_LXML_LOCK", _Refused())
    with pytest.raises(_Interrupt):
        extract_article(_PAGE)
    assert names == ["gave_up"]


def test_the_clock_is_read_under_the_gauges_own_lock(monkeypatch):
    """A mark and a reading are totally ordered only if both read the clock inside the critical section."""
    held_when_read: list[bool] = []

    def spy() -> float:
        held_when_read.append(lock_stats._LIVE_LOCK.locked())
        return 5.0

    monkeypatch.setattr(lock_stats, "now", spy)
    lock_stats.asking()
    lock_stats.holding()
    lock_stats.released()
    lock_stats.live_reading()
    lock_stats.gave_up()
    assert held_when_read == [True] * 5


def _calls(func) -> set[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            names.add(f.id if isinstance(f, ast.Name) else ast.unparse(f))
    return names


def test_the_marks_inside_the_hold_call_nothing_but_the_clock_and_the_step_bodies_call_nothing_at_all():
    """CPython 3.13 checks for a pending interrupt at a call's return and at the start of a Python frame, so a step body
    with no call in it is applied whole or not at all; the marks inside the hold also may not block, take another lock or
    do I/O. What each calls is pinned by name."""
    assert _calls(lock_stats._mark) == {"step", "now", "threading.get_ident"}
    assert _calls(lock_stats.released) == {"_mark", "now"}
    for step in (lock_stats._on_ask, lock_stats._on_give_up, lock_stats._on_hold, lock_stats._on_release):
        assert _calls(step) == set(), f"{step.__name__} has a call in it: a window for an interrupt between two of its stores"


_STEPS = (lock_stats._on_ask, lock_stats._on_give_up, lock_stats._on_hold, lock_stats._on_release)
_INTERRUPT_OPS = {"FOR_ITER", "GET_ITER", "BEFORE_WITH", "BEFORE_ASYNC_WITH", "MAKE_FUNCTION", "SEND", "YIELD_VALUE"}


def _interrupt_points(func) -> list[str]:
    """The instructions after which CPython 3.13 looks for a pending interrupt, other than the frame's own entry: a call's
    return (``CALL*``, and the implicit calls of ``with``, ``for`` and generators) and a backward jump."""
    return [
        i.opname
        for i in dis.get_instructions(func)
        if i.opname.startswith(("CALL", "JUMP_BACKWARD")) or i.opname in _INTERRUPT_OPS
    ]


def test_the_interrupt_point_finder_sees_a_call_a_loop_a_with_and_a_comprehension():
    """The pin below is only as good as its finder: each shape that gives an interrupt a place to land must be found."""

    def with_call(x):
        return len(x)

    def with_while(x):
        while x:
            x = x[1:]

    def with_for(x):
        for _ in x:
            pass

    def with_with(x):
        with x:
            pass

    def with_generator(x):
        return sum(i for i in x)

    for f in (with_call, with_while, with_for, with_with, with_generator):
        assert _interrupt_points(f), f"{f.__name__} gives an interrupt a place to land and the finder does not see it"
    assert _interrupt_points(lambda a, b: a - b if a > b else b) == []


def test_a_step_body_has_no_interrupt_point_of_its_own_on_the_bytecode():
    """``ast.Call`` is not the property: a ``while`` or a ``for`` has no call and CPython 3.13 still checks for an interrupt at
    its backward jump (a loop around one store survived the source-level pin). The finding was reproduced: a
    ``KeyboardInterrupt`` does land inside a loop with no call."""
    for step in _STEPS:
        assert _interrupt_points(step) == [], f"{step.__name__}: an interrupt can land between two of its stores"


# --------------------------------------------------------------------------
# a broken gauge never breaks an extraction
# --------------------------------------------------------------------------
class _BrokenLock:
    def __enter__(self):
        raise RuntimeError("the gauge's lock is broken")

    def __exit__(self, *exc):
        return False


def test_a_broken_gauge_never_breaks_an_extraction_and_says_so_when_read(clock, monkeypatch):
    monkeypatch.setattr(extract_mod, "_extract_locked", lambda html, *, url=None: _doc())
    with monkeypatch.context() as scoped:
        scoped.setattr(lock_stats, "_LIVE_LOCK", _BrokenLock())
        assert extract_article(_PAGE) is not None
        assert extract_article(_PAGE) is not None
        with pytest.raises(RuntimeError):
            lock_stats.live_reading()  # the caller writes the class of the failure, never a zero
    assert _idle(), "the failed marks changed nothing"
    assert lock_stats.snapshot()["holds"] == 2, "the pass window is a separate statistic and still counted both"


# --------------------------------------------------------------------------
# a skipped or failed mark: nothing outlives the call, and the totals never go backwards
# --------------------------------------------------------------------------
def test_a_skipped_holding_mark_leaves_no_waiter_after_the_call(clock, monkeypatch):
    """The review's finding: ``holding`` fails before it closes the wait, ``released`` runs (clamped), and ``record`` used to
    return without ``gave_up`` because the lock WAS taken, so the waiter stayed registered for the life of the process."""

    def interrupted() -> None:
        clock.t += 1.0
        raise _Interrupt()

    monkeypatch.setattr(lock_stats, "holding", interrupted)
    monkeypatch.setattr(extract_mod, "_extract_locked", lambda html, *, url=None: _doc())
    with pytest.raises(_Interrupt):
        extract_article(_PAGE)
    assert _idle(), "the waiter outlived the call"
    before = lock_stats.live_reading()["waited_s"]
    clock.t += 30.0
    assert lock_stats.live_reading()["waited_s"] == before, "a waiter left behind keeps accruing wait for ever"


def test_a_holding_mark_that_fails_quietly_also_leaves_no_waiter(clock, monkeypatch):
    def broken(t, ident):
        raise RuntimeError("the step failed")

    monkeypatch.setattr(lock_stats, "_on_hold", broken)
    monkeypatch.setattr(extract_mod, "_extract_locked", lambda html, *, url=None: _doc())
    assert extract_article(_PAGE) is not None, "a statistic never replaces an extraction's result"
    assert _idle()


def test_mark_swallows_exception_but_not_base_exception(clock, monkeypatch):
    monkeypatch.setattr(lock_stats, "_on_ask", lambda t, ident: (_ for _ in ()).throw(_Interrupt()))
    with pytest.raises(_Interrupt):
        lock_stats.asking()  # an interrupt in the main thread must still reach its handler
    monkeypatch.setattr(lock_stats, "_on_ask", lambda t, ident: (_ for _ in ()).throw(RuntimeError("x")))
    lock_stats.asking()  # an Exception is the statistic's own failure: swallowed


def test_asking_is_inside_the_outer_try_so_an_interrupt_after_it_still_closes_the_wait(clock, monkeypatch):
    """R171: the mark that takes shared state (a registered waiter) sits INSIDE the ``try`` whose ``finally`` gives it back."""
    real = lock_stats.asking

    def registers_then_is_interrupted() -> None:
        real()
        raise _Interrupt()

    monkeypatch.setattr(lock_stats, "asking", registers_then_is_interrupted)
    monkeypatch.setattr(extract_mod, "_extract_locked", lambda html, *, url=None: _doc())
    with pytest.raises(_Interrupt):
        extract_article(_PAGE)
    assert _idle(), "asking() ran before the try: the waiter it registered has no finally to close it"


def test_a_stale_waiter_is_closed_by_the_threads_next_ask_and_the_total_never_goes_backwards(clock):
    lock_stats._waiters[threading.get_ident()] = 90.0  # a wait whose closing mark was skipped
    before = lock_stats.live_reading()
    assert before["waited_s"] == 10.0 and before["waiting"] == 1
    lock_stats.asking()
    after = lock_stats.live_reading()
    assert after["waited_s"] == 10.0 and after["waiting"] == 1, "closed at the new ask: continuous, never backwards"
    clock.t += 2.0
    assert lock_stats.live_reading()["waited_s"] == 12.0


def test_a_holder_whose_release_was_skipped_is_closed_by_the_next_take_from_another_thread(clock):
    lock_stats.holding()  # this thread takes the lock at 100 and its release mark is skipped
    clock.t += 5.0
    phantom = lock_stats.live_reading()
    assert phantom["occupied_s"] == 5.0 and phantom["holder_age_s"] == 5.0
    done: list[dict] = []

    def other() -> None:
        lock_stats.holding()  # the real lock cannot be held by two threads: the earlier hold is over
        done.append(lock_stats.live_reading())
        clock.t += 2.0
        lock_stats.released()

    t = threading.Thread(target=other, name="other")
    t.start()
    t.join(_WAIT)
    assert done[0]["occupied_s"] == 5.0 and done[0]["holder_age_s"] == 0.0, "continuous at the take: never backwards"
    end = lock_stats.live_reading()
    assert end["occupied_s"] == 7.0 and end["holder_age_s"] is None
    assert lock_stats._live["depth"] == 0 and lock_stats._live["holder"] is None and lock_stats._live["since"] is None


def test_released_returns_the_clock_the_hold_ended_at_and_the_window_and_gauge_end_a_hold_together(clock, monkeypatch):
    def body(html, *, url=None):
        clock.t += 2.0
        return _doc()

    monkeypatch.setattr(extract_mod, "_extract_locked", body)
    extract_article(_PAGE)
    assert lock_stats.snapshot()["hold_total_s"] == 2.0
    assert lock_stats.live_reading()["occupied_s"] == 2.0
    lock_stats.holding()
    clock.t += 1.0
    assert lock_stats.released() == clock.t, "the reading the hold ended at"
    assert lock_stats._live["since"] is None and lock_stats._live["depth"] == 0


def test_the_marks_sit_where_the_exception_table_needs_them():
    """R171 by structure: ``asking`` is the first statement of the ``try`` whose ``finally`` calls ``record`` (a wait it
    registers always has a ``finally`` to close it), ``holding`` is the first statement of the ``try`` INSIDE the lock (a hold it
    opens always has a ``finally`` to close it), and ``released`` is the first statement of that ``finally``, assigned to the
    stamp ``record`` takes (one call, so no interrupt can land between the stamp and the close)."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(extract_article)))
    func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))

    def call_name(stmt: ast.stmt) -> str:
        value = stmt.value if isinstance(stmt, (ast.Expr, ast.Assign)) else None
        return ast.unparse(value.func) if isinstance(value, ast.Call) else ""

    outer = next(n for n in func.body if isinstance(n, ast.Try))
    assert [call_name(s) for s in outer.finalbody] == ["lock_stats.record"]
    assert call_name(outer.body[0]) == "lock_stats.asking", "asking() must be the first statement INSIDE the outer try"
    with_lock = outer.body[1]
    assert isinstance(with_lock, ast.With) and ast.unparse(with_lock.items[0].context_expr) == "_LXML_LOCK"
    inner = next(n for n in with_lock.body if isinstance(n, ast.Try))
    assert call_name(inner.body[0]) == "lock_stats.holding", "holding() must be the first statement INSIDE the inner try"
    first_final = inner.finalbody[0]
    assert isinstance(first_final, ast.Assign) and call_name(first_final) == "lock_stats.released"
    assert [ast.unparse(t) for t in first_final.targets] == ["released"], "the stamp record() takes is released()'s own reading"


# --------------------------------------------------------------------------
# a step that fails changes nothing
# --------------------------------------------------------------------------
class _Boom(float):
    """A clock reading whose subtraction fails the way a float allocation can (``MemoryError`` is an ``Exception``)."""

    armed = False

    def __sub__(self, other):
        if _Boom.armed:
            raise MemoryError("no room for a float")
        return float.__sub__(self, other)


class _fails:
    """``with _fails():`` every subtraction on a ``_Boom`` reading raises."""

    def __enter__(self):
        _Boom.armed = True

    def __exit__(self, *exc):
        _Boom.armed = False
        return False


def test_a_release_whose_arithmetic_fails_leaves_the_hold_open_and_the_total_where_it_was(clock):
    """The review's finding: ``_on_release`` cleared ``since`` and ``holder`` before the addition, so a failure there made
    an open 85 s hold vanish (occupied 85 -> 0, no holder) while ``_mark`` swallowed the error."""
    me = threading.get_ident()
    lock_stats.holding()
    clock.t = _Boom(185.0)
    with _fails():
        lock_stats.released()
    live = lock_stats._live
    assert (live["depth"], live["since"], live["holder"], live["occupied_s"]) == (1, 100.0, me, 0.0)
    reading = lock_stats.live_reading()
    assert reading["occupied_s"] == 85.0 and reading["holder_age_s"] == 85.0
    lock_stats.released()  # the retry closes it with its full length
    assert lock_stats._live["occupied_s"] == 85.0 and lock_stats._live["since"] is None and _idle()


def test_a_give_up_whose_arithmetic_fails_keeps_the_wait_open_and_the_total_where_it_was(clock):
    lock_stats.asking()
    clock.t = _Boom(105.0)
    with _fails():
        lock_stats.gave_up()
    assert lock_stats._live["waited_s"] == 0.0 and len(lock_stats._waiters) == 1, "the open wait vanished"
    assert lock_stats.live_reading()["waited_s"] == 5.0
    lock_stats.gave_up()
    assert lock_stats._live["waited_s"] == 5.0 and not lock_stats._waiters


def test_a_hold_whose_arithmetic_fails_closes_neither_the_wait_nor_a_phantom_and_opens_nothing(clock):
    me = threading.get_ident()
    lock_stats.asking()
    clock.t = _Boom(104.0)
    with _fails():
        lock_stats.holding()
    live = lock_stats._live
    assert (live["depth"], live["waited_s"], len(lock_stats._waiters)) == (0, 0.0, 1), "half a hold was applied"
    lock_stats.holding()
    assert (live["depth"], live["waited_s"], live["holder"], len(lock_stats._waiters)) == (1, 4.0, me, 0)
    # and the same for the phantom another thread left behind
    lock_stats._live.update(depth=1, since=100.0, holder=-1, occupied_s=0.0)
    lock_stats._waiters.clear()
    clock.t = _Boom(110.0)
    with _fails():
        lock_stats.holding()
    assert (live["depth"], live["holder"], live["since"], live["occupied_s"]) == (1, -1, 100.0, 0.0)
    lock_stats.holding()
    assert (live["depth"], live["holder"], live["since"], live["occupied_s"]) == (1, me, 110.0, 10.0)


def test_an_ask_whose_arithmetic_fails_keeps_the_stale_wait_and_registers_nothing_new(clock):
    me = threading.get_ident()
    lock_stats._waiters[me] = 90.0
    clock.t = _Boom(100.0)
    with _fails():
        lock_stats.asking()
    assert lock_stats._waiters == {me: 90.0} and lock_stats._live["waited_s"] == 0.0
    lock_stats.asking()
    assert lock_stats._waiters == {me: 100.0} and lock_stats._live["waited_s"] == 10.0


# --------------------------------------------------------------------------
# record() closes a wait whatever else it does, and the edges that are documented are pinned as edges
# --------------------------------------------------------------------------
def test_record_closes_a_leftover_waiter_even_when_the_window_statistic_fails(clock, monkeypatch):
    """``gave_up`` is the first statement of ``record``, not the last of its ``try``: the window update is the part that may
    raise (and ``record`` swallows it), and a waiter whose ``holding`` was skipped must not depend on it."""
    lock_stats.asking()  # registered; holding() never ran
    clock.t += 3.0
    with monkeypatch.context() as scoped:
        scoped.setattr(lock_stats, "_STATS_LOCK", _BrokenLock())
        lock_stats.record(asked=100.0, got=101.0, released=102.0, html="x")  # the window update raises inside; swallowed
    assert not lock_stats._waiters and lock_stats._live["waited_s"] == 3.0


def test_the_same_threads_next_hold_deepens_a_phantom_and_does_not_heal_it(clock):
    """A DOCUMENTED edge (``_mark``'s docstring), pinned so the words stay true: only another thread's hold heals a holder
    whose release was skipped; the same thread's next hold nests inside it."""
    me = threading.get_ident()
    lock_stats.holding()  # this thread takes the lock at 100 and its release mark is skipped
    clock.t += 5.0
    lock_stats.holding()  # the real lock is free again; the next extraction takes it
    assert (lock_stats._live["depth"], lock_stats._live["since"], lock_stats._live["holder"]) == (2, 100.0, me)
    clock.t += 5.0
    lock_stats.released()
    assert lock_stats._live["depth"] == 1, "one release closes one level: the phantom is still open"
    assert lock_stats.live_reading()["holder_age_s"] == 10.0, "its age keeps growing while the lock is free"
