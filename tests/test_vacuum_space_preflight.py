"""VACUUM needs room for a second copy of the database, and nothing checked.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

DB-10 §2 carry-over, recorded in ``docs/ledger/OPEN_QUEUE.md``: the frontend's
``_confirmVacuum`` discloses an estimated DURATION and confirms, but
``POST /api/database/vacuum`` would start a full rebuild on a corpus of any size
with no disk check at all. SQLite's VACUUM writes a COMPLETE second copy of the
file's live pages and only then swaps them in, so the peak requirement is about twice the
pages in use, plus the log — and running out of space mid-rebuild is the worst possible moment
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

import json
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


def test_the_preflight_measures_twice_the_pages_in_use_on_the_database_volume_and_the_memory_the_copy_is_held_in(sqlite_engine) -> None:
    report = vacuum_preflight(sqlite_engine)
    assert report["checked"] is True
    assert report["sufficient"] is True, report
    assert report["db_bytes"] > 0
    # a store with no free pages and no log: what VACUUM copies is the file
    assert report["copy_bytes_read"] is True and report["copy_bytes"] == report["db_bytes"] and report["wal_bytes"] == 0
    assert report["needed_bytes"] == int(report["copy_bytes"] * VACUUM_HEADROOM) + report["wal_bytes"]
    assert set(report["free_bytes"]) == {"database"}, "the rebuild is held in memory: no temporary volume is written"
    assert report["ram_estimate_bytes"] == int(report["copy_bytes"] * VACUUM_RAM_FACTOR)
    assert report["ram_factor"] == VACUUM_RAM_FACTOR == 1.25, "a figure changed: update the words that quote it"
    assert report["not_read"] == [] and report["detail"] == "enough free space and memory for this VACUUM"


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


def test_the_memory_asked_is_the_pages_in_use_times_the_factor_plus_the_guards_floor_and_the_boundary_is_exact(
    sqlite_engine, monkeypatch
) -> None:
    """The coordinator's gate: the MEMORY VACUUM's copy holds the pages in use in RAM, so it is refused when the machine cannot
    hold it and the memory guard's floor, with the reason and the numbers, and passes at exactly the figure."""
    copy_bytes = vacuum_preflight(sqlite_engine)["copy_bytes"]
    need = int(copy_bytes * VACUUM_RAM_FACTOR) + 7_000
    _memory(monkeypatch, need, floor=7_000)
    ok = vacuum_preflight(sqlite_engine)
    assert ok["sufficient"] is True and "short_on" not in ok, ok
    assert ok["ram_floor_bytes"] == 7_000 and ok["ram_available_bytes"] == need
    _memory(monkeypatch, need - 1, floor=7_000)
    short = vacuum_preflight(sqlite_engine)
    assert short["sufficient"] is False and short["short_on"] == ["memory"], short
    assert f"{need - 1:,} bytes of memory available" in short["detail"]
    assert f"{int(copy_bytes * VACUUM_RAM_FACTOR):,}" in short["detail"] and "7,000" in short["detail"]
    assert "would corrupt an encrypted library at the app's page size" in short["detail"], "the reason the copy is not moved to a file is not said"
    assert "every connection of the app keeps its temporary data there" in short["detail"], "the reason must hold for a plaintext store too"
    # the floor alone is enough to refuse: it is not an extra the estimate swallows
    _memory(monkeypatch, int(copy_bytes * VACUUM_RAM_FACTOR) + 6_999, floor=7_000)
    assert vacuum_preflight(sqlite_engine)["short_on"] == ["memory"]


def test_a_memory_shortfall_is_refused_before_the_write_lock_and_the_refusal_is_logged(sqlite_engine, monkeypatch, caplog) -> None:
    import logging

    _memory(monkeypatch, 1)
    took_the_lock = []
    import src.database.writer as writer

    real_lock = writer.write_lock
    monkeypatch.setattr(writer, "write_lock", lambda *a, **k: (took_the_lock.append(True), real_lock(*a, **k))[1])
    with caplog.at_level(logging.WARNING, logger="database.maintenance"), pytest.raises(VacuumSpaceError) as excinfo:
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
    assert report["not_read"] == [] and "Not checked" not in report["detail"], "both were read: nothing is said to be unread"


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
    assert "twice the pages in use plus the log" in out["method"]


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
    ``needed == copy_bytes * VACUUM_HEADROOM`` pins nothing -- it is true for any
    value of the constant, including 1.0, which is the value that says "the
    rebuild needs no room of its own". Dropping the constant to 1.0 passed every
    other test in this file.

    So the claim is made behaviourally: a volume with room for the FILE but not
    for the SECOND COPY must be refused (here the file is all pages in use, so its size is the copy). That is exactly the disk on
    which the old, unchecked VACUUM would have failed halfway through.
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
        "what VACUUM writes back is the live bytes, once through the log and once into the file at the swap, and the measured "
        f"growth was one copy: 2.0x the pages in use is twice that, a margin and not a floor (found {VACUUM_HEADROOM})"
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


