"""VACUUM needs room for a second copy of the database, and nothing checked.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

DB-10 §2 carry-over, recorded in ``docs/ledger/OPEN_QUEUE.md``: the frontend's
``_confirmVacuum`` discloses an estimated DURATION and confirms, but
``POST /api/database/vacuum`` would start a full rebuild on a corpus of any size
with no disk check at all. SQLite's VACUUM writes a COMPLETE second copy of the
file and only then swaps it in, so the peak requirement is about twice the
current size — and running out of space mid-rebuild is the worst possible moment
to discover it.

THREE THINGS THIS PINS, each of which is a way the check could be wrong rather
than absent.

1. THE DATABASE'S VOLUME AND THE MEMORY ARE MEASURED, AND THE TEMPORARY VOLUME IS
   NOT. Every pooled connection of the app sets ``temp_store=MEMORY``, so the
   rebuilt copy is held in RAM and nothing is written to ``/tmp``: a refusal for a
   small ``/tmp`` pointed the operator at a volume the rebuild never touches, and
   a machine with too little MEMORY for the copy was waved through (the rollup's
   in-memory build is what brought the 4.81 GiB machines down). The copy is not
   moved to a file to avoid the question: at the app's 16 KiB page size a VACUUM
   with ``temp_store=FILE`` wrote a CORRUPT encrypted store (the deep read of the
   index build), so the cost is memory and memory is what is gated.

2. AN UNREADABLE FIGURE IS NOT A REFUSAL. ``shutil.disk_usage`` can raise, and a
   fabricated 0 would manufacture a refusal out of an unreadable ``statvfs``.
   ``sufficient`` is then ``None`` and the vacuum PROCEEDS, with the response
   saying it was not preflighted — the same three-state discipline
   ``weights_pin`` uses when it omits a comparison nothing compared, and the
   same one ``vllm_lifecycle._free_disk_bytes`` already draws.

3. THE REFUSAL HAS ITS OWN STATUS. 507 for "the disk cannot hold this", kept
   distinct from the existing 409 "something else is writing". Collapsing two
   different refusals into one status is how an operator comes to fix the wrong
   thing.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from src.database import article_indexes
from src.database.maintenance import (
    VACUUM_HEADROOM,
    VACUUM_RAM_FACTOR,
    VacuumSpaceError,
    vacuum_database,
    vacuum_preflight,
)
from tests.js_source_helper import python_function_source


@pytest.fixture(autouse=True)
def plenty_of_memory(monkeypatch):
    """A machine with room, so the tests of the DISK half are not at the mercy of the one that runs them; the memory tests
    below set their own figures through the same two readers the index build uses."""
    monkeypatch.setattr(article_indexes, "_available_ram_bytes", lambda: 10**12)
    monkeypatch.setattr(article_indexes, "_floor_bytes", lambda: 0)


@pytest.fixture
def sqlite_engine(tmp_path):
    from sqlalchemy import create_engine, text

    db = tmp_path / "store.db"
    engine = create_engine(f"sqlite:///{db}")
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, blob TEXT)"))
        conn.execute(text("INSERT INTO t (blob) SELECT hex(randomblob(400))"))
    return engine


def test_the_preflight_measures_twice_the_file_on_the_database_volume_and_the_memory_the_copy_is_held_in(sqlite_engine) -> None:
    report = vacuum_preflight(sqlite_engine)
    assert report["checked"] is True
    assert report["sufficient"] is True, report
    assert report["db_bytes"] > 0
    assert report["needed_bytes"] == int(report["db_bytes"] * VACUUM_HEADROOM)
    assert set(report["free_bytes"]) == {"database"}, "the rebuild is held in memory: no temporary volume is written"
    assert report["ram_estimate_bytes"] == int(report["db_bytes"] * VACUUM_RAM_FACTOR)
    assert report["ram_factor"] == VACUUM_RAM_FACTOR == 1.25, "a figure changed: update the words that quote it"


def test_a_measured_shortfall_refuses_before_taking_the_write_lock(
    sqlite_engine, monkeypatch
) -> None:
    """And it refuses BEFORE the exclusive lock, so nobody loses their writer to a
    vacuum that was never going to fit."""
    real = shutil.disk_usage

    def _tiny(path):
        got = real(path)
        return type(got)(got.total, got.used, 1)  # one byte free

    monkeypatch.setattr(shutil, "disk_usage", _tiny)
    report = vacuum_preflight(sqlite_engine)
    assert report["sufficient"] is False
    assert report["short_on"], report
    assert "needs about" in report["detail"]

    took_the_lock = []
    import src.database.writer as writer

    real_lock = writer.write_lock

    def _watched(*a, **k):
        took_the_lock.append(True)
        return real_lock(*a, **k)

    monkeypatch.setattr(writer, "write_lock", _watched)
    with pytest.raises(VacuumSpaceError) as excinfo:
        vacuum_database(sqlite_engine)
    assert excinfo.value.report["sufficient"] is False
    assert not took_the_lock, (
        "the refusal must come before the exclusive write lock; refusing after it "
        "would stall every other writer for a vacuum that never ran"
    )


def test_a_full_temporary_volume_is_not_a_refusal_because_nothing_is_written_there(sqlite_engine, monkeypatch) -> None:
    """The deep read's S2: the old check measured ``tempfile.gettempdir()`` for a rebuild the pooled ``temp_store=MEMORY``
    never writes, and told the operator to move the temporary directory, which cures nothing."""
    import tempfile

    real = shutil.disk_usage
    tmpdir = os.path.realpath(tempfile.gettempdir())
    asked: list[str] = []

    def _tmp_is_full(path):
        asked.append(os.path.realpath(str(path)))
        got = real(path)
        if os.path.realpath(str(path)) == tmpdir and os.path.realpath(str(path)) != os.path.realpath(os.path.dirname(str(sqlite_engine.url.database))):
            return type(got)(got.total, got.used, 1)
        return got

    monkeypatch.setattr(shutil, "disk_usage", _tmp_is_full)
    report = vacuum_preflight(sqlite_engine)
    assert report["sufficient"] is True, report
    assert "short_on" not in report
    assert "temporary directory" not in report["detail"]
    assert set(asked) == {os.path.realpath(os.path.dirname(str(sqlite_engine.url.database)))}, asked


def _memory(monkeypatch, available, floor=0):
    monkeypatch.setattr(article_indexes, "_available_ram_bytes", lambda: available)
    monkeypatch.setattr(article_indexes, "_floor_bytes", lambda: floor)


def test_the_memory_asked_is_the_files_size_times_the_factor_plus_the_guards_floor_and_the_boundary_is_exact(
    sqlite_engine, monkeypatch
) -> None:
    """The coordinator's gate: the MEMORY VACUUM's copy holds the whole file in RAM, so it is refused when the machine cannot
    hold it and the memory guard's floor, with the reason and the numbers, and passes at exactly the figure."""
    db_bytes = vacuum_preflight(sqlite_engine)["db_bytes"]
    need = int(db_bytes * VACUUM_RAM_FACTOR) + 7_000
    _memory(monkeypatch, need, floor=7_000)
    ok = vacuum_preflight(sqlite_engine)
    assert ok["sufficient"] is True and "short_on" not in ok, ok
    assert ok["ram_floor_bytes"] == 7_000 and ok["ram_available_bytes"] == need
    _memory(monkeypatch, need - 1, floor=7_000)
    short = vacuum_preflight(sqlite_engine)
    assert short["sufficient"] is False and short["short_on"] == ["memory"], short
    assert f"{need - 1:,} bytes of memory available" in short["detail"]
    assert f"{int(db_bytes * VACUUM_RAM_FACTOR):,}" in short["detail"] and "7,000" in short["detail"]
    assert "temporary file corrupts an encrypted file" in short["detail"], "the reason the copy is not moved to a file is not said"
    # the floor alone is enough to refuse: it is not an extra the estimate swallows
    _memory(monkeypatch, int(db_bytes * VACUUM_RAM_FACTOR) + 6_999, floor=7_000)
    assert vacuum_preflight(sqlite_engine)["short_on"] == ["memory"]


