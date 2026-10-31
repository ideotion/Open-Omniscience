"""A briefing pass names the producer that ran long, and no longer lets the caller's reads ride into the first producer.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE QUESTION THIS ANSWERS. The RC2 bundle of 2026-10-28 (build baecdf3d8) showed ``oo-briefing-refresh`` holding the log's read mark for
5,751 s while the log grew to 80.6 GB. The producer loop releases its read between producers (measured on the real session: the pool
checkout is back at 0 when the second producer starts), so one STEP held it, and the bundle could not say which: nothing recorded how long
each producer took. ``run_all_bounded`` now says so (a WARNING and ``stats["slow_producers"]``, from :data:`registry._SLOW_PRODUCER_S`).

Two smaller things found on the way, tested here because they share the cause (a read mark kept longer than the work needs):
the first producer shared one snapshot with everything the caller read before the loop, and a ``warm_cache`` spec that failed left its
transaction open for the specs after it.

The time is a real (short) sleep against a patched budget, never a patch of ``time.monotonic`` (process-wide, so a test thread would see it).
"""

from __future__ import annotations

import logging
import time

import pytest
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

import src.api.insights as ins
from src.briefing import registry
from src.utils.cache import SimpleCache

_BUDGET = 0.2  # the patched "slow" line: a producer that sleeps past it is slow, one that returns at once is not
_SLEEP = 0.25


def _session(tmp_path):
    eng = sa.create_engine(f"sqlite:///{tmp_path / 's.db'}", connect_args={"check_same_thread": False})
    return sessionmaker(bind=eng)()


def _two_producers(monkeypatch):
    def _quick(_s):
        return []

    def _slow(_s):
        time.sleep(_SLEEP)
        return []

    monkeypatch.setattr(registry, "_REGISTRY", [("quick", _quick), ("slow", _slow), ("quick2", _quick)])


def test_a_producer_over_the_budget_is_named_in_the_log_and_in_stats(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(registry, "_SLOW_PRODUCER_S", _BUDGET)
    _two_producers(monkeypatch)
    s = _session(tmp_path)
    try:
        with caplog.at_level(logging.WARNING, logger=registry._LOG.name):
            _cards, stats = registry.run_all_bounded(s)
    finally:
        s.close()
    slow = stats["slow_producers"]
    assert [p["name"] for p in slow] == ["slow"], slow
    assert slow[0]["seconds"] >= _SLEEP - 0.01
    assert slow[0]["started_at"].endswith("+00:00"), "the start is a UTC wall time, so a bundle's log lines can be matched to it"
    lines = [r.getMessage() for r in caplog.records if "took" in r.getMessage()]
    assert len(lines) == 1 and "'slow'" in lines[0], lines
    assert stats["truncated"] is False and stats["producers_run"] == 3, "naming a slow producer must not stop anything"


def test_a_pass_with_no_slow_producer_has_no_key(monkeypatch, tmp_path, caplog):
    """ABSENT, not empty: ``test_leads_quality_budget`` compares the whole stats dict, and a quiet pass should say nothing."""
    _two_producers(monkeypatch)  # the real 300 s budget: nothing here comes near it
    s = _session(tmp_path)
    try:
        with caplog.at_level(logging.WARNING, logger=registry._LOG.name):
            _cards, stats = registry.run_all_bounded(s)
    finally:
        s.close()
    assert "slow_producers" not in stats
    assert not [r for r in caplog.records if "took" in r.getMessage()]


def test_a_producer_that_raises_after_running_long_is_still_named(monkeypatch, tmp_path):
    """The time is taken after the isolation ``except``, so a producer that ran an hour and then failed is the one to name."""
    monkeypatch.setattr(registry, "_SLOW_PRODUCER_S", _BUDGET)

    def _slow_then_fails(_s):
        time.sleep(_SLEEP)
        raise RuntimeError("boom")

    monkeypatch.setattr(registry, "_REGISTRY", [("fails", _slow_then_fails)])
    s = _session(tmp_path)
    try:
        _cards, stats = registry.run_all_bounded(s)
    finally:
        s.close()
    assert [p["name"] for p in stats["slow_producers"]] == ["fails"]


def test_the_first_producer_starts_with_the_callers_read_released(monkeypatch, tmp_path):
    """Home reads before the loop (the watch pass ends with a flush). Before this, the first producer shared that snapshot."""
    seen: list[bool] = []

    def _first(session):
        seen.append(session.in_transaction())
        return []

    monkeypatch.setattr(registry, "_REGISTRY", [("first", _first)])
    s = _session(tmp_path)
    try:
        s.execute(text("SELECT 1")).fetchall()  # the caller's read: opens the transaction
        assert s.in_transaction()
        registry.run_all_bounded(s)
    finally:
        s.close()
    assert seen == [False], "the first producer ran inside the transaction the caller's reads opened"


@pytest.fixture
def warm(monkeypatch):
    monkeypatch.setattr(ins, "_CACHE_TTL_S", 300)
    monkeypatch.setattr(ins, "_read_cache", SimpleCache(max_size=16, default_ttl=300))


def test_a_failed_warm_spec_does_not_leave_its_read_open_for_the_next(monkeypatch, tmp_path, warm):
    s = _session(tmp_path)
    failed_in: list[object] = []
    top_in: list[object] = []

    def _fails_after_reading(db, *a, **k):
        db.execute(text("SELECT 1")).fetchall()  # the read the failing spec had already opened
        failed_in.append(db.get_transaction())
        raise RuntimeError("a spec failed")

    def _top(db, *a, **k):
        # Not ``in_transaction()``: the statement deadline the spec runs under touches the connection, so a fresh one is open here
        # either way. Which transaction it is says whether the failed spec's was ended.
        top_in.append(db.get_transaction())
        return {"x": 1}

    monkeypatch.setattr(ins.rm, "trending_windows", _fails_after_reading)
    monkeypatch.setattr(ins.rm, "top_terms", _top)
    try:
        out = ins.warm_cache(s)
    finally:
        s.rollback()
        s.close()
    assert len(failed_in) == 2 and len(top_in) == 1
    assert all(top_in[0] is not t for t in failed_in), "the spec after two failed ones ran inside a failed spec's transaction"
    assert failed_in[0] is not failed_in[1], "the second failed spec ran inside the first one's transaction"
    assert len(out["warmed"]) == 1, "a failed spec must still not stop the others"