# --------------------------------------------------------------------------- #
#  the copy is sized from what VACUUM copies, not from the file on disk
# --------------------------------------------------------------------------- #
def _engine_with_rows(path, *, wal: bool, rows: int, keep: int | None = None, page_size: int = 4096):
    """A store of ``rows`` one-kilobyte rows. ``wal``: in WAL mode with the automatic checkpoint off, so the rows stay in the
    log (the file on disk is a few pages) and the pooled connection keeps it from being folded away. ``keep``: rows kept after
    a delete, which leaves the file as large as it was and most of its pages free. ``page_size``: the file's page size (the app's
    encrypted stores use 16 KiB), set before anything is written."""
    from sqlalchemy import create_engine, event, text

    engine = create_engine(f"sqlite:///{path}")

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi, _record):
        cur = dbapi.cursor()
        cur.execute(f"PRAGMA page_size={int(page_size)}")
        if wal:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA wal_autocheckpoint=0")
        cur.close()

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, blob TEXT)"))
        conn.execute(text(
            "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < :n) "
            "INSERT INTO t (blob) SELECT hex(randomblob(500)) FROM n"
        ), {"n": rows})
        if keep is not None:
            conn.execute(text("DELETE FROM t WHERE id > :k"), {"k": keep})
    return engine


def _page(engine) -> int:
    from sqlalchemy import text

    with engine.connect() as conn:
        return int(conn.execute(text("PRAGMA page_size")).scalar())


def test_pages_still_only_in_the_log_are_part_of_the_copy_and_the_logs_size_is_added_to_the_disk_figure(tmp_path, monkeypatch) -> None:
    """Measured: ``PRAGMA page_count`` on a connection includes the pages that are only in the write-ahead log, which the file's
    size on disk does not. The first version sized everything from the file, so a log that held most of the store asked for a
    few pages of memory (a lag of more than about a fifth under-asked)."""
    engine = _engine_with_rows(tmp_path / "wal.db", wal=True, rows=3000)
    report = vacuum_preflight(engine)
    assert report["wal_bytes"] > 2_000_000, report
    assert report["db_bytes"] < report["wal_bytes"] / 20, "the file on disk is not where the rows are"
    assert report["copy_bytes_read"] is True and report["copy_bytes"] > 10 * report["db_bytes"], report
    assert report["needed_bytes"] == int(report["copy_bytes"] * VACUUM_HEADROOM) + report["wal_bytes"], "the log's own size is added"
    assert report["ram_estimate_bytes"] == int(report["copy_bytes"] * VACUUM_RAM_FACTOR)
    real = shutil.disk_usage
    for free, ok in ((report["needed_bytes"], True), (report["needed_bytes"] - 1, False)):
        monkeypatch.setattr(shutil, "disk_usage", lambda path, free=free: type(real(path))(real(path).total, real(path).used, free))
        assert vacuum_preflight(engine)["sufficient"] is ok, ("the disk boundary is exact", free)
    monkeypatch.setattr(shutil, "disk_usage", real)
    _memory(monkeypatch, int(report["copy_bytes"] * VACUUM_RAM_FACTOR) - 1)
    assert vacuum_preflight(engine)["short_on"] == ["memory"], "a file-sized memory figure would have let this through"
    engine.dispose()