def test_a_memory_shortfall_is_refused_before_the_write_lock_and_the_refusal_is_logged(sqlite_engine, monkeypatch, caplog) -> None:
    import logging

    _memory(monkeypatch, 1)
    took_the_lock = []
    import src.database.writer as writer

    real_lock = writer.write_lock
    monkeypatch.setattr(writer, "write_lock", lambda *a, **k: (took_the_lock.append(True), real_lock(*a, **k))[1])
    with caplog.at_level(logging.WARNING, logger="src.database.maintenance"), pytest.raises(VacuumSpaceError) as excinfo:
        vacuum_database(sqlite_engine)
    assert excinfo.value.report["short_on"] == ["memory"]
    assert not took_the_lock, "a refusal after the exclusive lock would stall every writer for a vacuum that never ran"
    assert any("compaction not run" in r.getMessage() and "memory available" in r.getMessage() for r in caplog.records), caplog.text


def test_when_the_disk_and_the_memory_both_fall_short_the_detail_says_both(sqlite_engine, monkeypatch) -> None:
    real = shutil.disk_usage
    monkeypatch.setattr(shutil, "disk_usage", lambda path: type(real(path))(real(path).total, real(path).used, 1))
    _memory(monkeypatch, 1)
    report = vacuum_preflight(sqlite_engine)
    assert report["short_on"] == ["database", "memory"], report
    assert "volume has 1 bytes free" in report["detail"] and "bytes of memory available" in report["detail"]


