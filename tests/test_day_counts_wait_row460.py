"""Row 460: the daily keyword counts build does not start, and does not keep running, while a re-index drain would throw it away.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The build yields the writer between days (one transaction per day). What cost the field's Linux A 35,291 s of the gate was how often
it ran: the drain bumps the corpus epoch when it starts and when it ends, and a build at another epoch starts over. Pinned here:

- no build starts (boot, idle maintenance, fold_tail) while the drain job runs or its counter deferral is open;
- a running build stops at the next day once a drain starts;
- meanwhile trending reads LIVE sums, exactly, and nothing labels the stale table as current or as the source of an answer.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.analytics import day_counts
from tests.test_day_counts import _add, _build, _corpus, _live, _served, _table_rows, _truth


@pytest.fixture
def drain(monkeypatch):
    running = {"on": True}
    monkeypatch.setattr(day_counts, "_a_drain_is_running", lambda: running["on"])
    return running


def _open_deferral(eng) -> None:
    from sqlalchemy.orm import Session

    from src.analytics.counter_deferral import open_deferral

    with Session(bind=eng) as s:
        open_deferral(s, reason="row460 test")
        s.commit()


def test_no_build_starts_while_the_drain_runs(tmp_path, drain, monkeypatch):
    eng, s, _ex = _corpus(tmp_path)
    monkeypatch.setattr(day_counts.DAY_COUNTS_JOB, "start", lambda **_k: pytest.fail("a build started during a drain"))
    assert day_counts.build_waits_for(eng) == "reindex-drain"
    assert day_counts.start_build(eng) == "waiting"
    assert day_counts.start_build_if_needed(eng) == "waiting"
    assert day_counts.fold_tail(eng) == {"rebuild": "not-built", "job": "waiting"}


def test_no_build_starts_while_the_counter_deferral_is_open(tmp_path, drain, monkeypatch):
    """Between two drains of an import queue the job is not running, but the deferral stays open and the next drain bumps again."""
    eng, s, _ex = _corpus(tmp_path)
    drain["on"] = False
    assert day_counts.build_waits_for(eng) is None
    _open_deferral(eng)
    monkeypatch.setattr(day_counts.DAY_COUNTS_JOB, "start", lambda **_k: pytest.fail("a build started with the deferral open"))
    assert day_counts.build_waits_for(eng) == "counter-deferral"
    assert day_counts.start_build(eng) == "waiting"


def test_an_unreadable_drain_state_waits_rather_than_builds(tmp_path, monkeypatch):
    eng, _s, _ex = _corpus(tmp_path)

    def _boom(_kind):
        raise RuntimeError("registry unreadable")

    monkeypatch.setattr("src.jobs.background.get_job", _boom)
    assert day_counts._a_drain_is_running() is True
    assert day_counts.build_waits_for(eng) == "reindex-drain"


def test_a_running_build_stops_at_the_next_day_once_a_drain_starts(tmp_path, drain):
    eng, s, _ex = _corpus(tmp_path)
    drain["on"] = False
    calls = {"n": 0}
    real = day_counts._rebuild_day

    def _one_day_then_a_drain(conn, day, *, after=None):
        real(conn, day, after=after)
        calls["n"] += 1
        drain["on"] = True  # the import's drain starts while the build is on its first day

    day_counts._rebuild_day = _one_day_then_a_drain  # type: ignore[assignment]
    try:
        out = day_counts.build(eng)
    finally:
        day_counts._rebuild_day = real  # type: ignore[assignment]
    assert out["outcome"] == "stopped" and out["reason"] == "reindex-drain" and out["days"] == 1, out
    assert calls["n"] == 1, "the gate is given back at the next day, not after the whole build"
    with eng.connect() as conn:
        assert day_counts.current(conn) == "not-built", "a stopped build is never labelled current"


def test_trending_reads_live_and_exact_while_the_build_waits(tmp_path, drain, monkeypatch):
    from src.analytics import queries

    monkeypatch.setenv("OO_COLUMNAR_SERVE", "0")
    eng, s, ex = _corpus(tmp_path, n=12)
    _add(s, ex, 601, 4)
    assert day_counts.start_build(eng) == "waiting"
    assert _table_rows(eng) == {}
    assert _served(s) is None, "the table is not current: the serve says read live"
    assert _served(s, date(2026, 3, 2), date(2026, 3, 3)) is None
    end = date(2026, 3, 5)
    live = queries.trending(s, window_days=2, baseline_days=2, end=end, min_recent=1)
    assert live["terms"], "the scenario must rank something"
    assert live.get("basis", {}).get("source") != "day-counts", "a live answer is never labelled as served from the table"
    # And the live answer is the one the table gives once it is built: the wait changes where the numbers come from, not them.
    drain["on"] = False
    _build(eng)
    assert _table_rows(eng) == _truth(eng)
    served = queries.trending(s, window_days=2, baseline_days=2, end=end, min_recent=1)
    assert served.get("basis", {}).get("source") == "day-counts"
    for key in ("terms", "scanned", "keywords_with_recent_mentions", "count"):
        assert served[key] == live[key], key
    assert _served(s) == _live(s)
