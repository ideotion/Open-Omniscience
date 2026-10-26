"""0.5.1 item 28: under a persistent out-of-memory the persisted refresh is not started again by the very next kick.

Before: the in-memory build keeps a hold when it fails (R172) or stops on DuckDB's limit, but ``_record_failure`` and
``_stopped_build_verdict`` both returned at once when the PERSISTED store (D1, the encrypted-corpus path) was active, so a failure of
``_refresh_persisted_build`` kept nothing. With no rollup built, every serve call that wants one kicks a build, and ``trending`` asks
for two windows back to back: one request made two full ``refresh_keyword_daily`` attempts, and every poll after it one more.
After: the failure keeps the same hold for THIS process (marked ``store: persisted``, nothing written beside the persisted store, so a
restart tries once more), released by what releases a ``duckdb-limit`` hold; a hold is about the store whose build made it.

The persisted mechanism is read from code: these tests stub ``_refresh_persisted_build`` (the real one needs the keyed DuckDB attach),
so they pin the dispatcher and the hold, not the engine.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

import pytest

from src.analytics import rollup_hold, rollup_serve


class OutOfMemoryException(Exception):  # noqa: N818 - the engine's own class name, which is what the hold records
    pass


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("src.analytics.serve_gate.exclusive_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_boot_order_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_affordability_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_memory_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_last_build_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "serve_enabled", lambda: True)
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: True)
    monkeypatch.setattr(rollup_serve, "_current_epoch", lambda: 7)
    monkeypatch.setattr(rollup_serve, "_current_mention_count", lambda: 1000)
    monkeypatch.setattr(rollup_serve, "_duckdb_limit_mb", lambda: 1004.0)
    # the budget and the limit are one reading in the app: a hold records the limit it ran under
    monkeypatch.setattr(rollup_serve, "_build_budget", lambda: {"duckdb_limit_mb": rollup_serve._duckdb_limit_mb(), "offload_allowed": False})
    keys = ("con", "stopped", "failures", "failure_class", "last_outcome", "last_decline", "last_skip", "persisted", "built_at", "bind")
    keep = {k: rollup_serve._STATE.get(k) for k in keys}
    rollup_serve._STATE.update(con=None, stopped=None, failures=0, failure_class=None, last_outcome=None, last_decline=None,
                               last_skip=None, persisted=False, built_at=0.0, bind=None)
    rollup_serve._STATE.pop("last_outcome_restored", None)
    monkeypatch.setattr(rollup_serve, "_HOLD_LOOKED", False)
    monkeypatch.setattr(rollup_serve, "_LAST_STAGE", {"value": None})

    def sync_trigger():
        """The background kick, run in the calling thread so the build has ended before the next call (the worst case for a double start)."""
        if rollup_serve._BUILD_LOCK.acquire(blocking=False):
            rollup_serve._build_and_swap()

    monkeypatch.setattr(rollup_serve, "_trigger_build_async", sync_trigger)
    yield
    rollup_serve._STATE.update(keep)
    rollup_serve._STATE.pop("last_outcome_restored", None)


def _refresh_stub(monkeypatch, raises=OutOfMemoryException):
    calls: list[int] = []

    def refresh():
        calls.append(1)
        if raises is not None:
            raise raises("engine words that must not be kept")

    monkeypatch.setattr(rollup_serve, "_refresh_persisted_build", refresh)
    return calls


def _trending_shaped_pair():
    """What ``queries.trending`` asks of the serve: the recent window, then the prior one, back to back."""
    today = date.today()
    first = rollup_serve.windowed_counts(None, lo=today - timedelta(days=7), hi=today)
    second = rollup_serve.windowed_counts(None, lo=today - timedelta(days=37), hi=today - timedelta(days=8))
    return first, second


def test_one_request_that_asks_for_two_windows_makes_one_persisted_attempt_under_a_persistent_out_of_memory(monkeypatch):
    calls = _refresh_stub(monkeypatch)
    assert _trending_shaped_pair() == (None, None), "no rollup yet: both are answered by the live scan"
    assert len(calls) == 1, f"{len(calls)} persisted attempts for one request: the failure was not held"
    for _ in range(5):  # and the polls after it
        _trending_shaped_pair()
    assert len(calls) == 1


def test_the_hold_is_this_processs_own_and_names_the_class_and_never_the_engines_words(monkeypatch):
    _refresh_stub(monkeypatch)
    _trending_shaped_pair()
    held = rollup_serve._STATE["stopped"]
    assert held["reason"] == "build-failed" and held["store"] == "persisted"
    assert held["engine_error_class"] == "OutOfMemoryException" and held["consecutive_failures"] == 1
    assert "engine words" not in repr(rollup_serve.status()) and "engine words" not in repr(held)
    assert rollup_hold.read() is None, "nothing is written beside the persisted store: a restart tries once more"
    assert rollup_serve.status()["consecutive_failures"] == 1


def test_a_larger_memory_limit_releases_the_hold_and_the_next_kick_tries_again(monkeypatch):
    calls = _refresh_stub(monkeypatch)
    _trending_shaped_pair()
    assert len(calls) == 1
    monkeypatch.setattr(rollup_serve, "_duckdb_limit_mb", lambda: 2008.0)  # the budget grew: the condition that held it changed
    _trending_shaped_pair()
    assert len(calls) == 2, "a released hold must let the refresh run again, once"
    assert rollup_serve._STATE["failures"] == 2, "and a second failure extends the run"


def test_a_refresh_that_serves_ends_the_hold_and_the_run(monkeypatch):
    calls = _refresh_stub(monkeypatch)
    _trending_shaped_pair()
    monkeypatch.setattr(rollup_serve, "_duckdb_limit_mb", lambda: 2008.0)
    _refresh_stub(monkeypatch, raises=None)
    _trending_shaped_pair()
    assert rollup_serve._STATE["stopped"] is None and rollup_serve._STATE["failures"] == 0
    assert len(calls) == 1


def test_a_hold_is_about_the_store_whose_build_made_it(monkeypatch):
    """An in-memory stop does not hold the persisted refresh, and a persisted failure does not hold an in-memory build."""
    now = time.time()
    rollup_serve._STATE["stopped"] = {"reason": "duckdb-limit", "at": now, "duckdb_limit_mb": 1004.0, "offload_allowed": False, "epoch": 7}
    monkeypatch.setattr(rollup_serve, "_HOLD_LOOKED", True)
    assert rollup_serve._stopped_build_verdict() is None, "persisted active: the in-memory stop is not its hold"
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: False)
    assert rollup_serve._stopped_build_verdict() is not None, "in-memory active: its own stop still holds"
    rollup_serve._STATE["stopped"] = {"reason": "build-failed", "at": now, "duckdb_limit_mb": 1004.0, "offload_allowed": False, "epoch": 7,
                                      "store": "persisted"}
    assert rollup_serve._stopped_build_verdict() is None, "in-memory active: a persisted failure is not its hold"
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: True)
    assert rollup_serve._stopped_build_verdict() is not None, "persisted active: its own failure holds"


def test_a_recount_of_a_persisted_hold_never_writes_the_kept_file(monkeypatch):
    """The wall's recount re-keeps the hold; for a persisted one that must stay in this process, or it overwrites an in-memory wall hold the file kept."""
    _refresh_stub(monkeypatch)
    _trending_shaped_pair()
    assert rollup_hold.read() is None
    held = rollup_serve._STATE["stopped"]
    later = held["at"] + rollup_serve._BACKSTOP_S + 1
    monkeypatch.setattr(rollup_serve.time, "time", lambda: later)
    monkeypatch.setattr(rollup_serve, "_current_epoch", lambda: 8)  # the epoch moved and the count did not shrink: the hold stands, re-kept
    assert rollup_serve._stopped_build_verdict() is not None
    assert rollup_serve._STATE["stopped"]["epoch"] == 8 and rollup_serve._STATE["stopped"]["store"] == "persisted"
    assert rollup_hold.read() is None, "the recount wrote a persisted hold to the kept file"


