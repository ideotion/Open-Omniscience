"""What a vacuum reports about the space it freed and the space the disk got back (C3, R785).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field diagnostics 2026-09-11. The off-peak pass reported ``freelist_pages_before
141679`` -> ``after 141678`` against ``requested_pages 2000``: ONE page of two thousand,
with about 2.22 GB stranded in a 27.7 GB database -- and said nothing about it. The pragma
was never stepped past its first page (SQLAlchemy finalises a cursor it believes returns no
rows); the drain fixed that, and a RESIDUAL after a full-budget pass is a budget statement,
not a fault.

R785 (2026-11-22). Those measurements were taken on stores WITHOUT a write-ahead log, and
the app's stores all use one. Measured again on the app's own engine settings, plain and
encrypted:

  * ``incremental_vacuum`` frees every page it is asked to whether or not a reader holds a
    snapshot (on a rollback journal that reader made it raise ``database is locked``);
  * the pages are freed IN THE LOG: the database file keeps its size until a checkpoint
    copies the log back, so straight after a pass the disk has usually seen none of it;
  * a full VACUUM writes the rebuilt database through the log: with no other reader the
    automatic checkpoint shrinks the FILE at once while the log keeps the bytes, and with a
    reader holding an older view the file does not shrink and the log is added on top.

So freed is not reclaimed. These tests pin that ``bytes_reclaimed`` is the measured fall in
the file plus its log and nothing else, that space freed inside the database but not yet
given back is reported as exactly that with its reason, and that the pass never forces a
checkpoint to make the number look better.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.pool import QueuePool

from src.database import connect as connect_mod
from src.database.maintenance import maybe_incremental_vacuum, vacuum_database
from tests._app_engine import app_sqlite_engine

_KEY = "a throwaway passphrase for the vacuum accounting test"


def _on_disk(path) -> int:
    wal = f"{path}-wal"
    return os.path.getsize(path) + (os.path.getsize(wal) if os.path.exists(wal) else 0)


@pytest.fixture(params=["plain", "encrypted"])
def leg(request, monkeypatch):
    """Every engine leg the app runs: a plain store and an encrypted one, both opened with the app's pragmas
    (WAL, foreign keys, busy timeout, journal size limit)."""
    if request.param == "encrypted":
        pytest.importorskip("sqlcipher3")
        monkeypatch.setattr(connect_mod, "_passphrase", _KEY)  # what the app holds once it is unlocked
    return request.param


def _store(tmp_path, leg, *, auto_vacuum: str, rows: int = 4000, keep: int = 0):
    """A real on-disk store with a large freelist: ``rows`` rows written, all but the first ``keep`` deleted
    (a contiguous tail, so whole pages empty), the log checkpointed so the measurement starts clean."""
    path = tmp_path / "store.db"
    key = _KEY if leg == "encrypted" else None
    seed = connect_mod.connect(path, key=key, create_encrypted=leg == "encrypted", check_same_thread=False)
    seed.execute(f"PRAGMA auto_vacuum={auto_vacuum}")
    seed.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, blob TEXT)")
    seed.commit()
    seed.execute("VACUUM")  # makes the auto_vacuum mode take effect
    seed.close()
    assert connect_mod.is_encrypted_file(path) is (leg == "encrypted")
    engine = app_sqlite_engine(
        path,
        creator=lambda: connect_mod.connect(path, check_same_thread=False),
        poolclass=QueuePool,
        pool_size=4,
        max_overflow=0,
    )
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        assert c.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        c.execute(
            text("INSERT INTO t (blob) SELECT hex(randomblob(200)) FROM (WITH RECURSIVE n(i) AS "
                 "(SELECT 1 UNION ALL SELECT i+1 FROM n WHERE i < :rows) SELECT i FROM n)"),
            {"rows": rows},
        )
        c.execute(text("DELETE FROM t WHERE id > :keep"), {"keep": keep})
        c.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
    return engine, path


def _reader(path):
    """A second connection holding a read snapshot, the way a long report or an export does."""
    conn = connect_mod.connect(path, check_same_thread=False)
    conn.isolation_level = None
    conn.execute("BEGIN")
    conn.execute("SELECT count(*) FROM t").fetchone()
    return conn


@pytest.fixture(autouse=True)
def _fresh_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)


def _assert_reclaimed_is_measured(report, before: int, after: int) -> None:
    """The one rule: reclaimed is the measured fall in file plus log, never a page count."""
    assert report["on_disk_before"]["total_bytes"] == before
    assert report["on_disk_after"]["total_bytes"] == after
    assert report["bytes_reclaimed"] == max(before - after, 0)
    for side in ("on_disk_before", "on_disk_after"):
        d = report[side]
        assert d["total_bytes"] == d["file_bytes"] + d["log_bytes"]


def _assert_freed_not_shrunk_is_named(report) -> None:
    gap = report["bytes_freed_in_database"] - report["bytes_reclaimed"]
    assert gap > 0, report
    pending = report["freed_not_yet_shrunk"]
    assert pending["bytes"] == gap
    assert f"{gap:,} bytes are freed inside the database but not yet returned to the disk" in pending["detail"]
    # the reason, for the log the app actually runs on, and the promise not to force it
    assert "write-ahead log" in pending["detail"] and "checkpoint" in pending["detail"]
    assert "does not force a checkpoint" in pending["detail"]


# --------------------------------------------------------------------------- #
# incremental vacuum (the scheduler's idle pass)
# --------------------------------------------------------------------------- #
def test_a_healthy_pass_frees_every_page_and_does_not_call_them_reclaimed(tmp_path, monkeypatch, leg):
    """An unobstructed pass with a budget larger than the freelist drains it to zero -- and the disk has
    still seen none of it, because the file shrinks only at a later checkpoint. Calling the freed pages
    "reclaimed" there was the R785 defect."""
    monkeypatch.setenv("OO_INCREMENTAL_VACUUM_PAGES", "100000")
    engine, path = _store(tmp_path, leg, auto_vacuum="INCREMENTAL")
    before = _on_disk(path)

    report = maybe_incremental_vacuum(engine)
    after = _on_disk(path)
    engine.dispose()

    assert "skipped" not in report, report
    assert report["journal_mode"] == "wal"
    assert report["pages_freed"] > 0 and report["freelist_pages_after"] == 0
    assert "residual" not in report  # a healthy run carries no shortfall noise
    assert "pages_reclaimed" not in report  # the freelist's fall is not called reclaimed any more
    assert report["bytes_freed_in_database"] == report["pages_freed"] * report["page_size"]
    _assert_reclaimed_is_measured(report, before, after)
    _assert_freed_not_shrunk_is_named(report)


def test_a_reader_does_not_stop_the_pass_on_a_wal_store_it_holds_back_the_shrink(tmp_path, monkeypatch, leg):
    """The rollback-journal measurement this file used to pin (a reader makes the pragma raise) does not
    hold on the app's stores. On WAL the pass frees every page with a reader holding a snapshot, and what the
    reader holds back is the checkpoint: the file does not shrink while it is there, even when a checkpoint
    is asked for, and does once it has gone."""
    monkeypatch.setenv("OO_INCREMENTAL_VACUUM_PAGES", "100000")
    engine, path = _store(tmp_path, leg, auto_vacuum="INCREMENTAL")
    before = _on_disk(path)
    file_before = os.path.getsize(path)

    reader = _reader(path)
    try:
        report = maybe_incremental_vacuum(engine)
        after = _on_disk(path)
        # A checkpoint asked for while the reader holds its older view (the test asks; the pass never does):
        # it cannot copy the freeing frames back, so the file keeps its size.
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.execute(text("PRAGMA wal_checkpoint(PASSIVE)")).fetchall()
        assert os.path.getsize(path) == file_before
    finally:
        reader.execute("ROLLBACK")
        reader.close()

    assert "skipped" not in report, report  # no `database is locked`: that was the rollback journal
    assert report["freelist_pages_after"] == 0
    _assert_reclaimed_is_measured(report, before, after)
    _assert_freed_not_shrunk_is_named(report)

    # The reader gone, the same checkpoint copies the log back and the file shrinks by what was freed.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.execute(text("PRAGMA wal_checkpoint(TRUNCATE)")).fetchall()
    engine.dispose()
    assert file_before - os.path.getsize(path) >= report["bytes_freed_in_database"]


def test_the_pass_never_forces_a_checkpoint(tmp_path, monkeypatch, leg):
    """The number would look better after a forced checkpoint; R785 forbids buying it that way. The file is
    exactly the size it was before the pass: nothing copied the log back."""
    monkeypatch.setenv("OO_INCREMENTAL_VACUUM_PAGES", "100000")
    engine, path = _store(tmp_path, leg, auto_vacuum="INCREMENTAL")
    file_before = os.path.getsize(path)
    report = maybe_incremental_vacuum(engine)
    assert os.path.getsize(path) == file_before
    assert report["on_disk_after"]["file_bytes"] == file_before
    engine.dispose()


def test_a_budget_bound_run_names_its_residual_without_crying_wolf(tmp_path, monkeypatch, leg):
    """A pass that spends its whole allowance and leaves pages free is the design working -- bounded work
    in an idle window -- but the operator still needs to know the pages are there."""
    monkeypatch.setenv("OO_INCREMENTAL_VACUUM_PAGES", "5")
    engine, path = _store(tmp_path, leg, auto_vacuum="INCREMENTAL")
    before = _on_disk(path)

    report = maybe_incremental_vacuum(engine)
    after = _on_disk(path)
    engine.dispose()

    assert "skipped" not in report, report
    assert report["pages_freed"] == 5  # the drain means the budget is honoured exactly
    res = report["residual"]
    assert res["budget_bound"] is True and res["freed"] == 5
    assert res["still_free_pages"] == report["freelist_pages_after"]
    assert res["still_free_bytes"] == report["freelist_pages_after"] * report["page_size"]
    # a budget statement, not a fault: no invented cause, and the knob that changes it is named
    assert "The per-pass budget was the limit, not the store" in res["detail"]
    assert "OO_INCREMENTAL_VACUUM_PAGES" in res["detail"]
    assert "reader" not in res["detail"], "a healthy budget-bound run must not blame a reader"
    note = res["full_vacuum_note"]
    assert "blocks writes" in note and "free disk" in note and "operator's button" in note
    _assert_reclaimed_is_measured(report, before, after)


def test_a_store_not_in_incremental_mode_still_takes_the_existing_honest_branch(tmp_path, leg):
    """A store the pragma cannot help says so by NAME, and never produces an account of a run that never
    happened."""
    engine, _ = _store(tmp_path, leg, auto_vacuum="NONE")
    report = maybe_incremental_vacuum(engine)
    engine.dispose()
    assert report == {"skipped": "not-incremental-mode", "auto_vacuum": 0}


# --------------------------------------------------------------------------- #
# full VACUUM (the Settings button, whose "Space freed" the operator reads)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("with_reader", [False, True], ids=["no-reader", "reader-held"])
def test_a_full_vacuum_reports_the_disks_gain_not_the_files(tmp_path, leg, with_reader):
    """Half the rows kept so the rebuilt database is large: its pages go through the log. Without a reader
    the file shrinks once the log crosses the automatic checkpoint, and the log holds the bytes; with one
    the file does not shrink and the log is added on top. Either way the file-only fall this used to report as reclaimed is not what the disk got."""
    engine, path = _store(tmp_path, leg, auto_vacuum="NONE", rows=20000, keep=10000)
    before = _on_disk(path)
    file_before = os.path.getsize(path)

    reader = _reader(path) if with_reader else None
    try:
        report = vacuum_database(engine)
        after = _on_disk(path)
        file_after = os.path.getsize(path)
    finally:
        if reader is not None:
            reader.execute("ROLLBACK")
            reader.close()
    engine.dispose()

    assert report["supported"] is True
    assert report["journal_mode"] == "wal"
    assert report["bytes_before"] == before and report["bytes_after"] == after
    assert report["bytes_freed_in_database"] == (
        (report["database_pages_before"] - report["database_pages_after"]) * report["page_size"]
    ) > 0
    _assert_reclaimed_is_measured(report, before, after)
    if with_reader:
        assert file_after == file_before  # the reader held the checkpoint back
    else:
        # Whether the file shrinks during the pass depends on whether the log crossed the automatic
        # checkpoint threshold (1000 pages): measured, the plain leg (4 KiB pages) crosses it and the file
        # shrinks; the encrypted leg (16 KiB pages) does not and the file keeps its size. Either way the
        # file never grows, and a fall in the file alone is never what the disk got back.
        assert file_after <= file_before
        if file_after < file_before:
            assert report["bytes_reclaimed"] < file_before - file_after
    _assert_freed_not_shrunk_is_named(report)


def test_space_that_cannot_be_measured_is_never_called_reclaimed(monkeypatch, tmp_path):
    """A size that cannot be read is not a size of zero: the account says nothing was measured."""
    from src.database import maintenance

    def _unreadable(_p):
        raise PermissionError("not allowed")

    monkeypatch.setattr(maintenance.os.path, "getsize", _unreadable)
    disk = maintenance._on_disk_bytes(str(tmp_path / "x.db"))
    assert disk == {"file_bytes": None, "log_bytes": None, "total_bytes": None}
    acc = maintenance._space_account(disk, disk, freed_bytes=4096, journal_mode="wal")
    assert acc["bytes_reclaimed"] is None
    assert "could not be read, so none of it is called reclaimed" in acc["freed_not_yet_shrunk"]["detail"]
