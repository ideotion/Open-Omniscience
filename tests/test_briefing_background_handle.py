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


def test_the_thread_is_kept_and_found_without_enumerating_threads(monkeypatch, fresh_state):
    release = threading.Event()
    monkeypatch.setattr(service, "refresh_briefing", lambda session, on_progress=None: release.wait(HANG_GUARD_S))
    monkeypatch.setattr(threading, "enumerate", lambda: pytest.fail("the handle must be found without walking every thread"))
    assert service._refresh_thread is None
    service._ensure_background_refresh()
    handle = service._refresh_thread
    assert handle is not None and handle.name == "oo-briefing-refresh" and handle.is_alive()
    release.set()
    handle.join(HANG_GUARD_S)
    assert not handle.is_alive()
    assert service._refresh_thread is handle, "the handle stays set after the thread ends; is_alive() says whether it still runs"


def test_a_second_start_while_one_runs_keeps_the_first_handle(monkeypatch, fresh_state):
    release = threading.Event()
    monkeypatch.setattr(service, "refresh_briefing", lambda session, on_progress=None: release.wait(HANG_GUARD_S))
    service._ensure_background_refresh()
    first = service._refresh_thread
    service._ensure_background_refresh()
    assert service._refresh_thread is first
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
    service._ensure_background_refresh()
    handle = service._refresh_thread
    assert in_the_run.wait(HANG_GUARD_S), "the rebuild never began"
    monkeypatch.setenv("OO_DATA_DIR", str(moved))
    release.set()
    handle.join(HANG_GUARD_S)
    assert not handle.is_alive()
    assert (started / "briefing_cache.json").exists(), "the cache did not land where the thread started"
    assert not (moved / "briefing_cache.json").exists(), "the cache followed the data folder to where a later test had moved it"


def test_a_caller_in_another_thread_still_resolves_the_path_from_the_data_folder_each_time(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "a"))
    assert service._cache_path() == tmp_path / "a" / "briefing_cache.json"
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "b"))
    assert service._cache_path() == tmp_path / "b" / "briefing_cache.json"


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
