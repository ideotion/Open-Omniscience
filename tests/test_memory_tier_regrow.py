"""The memory tier follows a machine that GROWS while the app runs (R731, field test 2026-11-14 row 60).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Five of eight field instances resolved their tier from the RAM total a Qubes balloon reported at boot, then ran on
several GiB more for the rest of the session: the in-memory rollup off, or killed by a DuckDB limit sized for the
smaller machine. The budget now moves UP when a higher tier is read on two checks a minute apart. It never moves down
at runtime, never resizes the connection pool, and an operator's own value still wins.
"""

from __future__ import annotations

import logging

import pytest

from src.config import memory_budget as mb

pytestmark = pytest.mark.usefixtures("no_cgroup_limit")


@pytest.fixture
def machine(monkeypatch):
    mb.reset_for_tests()
    monkeypatch.delenv("OO_MEMORY_REGROW", raising=False)
    for env in ("OO_DB_POOL_SIZE", "OO_DB_MAX_OVERFLOW", "OO_SQLITE_CACHE_MB"):
        monkeypatch.delenv(env, raising=False)
    reading = {"mb": 3500.0}
    monkeypatch.setattr(mb, "total_ram_mb", lambda: reading["mb"])
    yield reading
    mb.reset_for_tests()


def test_a_sustained_growth_across_a_boundary_raises_the_tier_from_the_lower_reading(machine, caplog):
    boot = mb.budget()
    assert boot["tier"] == "small" and boot["columnar_serve_default"] is False
    machine["mb"] = 6200.0
    assert mb.regrow_check(now_mono=100.0) is None, "one reading is not sustained growth"
    assert mb.budget()["tier"] == "small"
    machine["mb"] = 5900.0
    assert mb.regrow_check(now_mono=130.0) is None, "a second reading inside the minute does not count"
    with caplog.at_level(logging.WARNING, logger="src.config.memory_budget"):
        change = mb.regrow_check(now_mono=161.0)
    assert change is not None and change["from_tier"] == "small" and change["to_tier"] == "medium"
    assert change["to_total_ram_mb"] == 5900.0, "sized from the LOWER of the two readings"
    now = mb.budget()
    assert now["tier"] == "medium" and now["columnar_serve_default"] is True
    assert now["duckdb_memory_limit_mb"] == int(5900.0 * 0.15) > boot["duckdb_memory_limit_mb"]
    assert now["sqlite_cache_mb"] == 16, "the page cache grows: it is read at each new connection"
    # the pool cannot change on a live engine, so it keeps its boot size, and the totals say so
    assert (now["db_pool_size"], now["db_max_overflow"]) == (boot["db_pool_size"], boot["db_max_overflow"])
    assert now["pool_total"] == boot["pool_total"]
    assert now["worst_case_pool_cache_mb"] == now["pool_total"] * 16
    assert "Re-resolved while running" in now["reason"] and "keeps the size it was built with" in now["reason"]
    logged = [r.getMessage() for r in caplog.records if "re-resolved upward" in r.getMessage()]
    assert len(logged) == 1 and "small" in logged[0] and "medium" in logged[0], "logged once, old and new tier"
    reading = mb.resolved_reading()
    assert reading["tier"] == "medium" and reading["regrown"][-1]["from_tier"] == "small"
    assert reading["first_resolved_at"] is not None


def test_a_shrink_never_lowers_the_tier(machine):
    machine["mb"] = 9000.0
    assert mb.budget()["tier"] == "large"
    machine["mb"] = 3000.0
    assert mb.regrow_check(now_mono=0.0) is None and mb.regrow_check(now_mono=120.0) is None
    assert mb.budget()["tier"] == "large"
    assert "regrown" not in mb.resolved_reading(), "a run that never re-resolved has no such key"


def test_growth_inside_one_tier_changes_nothing(machine):
    machine["mb"] = 4400.0
    before = dict(mb.budget())
    machine["mb"] = 7000.0
    assert mb.regrow_check(now_mono=0.0) is None and mb.regrow_check(now_mono=120.0) is None
    assert mb.budget() == before


def test_a_balloon_that_falls_back_before_the_second_check_is_not_credited(machine):
    mb.budget()
    machine["mb"] = 6200.0
    mb.regrow_check(now_mono=0.0)
    machine["mb"] = 3600.0  # back below the boundary: the pending reading is dropped
    assert mb.regrow_check(now_mono=70.0) is None
    machine["mb"] = 6200.0
    assert mb.regrow_check(now_mono=80.0) is None, "a new first reading, not the old one confirmed"
    assert mb.budget()["tier"] == "small"
    assert mb.regrow_check(now_mono=141.0) is not None


def test_an_operator_value_still_wins_after_a_regrow(machine, monkeypatch):
    monkeypatch.setenv("OO_SQLITE_CACHE_MB", "4")
    mb.budget()
    machine["mb"] = 9000.0
    mb.regrow_check(now_mono=0.0)
    assert mb.regrow_check(now_mono=60.0)["to_tier"] == "large"
    b = mb.budget()
    assert b["sqlite_cache_mb"] == 4 and b["overrides"] == {"sqlite_cache_mb": 4}


def test_the_switch_keeps_the_boot_budget_for_the_whole_run(machine, monkeypatch):
    monkeypatch.setenv("OO_MEMORY_REGROW", "0")
    mb.budget()
    machine["mb"] = 9000.0
    assert mb.regrow_check(now_mono=0.0) is None and mb.regrow_check(now_mono=120.0) is None
    assert mb.budget()["tier"] == "small"
    assert "not re-resolved" in mb.reading_vs_now()["caveat"]


def test_an_unmeasured_reading_is_no_evidence_of_growth(machine):
    mb.budget()
    machine["mb"] = None
    assert mb.regrow_check(now_mono=0.0) is None and mb.regrow_check(now_mono=120.0) is None
    assert mb.budget()["tier"] == "small"


def test_nothing_is_resolved_by_the_check_itself(machine):
    """Before the first ``budget()`` the check does nothing: the first resolve reads the machine as it is."""
    assert mb.regrow_check(now_mono=0.0) is None
    assert mb._CACHE is None  # noqa: SLF001 - the check must not be the first resolve


def test_the_liveness_thread_runs_the_check():
    from pathlib import Path

    src = Path("src/monitoring/session_history.py").read_text(encoding="utf-8")
    loop = src[src.index("def _loop() -> None:"):src.index("def start_liveness")]
    assert "regrow_check()" in loop and loop.index("tick_once()") < loop.index("regrow_check()")
