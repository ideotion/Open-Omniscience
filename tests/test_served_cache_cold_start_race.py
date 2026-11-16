"""A cold poll that starts a fast compute still says when the compute started (the race #2043's CI met).

``served_cache.cached``'s non-blocking cold path kicked the background compute and THEN read its start time. A compute that ended
in between had already taken its start out of the in-flight table, so the poll answered ``pending: true`` ("computing") with
``pending_since: null`` -- a count described as running with no start, which the insights status test caught on CI (run
43808845357, shard 3). The kick now returns the start it recorded, and the cold path uses that. These tests force the fast
interleaving deterministically: the background thread's target runs to the end inside ``start()``, before the kick returns.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

from src.api import served_cache
from src.database.session import SessionLocal, init_db

_KEY = "test:cold-start-race"


def setup_module(_module):
    init_db()


@pytest.fixture(autouse=True)
def _clean():
    served_cache.invalidate()
    yield
    served_cache.invalidate()


class _ThreadThatFinishesInsideStart:
    """A thread whose whole run happens inside ``start()``: the fastest compute the scheduler could ever give."""

    def __init__(self, target=None, name=None, daemon=None, **_k):
        self._target = target

    def start(self):
        self._target()


def _compute(_session):
    return {"value": 7}


def _cheap(_session):
    return {"value": None}


def test_a_compute_that_ends_before_the_kick_returns_still_leaves_pending_since(monkeypatch):
    monkeypatch.setattr(served_cache.threading, "Thread", _ThreadThatFinishesInsideStart)
    s = SessionLocal()
    try:
        out = served_cache.cached(_KEY, _compute, s, ttl_s=60, cold_payload=_cheap)
    finally:
        s.close()
    assert out["pending"] is True
    assert out["pending_since"], "a poll that says the count is computing names when it started"
    assert out["recount_running_s"] is not None, "the same start time, read once, feeds both fields"
    with served_cache._LOCK:
        assert _KEY not in served_cache._RECOUNT_STARTED, "the finished compute is not left looking in flight"


def test_when_the_compute_in_flight_ends_before_the_read_the_poll_serves_its_value(monkeypatch):
    """The other side of the same window: this poll found a compute running (the lock taken, so it starts nothing), and that
    compute ended and stored before the poll read its start. The stored value is the answer, never "computing" since nothing.
    The state is built by hand (the lock held with no start beside it), which the real holders no longer leave: this pins the
    defence-in-depth branch, not a race the code can still run into."""
    s = SessionLocal()
    try:
        served_cache.refresh(_KEY, _compute)  # the compute that was in flight has stored its value...
        lock = served_cache._build_lock(_KEY)
        assert lock.acquire(blocking=False)  # ...and still holds the lock as this poll kicks, so the kick starts nothing
        try:
            with served_cache._LOCK:
                stored = served_cache._CACHE.pop(_KEY)  # the poll's first look found the cache cold
            real_kick = served_cache._kick_background_refresh

            def _kick_then_store(key, compute):
                got = real_kick(key, compute)
                with served_cache._LOCK:
                    served_cache._CACHE[key] = stored  # and between its kick and its read, the compute stored and ended
                return got

            monkeypatch.setattr(served_cache, "_kick_background_refresh", _kick_then_store)
            out = served_cache.cached(_KEY, _compute, s, ttl_s=60, cold_payload=_cheap)
        finally:
            lock.release()
    finally:
        s.close()
    assert out.get("pending") is not True and out["value"] == 7 and out["cached"] is True, out


def test_the_kick_reports_the_start_of_the_compute_already_running():
    lock = served_cache._build_lock(_KEY)
    assert lock.acquire(blocking=False)
    try:
        with served_cache._LOCK:
            served_cache._RECOUNT_STARTED[_KEY] = 1234.0
        assert served_cache._kick_background_refresh(_KEY, _compute) == 1234.0
    finally:
        with served_cache._LOCK:
            served_cache._RECOUNT_STARTED.pop(_KEY, None)
        lock.release()


def test_a_held_build_lock_always_has_a_start_beside_it(monkeypatch):
    """The lock and the start change together: no poll can find the lock taken and the start missing. Checked by patching the
    lock's release to look at the table at the instant of release, in the real background thread."""
    seen = []
    lock = served_cache._build_lock(_KEY)

    class _Watched:
        def acquire(self, blocking=True):
            got = lock.acquire(blocking)
            if got:
                seen.append(("acquired", served_cache._LOCK.locked()))
            return got

        def release(self):
            seen.append(("released", served_cache._LOCK.locked(), _KEY in served_cache._RECOUNT_STARTED))
            lock.release()

    monkeypatch.setattr(served_cache, "_build_lock", lambda key: _Watched())
    monkeypatch.setattr(served_cache.threading, "Thread", _ThreadThatFinishesInsideStart)
    s = SessionLocal()
    try:
        served_cache.cached(_KEY, _compute, s, ttl_s=60, cold_payload=_cheap)
    finally:
        s.close()
    assert seen == [("acquired", True), ("released", True, False)], seen