def test_the_free_pages_a_delete_left_are_not_part_of_the_copy(tmp_path, monkeypatch) -> None:
    """After a big delete the file is as big as it was and nearly all of it is free pages; VACUUM copies the few that are in use
    (measured: a 41 MB file with 10 MB in use grew the log by 10.3 MB and the file by nothing). Asking twice the FILE refused a
    compaction that would have fit and was the one thing that gives the space back."""
    engine = _engine_with_rows(tmp_path / "freed.db", wal=False, rows=4000, keep=200)
    report = vacuum_preflight(engine)
    page = _page(engine)
    assert report["copy_bytes_read"] is True and report["copy_bytes"] % page == 0
    assert report["copy_bytes"] < report["db_bytes"] / 5, ("the free pages were counted", report)
    assert report["needed_bytes"] == int(report["copy_bytes"] * VACUUM_HEADROOM)
    real = shutil.disk_usage
    monkeypatch.setattr(
        shutil, "disk_usage", lambda path: type(real(path))(real(path).total, real(path).used, int(report["db_bytes"] * VACUUM_HEADROOM) - 1)
    )
    assert vacuum_preflight(engine)["sufficient"] is True, "less than twice the file but more than twice what is in use must pass"
    _memory(monkeypatch, int(report["db_bytes"] * VACUUM_RAM_FACTOR) - 1)
    assert vacuum_preflight(engine)["sufficient"] is True, "the memory is gated on what is copied, not on the file"
    engine.dispose()


def test_pages_in_use_that_cannot_be_read_fall_back_to_the_whole_file_and_its_log_and_say_so(tmp_path, monkeypatch) -> None:
    from src.database import maintenance

    engine = _engine_with_rows(tmp_path / "wal2.db", wal=True, rows=800)
    monkeypatch.setattr(maintenance, "_vacuum_copy_bytes", lambda engine: None)
    report = vacuum_preflight(engine)
    assert report["copy_bytes_read"] is False and report["copy_bytes"] == report["db_bytes"] + report["wal_bytes"], report
    assert "The pages in use could not be read, so the whole file and its log were counted." in report["detail"] and report["sufficient"] is True
    engine.dispose()


@pytest.mark.parametrize("exc", [OSError("no connection to ask"), RuntimeError("the factory refused"), ValueError("bad key"), KeyError("x")])
def test_a_connection_that_fails_to_answer_is_an_unread_figure_and_never_a_refusal_whatever_it_raises(sqlite_engine, monkeypatch, exc) -> None:
    """Whatever the engine or the connection factory raises (an ``OSError`` is only one of the things a keyed connection can
    do), the figure is unread: a narrowed ``except`` would turn a driver's own error into a failed compaction request."""
    from src.database import maintenance

    real_connect = sqlite_engine.connect

    def _boom(*a, **k):
        raise exc

    monkeypatch.setattr(sqlite_engine, "connect", _boom, raising=False)
    assert maintenance._vacuum_copy_bytes(sqlite_engine) is None
    assert vacuum_preflight(sqlite_engine)["copy_bytes_read"] is False, "the preflight carries on from the whole file"
    monkeypatch.setattr(sqlite_engine, "connect", real_connect, raising=False)
    assert maintenance._vacuum_copy_bytes(sqlite_engine) is not None


def test_the_text_of_a_failed_read_never_reaches_the_log_because_it_can_carry_the_passphrase(sqlite_engine, monkeypatch, caplog) -> None:
    """The passphrase rule: an engine's or a connection factory's message can hold the key (the factory builds ``PRAGMA key``
    statements), and a log record's ``exc_info`` rides the diagnostics bundle. Only the exception's TYPE is recorded."""
    import logging

    from src.database import maintenance

    secret = "correct horse battery staple 8842"

    def _boom(*a, **k):
        raise RuntimeError(f"PRAGMA key = '{secret}' failed")

    monkeypatch.setattr(sqlite_engine, "connect", _boom, raising=False)
    with caplog.at_level(logging.DEBUG):
        assert maintenance._vacuum_copy_bytes(sqlite_engine) is None
        report = vacuum_preflight(sqlite_engine)
    assert secret not in caplog.text and "PRAGMA key" not in caplog.text, caplog.text
    assert secret not in json.dumps(report, default=str), "the report is returned to the API and rides the diagnostics bundle too"
    assert all(r.exc_info is None for r in caplog.records), "no traceback is attached to the record"
    assert "RuntimeError" in caplog.text, "the type is what is kept, so the record still says what kind of failure it was"


class _FakeConn:
    def __init__(self, answers):
        self._answers = answers

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement):
        word = str(statement).split("=")[0].split()[-1].lower() if "=" in str(statement) else str(statement).split()[-1].lower()
        value = self._answers[word]

        class _R:
            def scalar(self_inner):
                return value

        return _R()


class _FakeEngine:
    def __init__(self, **answers):
        self._answers = answers

    def connect(self):
        return _FakeConn(self._answers)


