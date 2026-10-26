"""Shared shapes for tests whose property is "this call does not wait for X".

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A test that holds an elapsed time to an upper bound ("it returned in under a second") cannot tell a defect from a pause: a
collection of a very large process, a stolen CPU slice or a loaded runner stretches the one just as the defect stretches the
other, and the bound is a figure somebody guessed was far enough above the healthy time (a connecting-cleanup sweep that
measured 0.05-0.11 s healthy went red on a pull request's CI at a bound of 0.5 s, and an encrypted read measured 2.73 s healthy
against a 3.0 s bound). The property is not a duration but an ORDER: the call came back while the thing it must not wait for was
still unfinished. So these tests either (a) make the thing it must not wait for report that it returned, and assert it had
not when the call came back, or (b) run the call on a thread with a long HANG GUARD and make the thing it must not wait for
outlast that guard, so that waiting for it is the only way to be late. Neither reads a clock.

A test of how a cost GROWS (a ratio of two timings, linear against quadratic) has no order to assert, so it is timed on the thread's
own CPU clock, which a pause, a stolen slice or a busy runner does not advance (``CPU_CLOCK``).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

#: How long a call that must come back at once is waited for before the test calls it hung. A guard, never a verdict: a call
#: that comes back returns this wait at once, so the guard costs a passing run nothing, and anything a test must not wait for is
#: made to outlast it.
HANG_GUARD_S = 20.0

#: The clock a scaling test times with: the thread's own CPU time where the platform has a fine one (Windows' ticks of about 15.6 ms
#: are coarser than the work timed), the wall clock where it has not.
CPU_CLOCK = time.thread_time if time.get_clock_info("thread_time").implementation.startswith("clock_gettime") else time.perf_counter


def wait_until(predicate: Callable[[], Any], guard_s: float = HANG_GUARD_S, step_s: float = 0.01) -> bool:
    """Poll ``predicate`` until it is true or ``guard_s`` has gone by; whether it became true. A test waits for a thread to have DONE what it
    asserts, observed, where it used to sleep a fixed time and hope: the guard is not a verdict, a thread that gets there returns at once, so
    a passing run waits only as long as the thread takes."""
    deadline = time.monotonic() + guard_s
    while True:
        if predicate():
            return True
        if time.monotonic() >= deadline:
            return bool(predicate())
        time.sleep(step_s)


def call_on_thread(fn: Callable[..., Any], *args: Any, guard_s: float = HANG_GUARD_S, **kwargs: Any) -> tuple[bool, Any]:
    """Run ``fn`` on a daemon thread and wait for it at most ``guard_s``: ``(whether it came back, its value)``.

    An exception it raised is raised here, on the caller's thread, so a test that expects one keeps its ``pytest.raises``
    around this call. A call still running when the guard ends is left running (the thread is a daemon): the caller says
    what it was waiting for, and releases whatever holds it."""
    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            box["value"] = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - handed to the caller's thread
            box["error"] = exc

    worker = threading.Thread(target=_run, daemon=True, name="oo-test-call")
    worker.start()
    worker.join(guard_s)
    if worker.is_alive():
        return False, None
    if "error" in box:
        raise box["error"]
    return True, box.get("value")


def quiet_pass_tail(monkeypatch: Any) -> None:
    """Take the real work a scheduler pass ends with out of a test of the LOOP.

    A pass is followed, before the loop can start the next one or answer a stop, by a collection of the whole process heap and a WAL
    checkpoint through the write gate (``run_pass_hygiene``) and a custody read (``_drain_owed_custody``). Their time belongs to the suite and
    the runner, not to the loop: measured, the tail is 0.5 s on a fresh process and 1.6 s with eight million objects alive, and the full run of
    a pull request (57 minutes, a heap to match) stretched it past a 5 s wait for pass two. A test of WHEN the loop starts a pass or stops
    asserts an order the tail has no part in, so the tail is stubbed out of it; the tests of the tail itself call it directly."""
    monkeypatch.setattr("src.scheduler.hygiene.run_pass_hygiene", lambda: None)
    monkeypatch.setattr("src.scheduler.runner._drain_owed_custody", lambda: None)


class SteppedClock:
    """A stand-in for the ``time`` module of ONE source module (``monkeypatch.setattr(module, "time", clock)``) that moves only when the code
    under test SLEEPS: ``sleep(s)`` adds ``s`` to ``now`` and returns at once, so a retry loop that waits out a budget runs to its end on
    the calling thread in no time, and what it waited is a sum the test can read (``slept``) instead of a duration a loaded runner can
    stretch. It carries what a retry loop uses (``monotonic`` and ``sleep``) and nothing else, so a module that reads another clock
    function in the path under test fails loudly rather than quietly using the real one."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += max(0.0, seconds)


def watch_flight_followers(monkeypatch: Any, heavy_module: Any) -> threading.Event:
    """An event that is set when a duplicate request begins waiting on a running flight of ``src.api.heavy``'s single-flight.

    A test of the follow path starts the leader, holds it, starts a duplicate and then lets the leader go. Letting it go after a fixed
    head start ("the follower is surely parked by now") is a bet on the scheduler: a duplicate that arrives after the flight ended is a
    leader of its own scan, and the test fails for a reason that is not the code's. The follower holds the flight the moment it calls
    ``wait`` on its event, and from there the leader's end can only wake it, so this is the point to release the leader at."""
    parked = threading.Event()
    real_flight = heavy_module._Flight

    class _SpyEvent(threading.Event):
        def wait(self, timeout: float | None = None) -> bool:
            parked.set()
            return super().wait(timeout)

    class _SpyFlight(real_flight):  # type: ignore[valid-type, misc]
        __slots__ = ()

        def __init__(self) -> None:
            super().__init__()
            self.event = _SpyEvent()

    monkeypatch.setattr(heavy_module, "_Flight", _SpyFlight)
    return parked


class CheckpointTimeoutWatch:
    """A DB-API connection that reports, for every ``wal_checkpoint`` run through it, the busy timeout in force at that moment (``seen``). A
    checkpoint that must "come back busy at once" is one run with the timeout at 0; the factory's connection waits 30 s on a reader that
    holds the log, and a step that waits less than the guard (10 s, say) would pass a test that only reads whether the call came back, so
    the timeout is read where it matters instead of the time that was spent."""

    def __init__(self, conn: Any, seen: list[int]) -> None:
        self._conn = conn
        self._seen = seen

    def execute(self, sql: Any, *args: Any, **kwargs: Any) -> Any:
        if "wal_checkpoint" in str(sql).lower():
            self._seen.append(int(self._conn.execute("PRAGMA busy_timeout").fetchone()[0]))
        return self._conn.execute(sql, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)
