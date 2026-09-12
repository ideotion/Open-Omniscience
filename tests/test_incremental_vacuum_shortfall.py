"""What incremental vacuum reports about the pages it did not reclaim (C3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field diagnostics 2026-09-11. The off-peak pass reported ``freelist_pages_before
141679`` -> ``after 141678`` against ``requested_pages 2000``: ONE page reclaimed of two
thousand, with about 2.22 GB stranded in a 27.7 GB database -- and said nothing about it.

THE FIRST READING OF THAT WAS WRONG, and this file records the correction because the
wrong reading is the intuitive one. It looked like a store the pragma could not help, so
the first fix shipped an alarm on "asked for N, got fewer, and more than N are still
free". But the pragma was never stepped past its first page (SQLAlchemy finalises a
cursor it believes returns no rows), so that condition was measuring the BUG, not the
store, and it fires approximately never once the cursor is drained.

The three outcomes that actually occur were then measured on a real store (freelist 445,
page_size 4096):

  * budget-bound   -- requested 5 -> reclaimed exactly 5, 440 still free;
  * unobstructed   -- requested 100,000 -> freelist drained to ZERO;
  * reader-blocked -- a second connection holding a read snapshot makes the pragma RAISE
    ``database is locked``, rather than quietly returning fewer pages.

So what these tests pin is that the report names a RESIDUAL as a budget statement, with
the knob that changes it, and does not dress a healthy bounded run up as a fault by
blaming a reader that is not there. Inventing a cause for a healthy run is the same
defect as staying silent about an unhealthy one, pointed the other way.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from src.database.maintenance import maybe_incremental_vacuum


def _store(tmp_path, *, auto_vacuum: str):
    """A real on-disk SQLite store, because this defect only exists in a real one."""
    path = tmp_path / "store.db"
    engine = create_engine(f"sqlite:///{path}", future=True)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.execute(text(f"PRAGMA auto_vacuum={auto_vacuum}"))
        c.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, blob TEXT)"))
        c.execute(text("VACUUM"))  # makes the auto_vacuum mode take effect
    return engine, path


def _fill_then_free(engine, *, rows: int = 4000) -> None:
    """Create a large freelist: insert a lot, then delete it."""
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        payload = "x" * 400
        c.execute(
            text("INSERT INTO t (blob) SELECT :p FROM (WITH RECURSIVE n(i) AS "
                 "(SELECT 1 UNION ALL SELECT i+1 FROM n WHERE i < :rows) SELECT i FROM n)"),
            {"p": payload, "rows": rows},
        )
        c.execute(text("DELETE FROM t"))


@pytest.fixture(autouse=True)
def _fresh_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)


def test_a_healthy_reclaim_carries_no_shortfall_noise(tmp_path, monkeypatch):
    """The report must not grow a scary block on a run that worked -- an alarm that
    fires on the healthy path is one nobody reads on the unhealthy one."""
    monkeypatch.setenv("OO_INCREMENTAL_VACUUM_PAGES", "100000")
    engine, _ = _store(tmp_path, auto_vacuum="INCREMENTAL")
    _fill_then_free(engine)

    report = maybe_incremental_vacuum(engine)

    assert "skipped" not in report, report
    # Asked for far MORE pages than are free, so the request was not the limit and
    # whatever remains is not a shortfall against it -- no alarm.
    assert report["pages_reclaimed"] > 0
    # CORRECTED once the cursor drain landed. This comment used to record that "a few
    # hundred pages survived a 100,000-page request" and built the alarm condition on
    # it. That was the BUG being measured, not the store: the pragma was never stepped
    # past its first page. With the drain, an unobstructed store given a budget larger
    # than its freelist drains to ZERO, so there is no residual to report at all.
    assert report["freelist_pages_after"] == 0
    assert "residual" not in report


def test_a_budget_bound_run_names_its_residual_without_crying_wolf(tmp_path, monkeypatch):
    """A pass that spends its whole allowance and leaves pages free is the design
    working -- bounded work in an idle window -- but the operator still needs to know
    the pages are there. Measured shape: freelist 445, budget 5 -> reclaimed exactly 5,
    440 still free."""
    monkeypatch.setenv("OO_INCREMENTAL_VACUUM_PAGES", "5")
    engine, _ = _store(tmp_path, auto_vacuum="INCREMENTAL")
    _fill_then_free(engine)

    report = maybe_incremental_vacuum(engine)

    assert "skipped" not in report, report
    # The drain means the budget is now honoured exactly, which is the whole fix.
    assert report["pages_reclaimed"] == 5
    res = report["residual"]
    assert res["budget_bound"] is True
    assert res["still_free_pages"] == report["freelist_pages_after"]
    assert res["still_free_bytes"] == report["freelist_pages_after"] * report["page_size"]

    # It must read as a budget statement, NOT as a fault: no invented cause, and the
    # knob that actually changes the outcome is named.
    assert "The per-pass budget was the limit, not the store" in res["detail"]
    assert "OO_INCREMENTAL_VACUUM_PAGES" in res["detail"]
    assert "reader" not in res["detail"], "a healthy budget-bound run must not blame a reader"

    # A full VACUUM stays offered with its real cost, and explicitly not run here.
    note = res["full_vacuum_note"]
    assert "blocks writes" in note and "free disk" in note
    assert "operator's button" in note


def test_a_reader_blocked_run_raises_rather_than_under_reclaiming(tmp_path):
    """Pins the measurement the residual's wording depends on. A second connection
    holding a read snapshot does NOT make incremental_vacuum quietly return fewer pages
    -- it makes the pragma raise `database is locked`, which lands in the existing error
    branch. This is why the budget-bound path carries no reader-snapshot 'candidates':
    that shape does not reach it."""
    import sqlite3

    engine, path = _store(tmp_path, auto_vacuum="INCREMENTAL")
    _fill_then_free(engine)

    blocker = sqlite3.connect(str(path), isolation_level=None)
    try:
        blocker.execute("BEGIN")
        blocker.execute("SELECT count(*) FROM t").fetchone()
        report = maybe_incremental_vacuum(engine)
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()

    assert report == {"skipped": "error"}, report


def test_a_store_not_in_incremental_mode_still_takes_the_existing_honest_branch(tmp_path):
    """The pre-existing refusal must be untouched: a store the pragma cannot help says
    so by NAME, and never produces a shortfall block about a run that never happened."""
    engine, _ = _store(tmp_path, auto_vacuum="NONE")
    report = maybe_incremental_vacuum(engine)
    assert report["skipped"] == "not-incremental-mode"
    assert report["auto_vacuum"] == 0
    assert "residual" not in report