def test_an_unreadable_memory_figure_is_not_a_refusal_and_neither_is_an_unreadable_disk_figure(sqlite_engine, monkeypatch) -> None:
    _memory(monkeypatch, None)
    assert vacuum_preflight(sqlite_engine)["sufficient"] is True, "no reading of the memory must not manufacture a refusal"

    def _boom(path):
        raise OSError("statvfs is unavailable here")

    monkeypatch.setattr(shutil, "disk_usage", _boom)
    _memory(monkeypatch, 10**12)
    report = vacuum_preflight(sqlite_engine)
    assert report["sufficient"] is True and report["checked"] is True, "the memory WAS measured, and it is enough"
    _memory(monkeypatch, 1)
    assert vacuum_preflight(sqlite_engine)["short_on"] == ["memory"], "an unreadable disk does not excuse a measured memory shortfall"


def test_an_unreadable_volume_is_not_a_refusal(sqlite_engine, monkeypatch) -> None:
    """A fabricated 0 would manufacture a refusal out of an unreadable statvfs."""
    def _boom(path):
        raise OSError("statvfs is unavailable here")

    monkeypatch.setattr(shutil, "disk_usage", _boom)
    _memory(monkeypatch, None)  # and neither figure could be read
    report = vacuum_preflight(sqlite_engine)
    assert report["sufficient"] is None, report
    assert report["checked"] is False
    assert "not preflighted" in report["detail"]
    # And the vacuum still runs -- being unable to measure is not being unable to act.
    out = vacuum_database(sqlite_engine)
    assert out["supported"] is True
    assert out["preflight"]["sufficient"] is None


def test_a_successful_vacuum_carries_its_preflight(sqlite_engine) -> None:
    """So an operator can see the check happened -- and, when it could not, that
    it did not."""
    out = vacuum_database(sqlite_engine)
    assert out["supported"] is True
    assert out["preflight"]["sufficient"] is True
    assert "twice the file size" in out["method"]


def test_the_endpoint_maps_the_shortfall_to_its_own_status() -> None:
    """507, not the 409 that already means 'something else is writing'."""
    src = (Path(__file__).resolve().parents[1] / "src" / "api" / "database.py").read_text(
        encoding="utf-8"
    )
    # Parser-bounded, not delimiter-guessed: the first draft sliced from
    # ``def vacuum()`` to a ``served_cache.invalidate()`` that happens to sit inside
    # it today, which is the shape ``tests/test_source_slicing_discipline.py`` exists
    # to keep out -- pick a delimiter that moves and the "body" silently becomes the
    # rest of the module, satisfied by any other function in the file.
    block = python_function_source(src, "vacuum")
    assert "VacuumSpaceError" in block, "the endpoint must handle the space refusal"
    assert "status_code=507" in block, (
        "a disk shortfall needs its own status; 409 already means the store is busy"
    )
    assert "status_code=409" in block, "the busy refusal must not have been replaced"


def test_a_volume_holding_the_file_but_not_its_copy_is_still_refused(
    sqlite_engine, monkeypatch
) -> None:
    """The headroom is the load-bearing number, and asserting
    ``needed == db_bytes * VACUUM_HEADROOM`` pins nothing -- it is true for any
    value of the constant, including 1.0, which is the value that says "the
    rebuild needs no room of its own". Dropping the constant to 1.0 passed every
    other test in this file.

    So the claim is made behaviourally: a volume with room for the FILE but not
    for the SECOND COPY must be refused. That is exactly the disk on which the
    old, unchecked VACUUM would have failed halfway through.
    """
    real = shutil.disk_usage
    db_bytes = vacuum_preflight(sqlite_engine)["db_bytes"]

    def _just_over_one_copy(path):
        got = real(path)
        return type(got)(got.total, got.used, int(db_bytes * 1.2))

    monkeypatch.setattr(shutil, "disk_usage", _just_over_one_copy)
    report = vacuum_preflight(sqlite_engine)
    assert report["sufficient"] is False, (
        "1.2x the file is room for the file and not for the copy VACUUM writes "
        f"beside it; the preflight accepted it: {report}"
    )
    assert VACUUM_HEADROOM >= 2.0, (
        "VACUUM rebuilds into a complete second copy before swapping, so 2.0x is "
        f"the floor of the requirement, not a margin on top of it (found {VACUUM_HEADROOM})"
    )


def test_ample_space_is_still_accepted(sqlite_engine, monkeypatch) -> None:
    """The other half of the pair: a headroom raised until nothing ever passes
    would satisfy the refusal test above while breaking every real vacuum."""
    real = shutil.disk_usage
    db_bytes = vacuum_preflight(sqlite_engine)["db_bytes"]

    def _three_copies(path):
        got = real(path)
        return type(got)(got.total, got.used, int(db_bytes * 3) + 4096)

    monkeypatch.setattr(shutil, "disk_usage", _three_copies)
    assert vacuum_preflight(sqlite_engine)["sufficient"] is True
