"""The background briefing rebuild keeps a handle and writes the cache where it started (R333).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``_ensure_background_refresh`` started ``oo-briefing-refresh`` and dropped the Thread, and the thread asked ``data_dir()`` for the cache file at
each read and write. A test that left it running therefore wrote its cache into whatever ``OO_DATA_DIR`` a LATER test had set (R332), and no caller
could find the thread without walking ``threading.enumerate()``. The thread is now kept (``service._refresh_thread``) and the cache path is
resolved once, when the thread starts.

Not covered, stated: ``shutdown.py`` joins no named thread today, so nothing here adds a shutdown step; and ``warm_cache`` and ``_dismissed_path``
resolve their own paths.
"""

from __future__ import annotations

import threading
import time

import pytest

import src.briefing.service as service
from tests.conftest import _BRIEFING_THREAD_NAMES, _quiesce_briefing_threads

HANG_GUARD_S = 30


@pytest.fixture()
def fresh_state(monkeypatch):
    monkeypatch.setitem(service._refresh_state, "refreshing", False)
    monkeypatch.setitem(service._refresh_state, "paused", "")
    monkeypatch.setattr(service, "_log_pinned", lambda: False)
    monkeypatch.setattr(service, "_refresh_thread", None)


class _ThreadingWithoutEnumerate:
    """``threading`` as ``service`` sees it, with ``enumerate`` refused: the handle must be found without walking every thread. A copy bound to
    the one name the module reads, not a patch of ``threading`` for the whole process."""

    def enumerate(self):  # noqa: A003 - the name under test
        pytest.fail("the handle must be found without walking every thread")

    def __getattr__(self, name):
        return getattr(threading, name)


def test_the_thread_is_kept_and_found_without_enumerating_threads(monkeypatch, fresh_state):
    release = threading.Event()
    monkeypatch.setattr(service, "refresh_briefing", lambda session, on_progress=None: release.wait(HANG_GUARD_S))
    monkeypatch.setattr(service, "threading", _ThreadingWithoutEnumerate())
    assert service._refresh_thread is None
    try:
        service._ensure_background_refresh()
        handle = service._refresh_thread
        assert handle is not None and handle.name == "oo-briefing-refresh" and handle.is_alive()
    finally:
        release.set()
    handle.join(HANG_GUARD_S)
    assert not handle.is_alive()
    assert service._refresh_thread is handle, "the handle stays set after the thread ends; is_alive() says whether it still runs"


def test_a_second_start_while_one_runs_keeps_the_first_handle(monkeypatch, fresh_state):
    release = threading.Event()
    monkeypatch.setattr(service, "refresh_briefing", lambda session, on_progress=None: release.wait(HANG_GUARD_S))
    try:
        service._ensure_background_refresh()
        first = service._refresh_thread
        service._ensure_background_refresh()
        assert service._refresh_thread is first
    finally:
        release.set()
    first.join(HANG_GUARD_S)


def test_the_cache_is_written_where_the_thread_started_even_if_the_data_folder_moves_meanwhile(monkeypatch, tmp_path, fresh_state):
    """Red before: the write resolved ``data_dir()`` again, so the cache landed in ``moved/`` and ``started/`` stayed empty."""
    started, moved = tmp_path / "started", tmp_path / "moved"
    monkeypatch.setenv("OO_DATA_DIR", str(started))
    in_the_run = threading.Event()
    release = threading.Event()

    def hold(_session):  # the first thing a rebuild does; the real chain then runs on and writes the cache
        in_the_run.set()
        release.wait(HANG_GUARD_S)

    monkeypatch.setattr("src.analytics.watches.evaluate_watches", hold)
    monkeypatch.setattr("src.api.insights.warm_cache", lambda session: None)  # the cache write is what is under test, not the warm-up threads
    try:
        service._ensure_background_refresh()
        handle = service._refresh_thread
        assert in_the_run.wait(HANG_GUARD_S), "the rebuild never began"
        monkeypatch.setenv("OO_DATA_DIR", str(moved))
    finally:
        release.set()
    handle.join(HANG_GUARD_S)
    assert not handle.is_alive()
    assert (started / "briefing_cache.json").exists(), "the cache did not land where the thread started"
    assert not (moved / "briefing_cache.json").exists(), "the cache followed the data folder to where a later test had moved it"


