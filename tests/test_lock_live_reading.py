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
* the cleanup (an exception, a ``BaseException`` and an interrupted acquire each leave no phantom holder or waiter);
* the window and the gauge stay apart (a pass ``reset()`` does not touch the gauge);
* the marks sit where they say (``asking`` outside the lock, ``holding`` and ``released`` inside it, the clock read
  under the gauge's own lock) and do nothing but arithmetic;
* a broken gauge never breaks an extraction.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
import threading
import time

import pytest

import src.ingest.extract as extract_mod
from src.ingest import lock_stats
from src.ingest.extract import extract_article

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
    monkeypatch.setattr(lock_stats, "_live", {"depth": 0, "since": None, "occupied_s": 0.0, "waited_s": 0.0})
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
    """The log is built from the clock values the gauge ITSELF read (each extraction reads the clock six times in a
    fixed order: asked, ask, got, hold, released, release), so what is checked is the accounting, not the clock: the
    union of holds and the sum of waits inside any window, open ones included, to float rounding."""
    reads: dict[str, list[float]] = {}  # by thread NAME: an ident is reused once its thread has ended
    real = time.monotonic

    def tape() -> float:
        t = real()
        reads.setdefault(threading.current_thread().name, []).append(t)
        return t

    monkeypatch.setattr(lock_stats, "now", tape)

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
    stop.set()
    sampler.join(_WAIT)
    samples.append(lock_stats.live_reading())
    assert not any(w.is_alive() for w in workers) and len(samples) > 20

    holds: list[tuple[float, float]] = []
    waits: list[tuple[float, float]] = []
    for i in range(8):
        ticks = reads[f"hammer-{i}"]
        assert len(ticks) == 25 * 6, "six clock reads per extraction, in a fixed order"
        for i in range(0, len(ticks), 6):
            _asked, ask, _got, hold, _rel, release = ticks[i : i + 6]
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
            return real()

        monkeypatch.setattr(lock_stats, name, spy)
    monkeypatch.setattr(extract_mod, "_extract_locked", lambda html, *, url=None: _doc())
    extract_article(_PAGE)
    assert seen == [("asking", False), ("holding", True), ("released", True)]


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


def test_the_marks_inside_the_hold_call_nothing_but_arithmetic_and_the_clock():
    """The two marks inside the hold (and the one that closes a wait) may not call anything that blocks, takes another
    lock or does I/O: what they call is pinned by name."""
    assert _calls(lock_stats._mark) == {"step", "now"}
    assert _calls(lock_stats._on_ask) == {"threading.get_ident"}
    assert _calls(lock_stats._on_give_up) == {"_waiters.pop", "threading.get_ident", "max"}
    assert _calls(lock_stats._on_hold) == {"_on_give_up"}
    assert _calls(lock_stats._on_release) == {"max"}


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