@pytest.mark.parametrize(
    "answers",
    [
        {"page_count": 5, "freelist_count": 5, "page_size": 4096},  # every page free: not a reading of zero bytes
        {"page_count": 5, "freelist_count": 9, "page_size": 4096},  # more free pages than pages
        {"page_count": 0, "freelist_count": 0, "page_size": 4096},
        {"page_count": 5, "freelist_count": 0, "page_size": 0},
    ],
)
def test_a_page_count_that_says_nothing_is_in_use_was_not_read_and_is_never_a_zero_copy(answers) -> None:
    from src.database import maintenance

    assert maintenance._vacuum_copy_bytes(_FakeEngine(**answers)) is None
    assert maintenance._vacuum_copy_bytes(_FakeEngine(page_count=6, freelist_count=2, page_size=8192)) == 4 * 8192


@pytest.mark.parametrize("page", [8192, 16384])
def test_the_copy_is_sized_in_the_files_own_page_size_not_in_4_kib_pages(tmp_path, page) -> None:
    """The app's encrypted stores use 16 KiB pages; a 4,096 written into the sum would under-ask by a factor of four."""
    import sqlite3

    engine = _engine_with_rows(tmp_path / f"p{page}.db", wal=False, rows=600, keep=100, page_size=page)
    assert _page(engine) == page
    con = sqlite3.connect(tmp_path / f"p{page}.db")
    try:
        want = (con.execute("PRAGMA page_count").fetchone()[0] - con.execute("PRAGMA freelist_count").fetchone()[0]) * page
    finally:
        con.close()
    report = vacuum_preflight(engine)
    assert report["copy_bytes_read"] is True and report["copy_bytes"] == want, report
    assert report["copy_bytes"] % page == 0
    engine.dispose()


# --------------------------------------------------------------------------- #
#  a figure that was not read is SAID not to have been (the memory guard's own fail-open rule, stated)
# --------------------------------------------------------------------------- #
def test_a_memory_figure_that_was_not_read_is_named_in_the_detail_and_the_vacuum_still_goes_ahead(sqlite_engine, monkeypatch) -> None:
    _memory(monkeypatch, None)
    report = vacuum_preflight(sqlite_engine)
    assert report["sufficient"] is True and report["not_read"] == ["the memory available"], report
    assert report["detail"].startswith("enough free space for this VACUUM. Not checked"), report["detail"]
    assert "Not checked, because it could not be read: the memory available." in report["detail"]
    assert "free space and memory" not in report["detail"], "it must not claim a memory it did not measure"


def test_a_disk_figure_that_was_not_read_is_named_in_the_detail(sqlite_engine, monkeypatch) -> None:
    def _boom(path):
        raise OSError("statvfs is unavailable here")

    monkeypatch.setattr(shutil, "disk_usage", _boom)
    report = vacuum_preflight(sqlite_engine)
    assert report["sufficient"] is True and report["not_read"] == ["the free space on the database's volume"], report
    assert report["detail"].startswith("enough memory for this VACUUM. Not checked"), report["detail"]
    assert "Not checked, because it could not be read: the free space on the database's volume." in report["detail"]


def test_a_refusal_for_the_figure_that_was_read_still_names_the_one_that_was_not(sqlite_engine, monkeypatch) -> None:
    def _boom(path):
        raise OSError("statvfs is unavailable here")

    monkeypatch.setattr(shutil, "disk_usage", _boom)
    _memory(monkeypatch, 1)
    report = vacuum_preflight(sqlite_engine)
    assert report["short_on"] == ["memory"] and "the free space on the database's volume" in report["detail"], report


# --------------------------------------------------------------------------- #
#  the log: absent is a reading of nothing, unreadable is not
# --------------------------------------------------------------------------- #
def _wal_getsize_raises(monkeypatch, exc):
    real = os.path.getsize

    def _size(path, *a, **k):
        if str(path).endswith("-wal"):
            raise exc
        return real(path, *a, **k)

    monkeypatch.setattr(os.path, "getsize", _size)


def test_a_log_that_is_not_there_is_a_log_of_nothing_and_says_nothing(sqlite_engine, monkeypatch) -> None:
    _wal_getsize_raises(monkeypatch, FileNotFoundError("no log"))
    report = vacuum_preflight(sqlite_engine)
    assert report["wal_bytes"] == 0 and report["not_read"] == [], report
    assert report["detail"] == "enough free space and memory for this VACUUM"


