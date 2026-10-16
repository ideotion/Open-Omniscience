"""The first Library figures request must not compute the whole-table keyword_mentions COUNT on the request thread.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field diagnostics of 2026-10-16: GET /api/database/figures took 55.6 s ONCE, the first call of a process 8.5 hours old, because
the served cache was cold and ``served_cache.cached`` computed inline; 99.6 % of the request was its own
``SELECT count(*) FROM keyword_mentions_all``. These tests pin the replacement: the cold start answers at once with the cheap
figures and the count as not yet known, ONE background count runs (single-flight), a count that cannot finish is a named failure
that holds a stated window instead of being retried per poll, and the count never runs on the request thread.
"""

from __future__ import annotations

import threading
import time

import pytest

from src.api import database as dbmod
from src.api import served_cache
from src.database.maintenance import StatementTimeout
from src.database.models import Article, Source
from src.database.session import SessionLocal, init_db


def setup_module(_module):
    init_db()


@pytest.fixture(autouse=True)
def _clean_cache():
    served_cache.invalidate()
    yield
    served_cache.invalidate()


def _wait(pred, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def _entry(key):
    with served_cache._LOCK:
        e = served_cache._CACHE.get(key)
        return dict(e) if e else None


def test_a_cold_call_answers_at_once_runs_one_background_compute_and_then_serves_it():
    release = threading.Event()
    ran: list[int] = []

    def compute(_session):
        ran.append(threading.get_ident())
        release.wait(5)
        return {"n": 42}

    s = SessionLocal()
    try:
        t0 = time.monotonic()
        first = served_cache.cached("t:cold", compute, s, ttl_s=60, cold_payload=lambda _s: {"cheap": 1})
        elapsed = time.monotonic() - t0
        assert elapsed < 2.0, "the cold call waited for the compute"
        assert first["pending"] is True and first["cheap"] == 1 and first["pending_since"] and first["cached"] is False
        second = served_cache.cached("t:cold", compute, s, ttl_s=60, cold_payload=lambda _s: {"cheap": 1})
        assert second["pending"] is True
        assert _wait(lambda: len(ran) >= 1)
        release.set()
        assert _wait(lambda: _entry("t:cold") is not None)
        third = served_cache.cached("t:cold", compute, s, ttl_s=60, cold_payload=lambda _s: {"cheap": 1})
    finally:
        s.close()
    assert len(ran) == 1, "two cold callers started two computes"
    assert ran[0] != threading.get_ident(), "the compute ran on the request thread"
    assert third["n"] == 42 and third["cached"] is True and "pending" not in third


def test_an_entry_can_hold_its_own_longer_window_so_a_recorded_failure_is_not_retried_per_poll(monkeypatch):
    calls: list[int] = []
    ticks = iter(range(1, 1000))
    monkeypatch.setattr(served_cache, "change_probe", lambda: next(ticks))  # something is always being written

    def compute(_session):
        calls.append(1)
        return {"state": "failed", "__ttl_s__": 900}

    s = SessionLocal()
    try:
        served_cache.cached("t:fail", compute, s, ttl_s=60, cold_payload=lambda _s: {})
        assert _wait(lambda: _entry("t:fail") is not None)
        assert _entry("t:fail")["ttl_s"] == 900
        with served_cache._LOCK:
            served_cache._CACHE["t:fail"]["checked_at"] -= 120  # older than the endpoint's 60 s, younger than the 900 s window
        out = served_cache.cached("t:fail", compute, s, ttl_s=60, cold_payload=lambda _s: {})
        time.sleep(0.3)
    finally:
        s.close()
    assert out["state"] == "failed" and "__ttl_s__" not in out
    assert len(calls) == 1, "a failure inside its window was retried"


def _seed_article():
    s = SessionLocal()
    try:
        if s.query(Article).count():
            return
        src = Source(name="cold-src", domain="cold.test")
        s.add(src)
        s.flush()
        s.add(Article(title="t", url="http://cold.test/1", canonical_url="http://cold.test/1", source_id=src.id,
                      content="c", hash="cold-h1", word_count=10))
        s.commit()
    finally:
        s.close()


def test_the_figures_route_answers_cold_without_the_count_and_then_carries_it(monkeypatch):
    _seed_article()
    release = threading.Event()
    seen: list[int] = []

    def slow_count(_db):
        seen.append(threading.get_ident())
        release.wait(5)
        return 12

    monkeypatch.setattr(dbmod, "_mentions_count", slow_count)
    s = SessionLocal()
    try:
        first = dbmod.library_figures(s)
        assert first["articles"] >= 1 and first["keyword_mentions"] is None and first["avg_keywords_per_article"] is None
        assert first["keyword_mentions_state"] == "computing" and first["pending"] is True and first["keyword_mentions_reason"]
        assert first["avg_word_count"] is not None, "the cheap figures are exact now"
        release.set()
        assert _wait(lambda: (_entry("db:figures") or {}).get("payload", {}).get("keyword_mentions_state") == "counted")
        done = dbmod.library_figures(s)
    finally:
        s.close()
    assert seen and seen[0] != threading.get_ident(), "the count ran on the request thread"
    assert done["keyword_mentions"] == 12 and done["keyword_mentions_state"] == "counted"
    assert done["avg_keywords_per_article"] == round(12 / done["articles"], 1)


def test_a_count_past_its_deadline_is_a_named_failure_held_for_its_window(monkeypatch):
    _seed_article()
    calls: list[int] = []
    ticks = iter(range(1, 1000))
    monkeypatch.setattr(served_cache, "change_probe", lambda: next(ticks))  # writes keep landing: only the window holds it

    def hits_deadline(_db):
        calls.append(1)
        raise StatementTimeout("the statement ran past its deadline")

    monkeypatch.setattr(dbmod, "_mentions_count", hits_deadline)
    s = SessionLocal()
    try:
        dbmod.library_figures(s)
        assert _wait(lambda: (_entry("db:figures") or {}).get("payload", {}).get("keyword_mentions_state") == "failed")
        entry = _entry("db:figures")
        out = dbmod.library_figures(s)
    finally:
        s.close()
    fail = out["keyword_mentions_failure"]
    assert fail["kind"] == "statement-deadline" and fail["retry_after_s"] == dbmod._FIGURES_FAILURE_WINDOW_S
    assert fail["deadline_s"] == dbmod._count_deadline_s() and fail["at"]
    assert out["keyword_mentions"] is None and out["avg_keywords_per_article"] is None
    assert entry["ttl_s"] == dbmod._FIGURES_FAILURE_WINDOW_S
    with served_cache._LOCK:
        served_cache._CACHE["db:figures"]["checked_at"] -= 200  # past the 60 s interval, inside the failure window
    s = SessionLocal()
    try:
        dbmod.library_figures(s)
    finally:
        s.close()
    time.sleep(0.3)
    assert len(calls) == 1, "the failed count was retried inside its window"


def test_another_error_in_the_count_is_named_by_its_class_only(monkeypatch):
    _seed_article()

    def boom(_db):
        raise RuntimeError("C:\\Users\\someone\\secret.db is locked")

    monkeypatch.setattr(dbmod, "_mentions_count", boom)
    s = SessionLocal()
    try:
        dbmod.library_figures(s)
        assert _wait(lambda: (_entry("db:figures") or {}).get("payload", {}).get("keyword_mentions_state") == "failed")
        out = dbmod.library_figures(s)
    finally:
        s.close()
    assert out["keyword_mentions_failure"]["kind"] == "RuntimeError"
    assert "secret" not in str(out) and "Users" not in str(out)


def test_the_background_count_runs_under_a_statement_deadline_that_can_be_set(monkeypatch):
    import contextlib

    import src.database.maintenance as maint

    _seed_article()
    seen: list[float] = []

    @contextlib.contextmanager
    def spy(_session, seconds=None):
        seen.append(seconds)
        yield

    monkeypatch.setattr(maint, "statement_deadline", spy)
    monkeypatch.setattr(dbmod, "_mentions_count", lambda _db: 3)
    monkeypatch.setenv("OO_FIGURES_COUNT_DEADLINE_S", "7")
    s = SessionLocal()
    try:
        out = dbmod._compute_figures_counted(s, dbmod.datetime.now(dbmod.UTC))
    finally:
        s.close()
    assert seen == [7.0] and out["keyword_mentions"] == 3 and out["keyword_mentions_state"] == "counted"
    monkeypatch.delenv("OO_FIGURES_COUNT_DEADLINE_S")
    assert dbmod._count_deadline_s() == dbmod._FIGURES_COUNT_DEADLINE_S == 300.0