def test_a_compute_that_ended_without_storing_is_started_again_not_reported_as_running_since_nothing(monkeypatch):
    kicks = []
    real_kick = served_cache._kick_background_refresh

    def _first_kick_finds_one_just_ended(key, compute):
        kicks.append(key)
        if len(kicks) == 1:
            return None  # the compute this poll found running ended, and stored nothing
        return real_kick(key, compute)

    monkeypatch.setattr(served_cache, "_kick_background_refresh", _first_kick_finds_one_just_ended)
    monkeypatch.setattr(served_cache.threading, "Thread", _ThreadThatFinishesInsideStart)
    s = SessionLocal()
    try:
        out = served_cache.cached(_KEY, _compute, s, ttl_s=60, cold_payload=_cheap)
    finally:
        s.close()
    assert len(kicks) == 2 and out["pending"] is True and out["pending_since"], (kicks, out)


def test_a_cold_poll_that_finds_an_inline_compute_running_gets_its_start(monkeypatch):
    """The other holder of the build lock: ``cached`` without a cold payload computes inline under it. A poll of the same key with a
    cold payload that lands meanwhile finds the lock taken; the inline holder records its start beside the lock too, so the poll
    answers "computing since" that start, never "computing since nothing" (the Opus read of #2058, should-fix 1)."""
    import threading

    inside, release = threading.Event(), threading.Event()

    def slow_inline(_session):
        inside.set()
        assert release.wait(10)
        return {"n": 1}

    def run_inline():
        s = SessionLocal()
        try:
            served_cache.cached(_KEY, slow_inline, s, ttl_s=60)
        finally:
            s.close()

    t = threading.Thread(target=run_inline)
    t.start()
    try:
        assert inside.wait(10)
        s = SessionLocal()
        try:
            out = served_cache.cached(_KEY, _compute, s, ttl_s=60, cold_payload=_cheap)
        finally:
            s.close()
        assert out["pending"] is True and out["pending_since"] is not None
    finally:
        release.set()
        t.join(10)
    assert not served_cache._build_lock(_KEY).locked() and served_cache._recount_started(_KEY) is None


def test_an_inline_caller_that_waits_reuses_the_first_ones_value_and_the_lock_held_meanwhile_carries_a_start():
    """Two cold inline callers of one key: the second waits for the first, then serves the stored value; the compute ran once,
    the held lock carries a start while the first computes, and nothing is left held. (The waiter's own instant after the
    release is not sampled here: that it never takes the build lock to learn it is free is by construction, the wait being on
    ``_BUILD_RELEASED``.)"""
    import threading
    import time

    inside, release, calls, starts_seen = threading.Event(), threading.Event(), [], []

    def slow(_session):
        calls.append(1)
        inside.set()
        assert release.wait(10)
        return {"n": 2}

    def run(results):
        s = SessionLocal()
        try:
            results.append(served_cache.cached(_KEY, slow, s, ttl_s=60))
        finally:
            s.close()

    first, second = [], []
    t1 = threading.Thread(target=run, args=(first,))
    t1.start()
    assert inside.wait(10)
    t2 = threading.Thread(target=run, args=(second,))
    t2.start()
    for _ in range(20):  # while both are in, the held lock always carries a start
        with served_cache._LOCK:
            if served_cache._build_lock(_KEY).locked():
                starts_seen.append(served_cache._RECOUNT_STARTED.get(_KEY))
        time.sleep(0.01)
    release.set()
    t1.join(10)
    t2.join(10)
    assert calls == [1] and first[0]["n"] == second[0]["n"] == 2
    assert starts_seen and None not in starts_seen
    assert not served_cache._build_lock(_KEY).locked() and served_cache._recount_started(_KEY) is None