@pytest.mark.parametrize("exc", [PermissionError("no"), OSError(5, "I/O error"), NotADirectoryError("x")])
def test_a_log_that_exists_and_cannot_be_measured_is_named_as_unread_and_is_not_a_zero(sqlite_engine, monkeypatch, exc) -> None:
    _wal_getsize_raises(monkeypatch, exc)
    report = vacuum_preflight(sqlite_engine)
    assert report["wal_bytes"] is None and "the size of the file's log" in report["not_read"], report
    assert report["sufficient"] is True, "an unreadable log is not a refusal"
    assert report["detail"].count("The size of the file's log could not be read and was counted as none.") == 1, report["detail"]
    assert "Not checked" not in report["detail"], "the log has its own sentence: it is not also a figure that was not checked"
    assert report["needed_bytes"] == int(report["copy_bytes"] * VACUUM_HEADROOM), "counted as none, and said so"


def test_a_refusal_with_an_unreadable_log_does_not_print_a_zero_byte_log(sqlite_engine, monkeypatch) -> None:
    _wal_getsize_raises(monkeypatch, PermissionError("no"))
    real = shutil.disk_usage
    monkeypatch.setattr(shutil, "disk_usage", lambda path: type(real(path))(real(path).total, real(path).used, 1))
    report = vacuum_preflight(sqlite_engine)
    assert report["short_on"] == ["database"]
    assert "0-byte log" not in report["detail"] and "a log whose size could not be read" in report["detail"], report["detail"]


# --------------------------------------------------------------------------- #
#  the detail reads as sentences, whichever branch wrote it
# --------------------------------------------------------------------------- #
def test_a_refusal_that_also_carries_a_note_reads_as_sentences_not_as_a_stray_semicolon(sqlite_engine, monkeypatch) -> None:
    def _boom(path):
        raise OSError("statvfs is unavailable here")

    monkeypatch.setattr(shutil, "disk_usage", _boom)
    _memory(monkeypatch, 1)
    report = vacuum_preflight(sqlite_engine)
    assert report["short_on"] == ["memory"]
    assert ".;" not in report["detail"] and "; not checked" not in report["detail"], report["detail"]
    assert report["detail"].endswith("(measured). Not checked, because it could not be read: the free space on the database's volume."), report["detail"]


def test_the_fallback_note_is_said_on_a_refusal_and_the_refusal_names_what_was_counted(tmp_path, monkeypatch) -> None:
    """When the pages in use cannot be read the whole file and its log are counted: the refusal says that, and does not call
    those bytes 'in use'; with the pages read it does."""
    from src.database import maintenance

    engine = _engine_with_rows(tmp_path / "w3.db", wal=True, rows=800)
    real = shutil.disk_usage
    monkeypatch.setattr(shutil, "disk_usage", lambda path: type(real(path))(real(path).total, real(path).used, 1))
    read = vacuum_preflight(engine)
    assert read["short_on"] == ["database"] and "bytes in use" in read["detail"], read["detail"]
    assert "could not be read" not in read["detail"]
    monkeypatch.setattr(maintenance, "_vacuum_copy_bytes", lambda engine: None)
    fell_back = vacuum_preflight(engine)
    assert fell_back["short_on"] == ["database"], fell_back
    assert "bytes in the file and its log" in fell_back["detail"] and "bytes in use" not in fell_back["detail"], fell_back["detail"]
    assert "The pages in use could not be read, so the whole file and its log were counted." in fell_back["detail"]
    assert ".;" not in fell_back["detail"]
    _memory(monkeypatch, 1)
    both = vacuum_preflight(engine)
    assert "bytes in the file and its log" in both["detail"] and "bytes in use" not in both["detail"], "the memory sentence too"
    engine.dispose()


def test_neither_figure_readable_still_says_the_whole_file_was_counted(tmp_path, monkeypatch) -> None:
    from src.database import maintenance

    engine = _engine_with_rows(tmp_path / "w4.db", wal=True, rows=300)

    def _boom(path):
        raise OSError("statvfs is unavailable here")

    monkeypatch.setattr(shutil, "disk_usage", _boom)
    _memory(monkeypatch, None)
    monkeypatch.setattr(maintenance, "_vacuum_copy_bytes", lambda engine: None)
    report = vacuum_preflight(engine)
    assert report["sufficient"] is None and "not preflighted" in report["detail"]
    assert "The pages in use could not be read, so the whole file and its log were counted." in report["detail"], report["detail"]
    assert "Not checked" not in report["detail"], "the free space and the memory are said once, in the main sentence"
    engine.dispose()


