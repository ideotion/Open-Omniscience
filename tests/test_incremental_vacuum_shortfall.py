"""Incremental vacuum says so when it could not reclaim (C3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field diagnostics 2026-09-11. The off-peak incremental vacuum reported
``freelist_pages_before 141679`` -> ``after 141678`` against ``requested_pages 2000``:
ONE page reclaimed of two thousand, with about 2.22 GB still stranded in a 27.7 GB
database -- and said nothing about it. A run that reclaims 1 page of 2000 is not a
successful run, and reporting only the bare number lets it read as one.

NOT THE USUAL EXPLANATION. The obvious cause is a store created at ``auto_vacuum=NONE``
whose pragma was flipped later -- a no-op without a full VACUUM, because the pointer-map
pages do not exist -- but such a store reports mode 0 and takes the existing
``not-incremental-mode`` branch. The field store reported 2, so the pragma was live and
the pages genuinely did not move.

What this pins is therefore the HONESTY, not a cause: the observation is reported, the
checkable candidates are named, and no mechanism is asserted that was never established.
The repo's rule is that a measurement which could not be taken is absent with a reason,
never dressed up as a result.
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
    assert "reclaim_shortfall" not in report
    assert report["pages_reclaimed"] > 0
    # Worth recording what this fixture actually showed: even in INCREMENTAL mode with
    # no long-lived reader, `incremental_vacuum` did NOT drain the freelist completely
    # (a few hundred pages survived a 100,000-page request). That is a real, local
    # reproduction of the shape the field saw in the extreme -- and exactly why the
    # shortfall condition is "we asked for N, got fewer, and MORE than N are still
    # free" rather than the naive "anything left over", which would cry wolf here.
    assert report["freelist_pages_after"] < report["freelist_pages_before"]
    assert report["freelist_pages_after"] <= report["requested_pages"]


def test_a_partial_reclaim_says_so_with_its_numbers_and_candidates(tmp_path, monkeypatch):
    """THE FIELD SHAPE: far more pages remain free than were reclaimed. The report must
    state the shortfall rather than presenting `pages_reclaimed` as a result."""
    monkeypatch.setenv("OO_INCREMENTAL_VACUUM_PAGES", "5")
    engine, _ = _store(tmp_path, auto_vacuum="INCREMENTAL")
    _fill_then_free(engine)

    report = maybe_incremental_vacuum(engine)

    assert "skipped" not in report, report
    short = report.get("reclaim_shortfall")
    assert short is not None, (
        f"a run that left {report.get('freelist_pages_after')} pages free after asking "
        f"for {report.get('requested_pages')} reported no shortfall: {report}"
    )
    assert short["requested"] == 5
    assert short["still_free_pages"] == report["freelist_pages_after"]
    assert short["still_free_bytes"] == report["freelist_pages_after"] * report["page_size"]
    assert "did NOT reclaim" in short["detail"]

    # The candidates must be CHECKABLE pointers, not a shrug -- and the reader-snapshot
    # one is named first because the same bundle measured a 17.4-hour reader (C1).
    assert len(short["candidates"]) >= 2
    assert any("reader" in c for c in short["candidates"])
    assert any("full VACUUM" in c for c in short["candidates"])

    # A full VACUUM is offered with its real cost, and explicitly NOT run automatically.
    note = short["full_vacuum_note"]
    assert "blocks writes" in note and "free disk" in note
    assert "operator's button" in note


def test_a_store_not_in_incremental_mode_still_takes_the_existing_honest_branch(tmp_path):
    """The pre-existing refusal must be untouched: a store the pragma cannot help says
    so by NAME, and never produces a shortfall block about a run that never happened."""
    engine, _ = _store(tmp_path, auto_vacuum="NONE")
    report = maybe_incremental_vacuum(engine)
    assert report["skipped"] == "not-incremental-mode"
    assert report["auto_vacuum"] == 0
    assert "reclaim_shortfall" not in report
