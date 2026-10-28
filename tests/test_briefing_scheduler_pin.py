"""The scheduler's background briefing refresh writes the cache where it started (the other half of R333; R355's 0.5.1 item).

``BackgroundScheduler._refresh_briefing_async`` ran ``refresh_briefing`` on ``oo-briefing-bg`` and the cache path was resolved from the data folder at
each read and write, so a refresh that outlived its test (or ran while the data folder changed) wrote ``briefing_cache.json`` into whatever
``OO_DATA_DIR`` was set at that moment. The path is now resolved before the thread exists and pinned inside it, the mechanism
``service._bg_refresh`` already uses (``tests/test_briefing_background_handle.py``).

No DB, no network: ``session_scope`` and ``refresh_briefing`` are stubbed. Not covered, stated: the shape of the cache file itself.
"""

from __future__ import annotations

import contextlib
import threading

import pytest

import src.briefing.service as service
from src.scheduler.runner import BackgroundScheduler
from src.scheduler.settings import SchedulerSettings

HANG_GUARD_S = 30


@pytest.fixture()
def sched():
    return BackgroundScheduler(settings_provider=lambda: SchedulerSettings())


@pytest.fixture()
def fake_scope(monkeypatch):
    @contextlib.contextmanager
    def _scope():
        yield object()

    monkeypatch.setattr("src.database.session.session_scope", _scope)


def test_the_background_refresh_resolves_the_cache_where_it_started_even_if_the_data_folder_moves(monkeypatch, tmp_path, sched, fake_scope):
    """Red before: ``_cache_path()`` asked ``data_dir()`` again inside the thread, so it answered ``moved/``."""
    started, moved = tmp_path / "started", tmp_path / "moved"
    monkeypatch.setenv("OO_DATA_DIR", str(started))
    in_the_run, release = threading.Event(), threading.Event()
    seen: list = []

    def refresh(session):
        in_the_run.set()
        release.wait(HANG_GUARD_S)
        seen.append(service._cache_path())  # what the real refresh asks, every time it reads or writes the cache

    monkeypatch.setattr(service, "refresh_briefing", refresh)
    try:
        sched._refresh_briefing_async()
        assert in_the_run.wait(HANG_GUARD_S), "the refresh never began"
        monkeypatch.setenv("OO_DATA_DIR", str(moved))
    finally:
        release.set()
    sched._briefing_thread.join(HANG_GUARD_S)
    assert not sched._briefing_thread.is_alive()
    assert seen == [started / "briefing_cache.json"], seen


@pytest.mark.parametrize("exits_with", [None, RuntimeError("the refresh failed")])
def test_the_pin_is_taken_off_on_every_way_out_of_the_block(monkeypatch, tmp_path, exits_with):
    """The scheduler's thread is a fresh one per refresh, so its own context dies with it and a scheduler-level test cannot tell whether the reset ran
    (removing the ``reset`` left the earlier version of this test green). The reset matters for any pooled thread that later uses the helper, so it is
    pinned on the helper itself, in the calling thread, on both exits."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "first"))
    expected = pytest.raises(RuntimeError) if exits_with else contextlib.nullcontext()
    with expected, service.pinned_cache_path(tmp_path / "pinned" / "briefing_cache.json"):
        assert service._cache_path() == tmp_path / "pinned" / "briefing_cache.json"
        if exits_with:
            raise exits_with
    assert service._run_cache_path.get() is None
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "second"))
    assert service._cache_path() == tmp_path / "second" / "briefing_cache.json"


def test_the_refresh_leaves_the_callers_cache_path_alone(monkeypatch, tmp_path, sched, fake_scope):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "first"))
    monkeypatch.setattr(service, "refresh_briefing", lambda session: None)
    sched._refresh_briefing_async()
    sched._briefing_thread.join(HANG_GUARD_S)
    assert service._run_cache_path.get() is None


def test_a_cache_folder_that_cannot_be_resolved_starts_nothing_and_frees_the_lock(monkeypatch, sched, fake_scope):
    """The lock was taken before the path is resolved; a failure there must not leave every later pass skipping the refresh as "still running"."""

    def cannot(*_a, **_k):
        raise OSError("the data folder cannot be resolved")

    real_cache_path = service._cache_path
    monkeypatch.setattr(service, "_cache_path", cannot)
    ran: list = []
    monkeypatch.setattr(service, "refresh_briefing", lambda session: ran.append(1))
    sched._refresh_briefing_async()  # does not raise
    assert not sched._briefing_bg_lock.locked(), "the lock stayed held"
    assert sched._briefing_thread is None and not ran
    monkeypatch.setattr(service, "_cache_path", real_cache_path)
    monkeypatch.setattr(service, "refresh_briefing", lambda session: ran.append(1))
    sched._refresh_briefing_async()
    sched._briefing_thread.join(HANG_GUARD_S)
    assert ran == [1], "the next pass did not run the refresh"