# --------------------------------------------------------------------------- #
#  the log and the pages together, and the memory sentence in each state
# --------------------------------------------------------------------------- #
def test_pages_unread_and_a_log_that_cannot_be_measured_say_the_file_alone_was_counted_and_say_each_once(
    sqlite_engine, monkeypatch
) -> None:
    """Both fallbacks at once: the copy is the file alone (the log could not be read, so it is not in the sum), and neither the
    refusal nor the notes may say 'and its log'. The two notes come in the order the figures were meant to be read."""
    from src.database import maintenance

    _wal_getsize_raises(monkeypatch, PermissionError("no"))
    monkeypatch.setattr(maintenance, "_vacuum_copy_bytes", lambda engine: None)
    real = shutil.disk_usage
    monkeypatch.setattr(shutil, "disk_usage", lambda path: type(real(path))(real(path).total, real(path).used, 1))
    _memory(monkeypatch, 1)
    report = vacuum_preflight(sqlite_engine)
    detail = report["detail"]
    assert report["short_on"] == ["database", "memory"] and report["wal_bytes"] is None and report["copy_bytes_read"] is False, report
    assert report["copy_bytes"] == report["db_bytes"] and report["needed_bytes"] == int(report["db_bytes"] * VACUUM_HEADROOM), report
    assert "bytes in the file" in detail and "and its log" not in detail and "bytes in use" not in detail, detail
    log_note = "The size of the file's log could not be read and was counted as none."
    pages_note = "The pages in use could not be read, so the whole file was counted."
    assert detail.count(log_note) == 1 and detail.count(pages_note) == 1, detail
    assert detail.index(log_note) < detail.index(pages_note), "the log's sentence first, then the pages'"
    assert detail.endswith(pages_note) and "Not checked" not in detail, detail


def test_the_memory_sentence_names_what_was_counted_in_each_state(tmp_path, monkeypatch) -> None:
    """A memory-only refusal (the disk is plentiful) says 'bytes in use' when the pages were read and names the file and its log
    when they were not; the figure it prints is the one the gate used."""
    from src.database import maintenance

    engine = _engine_with_rows(tmp_path / "w5.db", wal=True, rows=400)
    _memory(monkeypatch, 1)
    read = vacuum_preflight(engine)
    assert read["short_on"] == ["memory"], read
    assert f"copy of the {read['copy_bytes']:,} bytes in use is held in memory" in read["detail"], read["detail"]
    monkeypatch.setattr(maintenance, "_vacuum_copy_bytes", lambda engine: None)
    unread = vacuum_preflight(engine)
    assert unread["short_on"] == ["memory"], unread
    assert f"copy of the {unread['copy_bytes']:,} bytes in the file and its log is held in memory" in unread["detail"], unread["detail"]
    assert "bytes in use" not in unread["detail"]
    engine.dispose()


def test_an_unreadable_log_is_said_once_when_neither_figure_could_be_read_either(sqlite_engine, monkeypatch) -> None:
    """The early return: the main sentence already says that nothing was preflighted, so the 'not checked' sentence is dropped
    and the log's own sentence is not."""
    _wal_getsize_raises(monkeypatch, PermissionError("no"))

    def _boom(path):
        raise OSError("statvfs is unavailable here")

    monkeypatch.setattr(shutil, "disk_usage", _boom)
    _memory(monkeypatch, None)
    report = vacuum_preflight(sqlite_engine)
    assert report["sufficient"] is None and "not preflighted" in report["detail"], report
    assert report["detail"].count("The size of the file's log could not be read and was counted as none.") == 1, report["detail"]
    assert "Not checked" not in report["detail"], report["detail"]
    assert "the size of the file's log" in report["not_read"], report


def test_the_refusal_sentences_start_with_a_capital_letter(sqlite_engine, monkeypatch) -> None:
    """Each part of a refusal is a sentence of its own, joined by a space: neither begins in lower case."""
    real = shutil.disk_usage
    monkeypatch.setattr(shutil, "disk_usage", lambda path: type(real(path))(real(path).total, real(path).used, 1))
    _memory(monkeypatch, 1)
    detail = vacuum_preflight(sqlite_engine)["detail"]
    assert detail.startswith("The database volume has ") and ". This computer has " in detail, detail