def test_a_caller_outside_the_rebuild_thread_still_resolves_the_path_from_the_data_folder_each_time(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "a"))
    assert service._cache_path() == tmp_path / "a" / "briefing_cache.json"
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "b"))
    assert service._cache_path() == tmp_path / "b" / "briefing_cache.json"


def test_a_thread_that_cannot_be_started_leaves_the_state_as_it_was(monkeypatch, fresh_state):
    """Review finding 8: ``refreshing`` was set before ``start()``, so a failed start left it true for good and the kept handle unstarted."""

    class _CannotStart(threading.Thread):
        def start(self):
            raise RuntimeError("can't start new thread")

    class _ThreadingThatCannotStart:
        Thread = _CannotStart

        def __getattr__(self, name):
            return getattr(threading, name)

    monkeypatch.setattr(service, "threading", _ThreadingThatCannotStart())
    service._ensure_background_refresh()  # does not raise
    assert service._refresh_state["refreshing"] is False
    assert service._refresh_thread is None, "an unstarted Thread is not a handle"


def test_the_pin_does_not_leak_to_the_main_thread_after_a_rebuild_ran(monkeypatch, tmp_path, fresh_state):
    """The pin is a ContextVar set INSIDE the rebuild's thread: a thread starts in an empty context, so the caller's own ``_cache_path()`` is
    still resolved from the data folder afterwards."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "first"))
    monkeypatch.setattr(service, "refresh_briefing", lambda session, on_progress=None: None)
    service._ensure_background_refresh()
    handle = service._refresh_thread
    handle.join(HANG_GUARD_S)
    assert not handle.is_alive()
    assert service._run_cache_path.get() is None, "the pin reached the thread that started the rebuild"
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "second"))
    assert service._cache_path() == tmp_path / "second" / "briefing_cache.json"


# --------------------------------------------------------------------------- #
#  the conftest quiesce fixture (R333 part A)
# --------------------------------------------------------------------------- #
def test_the_quiesce_joins_a_briefing_thread_that_ends_inside_the_bound():
    release = threading.Event()
    t = threading.Thread(target=release.wait, args=(HANG_GUARD_S,), name=_BRIEFING_THREAD_NAMES[0], daemon=True)
    t.start()
    threading.Timer(0.2, release.set).start()
    _quiesce_briefing_threads("tests/x.py::joins", timeout=10)
    assert not t.is_alive()


def test_the_quiesce_fails_naming_the_thread_and_the_test_for_one_that_outlives_the_bound():
    release = threading.Event()
    t = threading.Thread(target=release.wait, args=(HANG_GUARD_S,), name=_BRIEFING_THREAD_NAMES[1], daemon=True)
    t.start()
    try:
        with pytest.raises(AssertionError) as err:
            _quiesce_briefing_threads("tests/x.py::leaves_one", timeout=0.3)
        assert "tests/x.py::leaves_one" in str(err.value) and "oo-briefing-bg" in str(err.value), str(err.value)
    finally:
        release.set()
        t.join(HANG_GUARD_S)


def test_the_quiesce_ignores_threads_that_are_not_briefing_threads():
    release = threading.Event()
    t = threading.Thread(target=release.wait, args=(HANG_GUARD_S,), name="some-other-thread", daemon=True)
    t.start()
    try:
        _quiesce_briefing_threads("tests/x.py::other", timeout=0.2)
    finally:
        release.set()
        t.join(HANG_GUARD_S)


def test_a_thread_that_outlives_the_bound_is_blamed_on_the_test_that_left_it_and_on_no_other():
    """Red before (the read of #1596): the next teardown listed the same thread again, waited the bound again and failed an innocent test."""
    release = threading.Event()
    t = threading.Thread(target=release.wait, args=(HANG_GUARD_S,), name=_BRIEFING_THREAD_NAMES[0], daemon=True)
    t.start()
    try:
        with pytest.raises(AssertionError, match="tests/x.py::first"):
            _quiesce_briefing_threads("tests/x.py::first", timeout=0.2)
        started = time.monotonic()
        _quiesce_briefing_threads("tests/x.py::second", timeout=5)  # the same thread, already reported: not waited on, not blamed again
        assert time.monotonic() - started < 2, "the reported thread was waited on again"
    finally:
        release.set()
        t.join(HANG_GUARD_S)


class _NotYetRunning:
    """A thread ``start()`` has been called on that has not run its first instruction: ``threading.enumerate()`` lists it and ``join`` raises
    ``RuntimeError`` (as ``Thread.join`` does before the thread has started) for the first ``join_attempts_refused`` attempts."""

    name = _BRIEFING_THREAD_NAMES[0]

    def __init__(self, join_attempts_refused):
        self._refused, self.joined = join_attempts_refused, False

    def join(self, timeout=None):
        if self._refused > 0:
            self._refused -= 1
            raise RuntimeError("cannot join thread before it is started")
        self.joined = True

    def is_alive(self):
        return False


class _ThreadingListing:
    """``threading`` as ``tests.conftest`` sees it, with ``enumerate`` answering a fixed list (a copy bound to the one name the quiesce reads)."""

    def __init__(self, listed):
        self._listed = listed

    def enumerate(self):  # noqa: A003 - the name under test
        return list(self._listed)

    def __getattr__(self, name):
        return getattr(threading, name)


def test_the_quiesce_retries_a_thread_that_cannot_be_joined_yet_and_then_joins_it(monkeypatch):
    """Review note 2 of #1596: a thread that had not started yet used to be skipped (and, after the first fix, one with an ident but not yet started still raised from the fixture), so a rebuild started a moment before the teardown ran into the next test."""
    import tests.conftest as conftest_module

    t = _NotYetRunning(join_attempts_refused=3)
    monkeypatch.setattr(conftest_module, "threading", _ThreadingListing([t]))
    _quiesce_briefing_threads("tests/x.py::limbo", timeout=10)
    assert t.joined, "a thread that was about to run was not joined"


def test_a_thread_that_cannot_be_joined_inside_the_bound_is_reported_not_skipped(monkeypatch):
    import tests.conftest as conftest_module

    t = _NotYetRunning(join_attempts_refused=10**9)
    monkeypatch.setattr(conftest_module, "threading", _ThreadingListing([t]))
    with pytest.raises(AssertionError, match="tests/x.py::stuck"):
        _quiesce_briefing_threads("tests/x.py::stuck", timeout=0.1)
    assert not t.joined, "a thread that never became joinable was reported as joined"


@pytest.mark.parametrize("paused", [False, True], ids=["ran", "paused-by-the-log-latch"])
def test_the_run_ends_with_the_pin_reset_in_the_context_it_ran_in(monkeypatch, tmp_path, fresh_state, paused):
    """Review note 1 of #1596: nothing failed when the reset in ``_bg_refresh``'s ``finally`` was removed. Called directly (not in its own thread) the
    pin is visible to this context, so a pin that outlives the run (a pooled worker's next task would inherit it) shows here, on both exits: a rebuild
    that ran, and the early return the write-ahead-log latch takes."""
    monkeypatch.setattr(service, "_log_pinned", lambda: paused)
    monkeypatch.setattr(service, "refresh_briefing", lambda session, on_progress=None: None)
    monkeypatch.setattr("src.api.insights.warm_cache", lambda session: None)
    monkeypatch.setattr("src.analytics.watches.evaluate_watches", lambda session: None)
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    service._bg_refresh(tmp_path / "pinned.json")
    assert service._run_cache_path.get() is None, "the pin outlived the run that set it"