def test_the_hold_is_about_the_store_the_failed_build_ran_for_not_the_store_read_afterwards(monkeypatch):
    """The store toggles while the persisted refresh runs (the passphrase arrives, or goes): the failure is still the persisted refresh's."""
    active = {"persisted": True}
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: active["persisted"])

    def refresh():
        active["persisted"] = False
        raise OutOfMemoryException("engine words that must not be kept")

    monkeypatch.setattr(rollup_serve, "_refresh_persisted_build", refresh)
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)  # the dispatcher releases the build lock it is called holding
    rollup_serve._build_and_swap()
    assert rollup_serve._STATE["stopped"]["store"] == "persisted"
    assert rollup_hold.read() is None


def test_a_persisted_refresh_that_opened_no_connection_is_neither_built_nor_the_end_of_a_failure_run(monkeypatch):
    """``_refresh_persisted_build`` returns without refreshing when the passphrase or backend vanished: that is no build, so no "built", and a run of failures stands."""
    rollup_serve._STATE.update(failures=2, failure_class="OutOfMemoryException")
    monkeypatch.setattr(rollup_serve, "_refresh_persisted_build", lambda: False)
    monkeypatch.setitem(rollup_serve._LAST_OUTCOME, "value", "failed")
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
    assert rollup_serve._build_and_swap() == "declined"
    assert rollup_serve._LAST_OUTCOME["value"] != "built"
    assert rollup_serve._STATE["failures"] == 2 and rollup_serve._STATE["failure_class"] == "OutOfMemoryException", "a no-op ended the failure run"
    skip = rollup_serve._STATE["last_skip"]
    assert skip["reason"] == "persisted-unavailable" and skip["source"] == "persisted"
    assert rollup_serve._STATE["stopped"] is None, "no build ran, so no failure hold is kept for it either"


def test_a_refresh_that_ran_is_still_built(monkeypatch):
    """Negative space: only an explicit False is the no-connection case, so a refresh that returns True (or nothing, as the stubs do) is a build."""
    for returned in (True, None):
        rollup_serve._STATE.update(failures=2, failure_class="OutOfMemoryException")
        monkeypatch.setattr(rollup_serve, "_refresh_persisted_build", lambda r=returned: r)
        assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
        assert rollup_serve._build_and_swap() == "built"
        assert rollup_serve._STATE["failures"] == 0
