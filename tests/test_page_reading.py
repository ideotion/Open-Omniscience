"""The page reading taken at every open (WAL / disk thread, diagnostics PR B).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``src/monitoring/page_reading.py`` states a database file's length in pages against the size its header counts. These tests pin the
two things that make that reading worth keeping: it is a FACT with the reason beside every absence (never a zero for "could not
read", never a difference when the header cannot be trusted), and it can never carry a path or a secret (an error is its class and
the NAME of its errno).

The headers are crafted byte by byte, so no engine is needed to produce a stale one: that is the case the Asus machine showed
(14,981 pages in the file that its header did not count) and no healthy SQLite will write on request.
"""

from __future__ import annotations

import errno
import json
import sqlite3
from pathlib import Path

import pytest

from src.monitoring import forensics, page_reading

MARKER = "MARKER-passphrase-4711-correct-horse"


def _header(*, page_size: int = 4096, counter: int = 7, pages: int = 3, valid_for: int | None = None, magic: bool = True) -> bytes:
    head = bytearray(100)
    head[0:16] = page_reading._MAGIC if magic else b"\x00" * 16
    head[16:18] = (1 if page_size == 65536 else page_size).to_bytes(2, "big")
    head[24:28] = counter.to_bytes(4, "big")
    head[28:32] = pages.to_bytes(4, "big")
    head[92:96] = (counter if valid_for is None else valid_for).to_bytes(4, "big")
    return bytes(head)


def _file(tmp_path: Path, *, in_file: int, trailing: int = 0, name: str = "open_omniscience.db", **header) -> Path:
    """A file ``in_file`` pages long (plus ``trailing`` bytes) whose first 100 bytes are a crafted header."""
    page_size = header.get("page_size", 4096)
    body = bytearray(in_file * page_size + trailing)
    body[0:100] = _header(**header)
    path = tmp_path / name
    path.write_bytes(bytes(body))
    return path


# --------------------------------------------------------------------------- #
#  read_header: a plaintext header, valid or not
# --------------------------------------------------------------------------- #
def test_a_healthy_file_reads_as_no_difference_and_says_nothing(tmp_path):
    r = page_reading.read_header(_file(tmp_path, in_file=5, pages=5))
    assert (r["state"], r["source"], r["header_valid"]) == ("read", "header-bytes", True)
    assert (r["pages_in_file"], r["pages_in_header"], r["difference"], r["page_size"], r["trailing_bytes"]) == (5, 5, 0, 4096, 0)
    assert page_reading.line_of(r) is None


def test_a_file_that_holds_pages_its_header_does_not_count_is_the_positive_difference_the_asus_machine_showed(tmp_path):
    r = page_reading.read_header(_file(tmp_path, in_file=20, pages=5))
    assert r["difference"] == 15 and r["pages_in_file"] == 20 and r["pages_in_header"] == 5
    said = page_reading.line_of(r)
    assert said and "15 pages more than its header counts" in said and "20 in the file" in said and "5 in the header" in said
    assert "header-bytes" in said, "the line names the source, because the two sources do not claim the same thing"


def test_a_header_that_counts_more_than_the_file_is_a_negative_difference_and_logs_no_line(tmp_path):
    """Normal while a -wal holds frames not yet folded into the file: a fact kept on the event, not a line."""
    r = page_reading.read_header(_file(tmp_path, in_file=2, pages=9))
    assert r["difference"] == -7
    assert page_reading.line_of(r) is None


def test_an_invalid_header_size_gives_no_difference_because_sqlite_would_not_use_it(tmp_path):
    """Bytes 28 to 31 are only valid when the change counter equals the version-valid-for number (bytes 92 to 95) and is not zero."""
    stale = page_reading.read_header(_file(tmp_path, in_file=20, pages=5, counter=8, valid_for=7))
    assert stale["state"] == "read" and stale["header_valid"] is False and stale["pages_in_header"] == 5
    assert "difference" not in stale
    assert page_reading.line_of(stale) is None
    zero = page_reading.read_header(_file(tmp_path, in_file=20, pages=0, name="zero.db"))
    assert zero["header_valid"] is False and "difference" not in zero


def test_a_torn_tail_is_counted_apart_and_never_rounded_into_a_page(tmp_path):
    r = page_reading.read_header(_file(tmp_path, in_file=4, trailing=1000, pages=4))
    assert r["pages_in_file"] == 4 and r["trailing_bytes"] == 1000 and r["difference"] == 0
    assert r["file_bytes"] == 4 * 4096 + 1000


def test_the_page_size_of_one_means_65536_and_other_sizes_are_read_as_stated(tmp_path):
    big = page_reading.read_header(_file(tmp_path, in_file=2, pages=2, page_size=65536))
    assert big["page_size"] == 65536 and big["pages_in_file"] == 2 and big["difference"] == 0
    small = page_reading.read_header(_file(tmp_path, in_file=6, pages=6, page_size=1024, name="small.db"))
    assert small["page_size"] == 1024 and small["pages_in_file"] == 6


@pytest.mark.parametrize("bad", [0, 256, 1000, 3000, 65535])
def test_a_page_size_sqlite_does_not_accept_is_a_reason_and_not_a_pages_figure(tmp_path, bad):
    path = tmp_path / "open_omniscience.db"
    head = bytearray(_header())
    head[16:18] = bad.to_bytes(2, "big")
    path.write_bytes(bytes(head) + b"\x00" * 8192)
    r = page_reading.read_header(path)
    assert r["state"] == "bad-page-size" and "pages_in_file" not in r and "difference" not in r


# --------------------------------------------------------------------------- #
#  read_header: every reason there is no figure
# --------------------------------------------------------------------------- #
def test_a_missing_file_an_empty_file_and_a_short_one_each_say_which(tmp_path):
    assert page_reading.read_header(tmp_path / "nope.db") == {"source": "header-bytes", "state": "no-file"}
    empty = tmp_path / "empty.db"
    empty.write_bytes(b"")
    r = page_reading.read_header(empty)
    assert r["state"] == "empty" and r["file_bytes"] == 0 and "pages_in_file" not in r
    short = tmp_path / "short.db"
    short.write_bytes(page_reading._MAGIC + b"\x10\x00")
    r = page_reading.read_header(short)
    assert r["state"] == "short" and r["file_bytes"] == len(page_reading._MAGIC) + 2 and "pages_in_file" not in r


def test_an_encrypted_file_reports_its_length_alone_and_never_a_page_count_guessed_from_nothing(tmp_path):
    """A SQLCipher file's first page is encrypted, so the first 16 bytes are not SQLite's magic. A page size nobody could read is not
    divided into the length."""
    path = tmp_path / "open_omniscience.db"
    path.write_bytes(bytes(range(256)) * 64)
    r = page_reading.read_header(path)
    assert r["state"] == "encrypted-or-foreign" and r["file_bytes"] == 16384
    for absent in ("pages_in_file", "pages_in_header", "difference", "page_size", "header_valid"):
        assert absent not in r
    assert page_reading.line_of(r) is None


def test_the_wal_beside_the_file_is_sized_and_its_absence_is_none(tmp_path):
    path = _file(tmp_path, in_file=3, pages=3)
    assert page_reading.read_header(path)["wal_bytes"] is None
    (tmp_path / (path.name + "-wal")).write_bytes(b"\x00" * 4152)
    assert page_reading.read_header(path)["wal_bytes"] == 4152


def test_a_path_that_cannot_be_read_is_its_class_and_errno_name_never_a_message_or_a_path(tmp_path):
    folder = tmp_path / MARKER
    folder.mkdir()
    r = page_reading.read_header(folder)
    assert r["state"] == "unreadable" and r["error"]
    assert MARKER not in json.dumps(r) and str(tmp_path) not in json.dumps(r), "the error carries neither the path nor the message"


def test_a_failing_stat_after_the_open_is_a_reading_that_says_so_and_does_not_raise(tmp_path, monkeypatch):
    path = _file(tmp_path, in_file=2, pages=2)

    def boom(_fd):
        raise OSError(5, f"{MARKER} {path}")

    monkeypatch.setattr(page_reading.os, "fstat", boom)
    r = page_reading.read_header(path)
    assert r["state"] == "unreadable" and MARKER not in json.dumps(r) and str(path) not in json.dumps(r)


# --------------------------------------------------------------------------- #
#  from_connection: the engine's answer
# --------------------------------------------------------------------------- #
def _store(tmp_path: Path) -> Path:
    path = tmp_path / "engine.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t(x BLOB)")
    conn.executemany("INSERT INTO t VALUES(?)", [(b"x" * 3000,) for _ in range(20)])
    conn.commit()
    conn.close()
    return path


def test_the_engine_reading_of_a_healthy_file_agrees_with_the_header_bytes(tmp_path):
    path = _store(tmp_path)
    by_bytes = page_reading.read_header(path)
    conn = sqlite3.connect(path)
    try:
        by_engine = page_reading.from_connection(conn, path)
    finally:
        conn.close()
    assert by_engine["source"] == "engine-pragma" and by_engine["state"] == "read"
    assert by_engine["header_valid"] is None, "the engine cannot say whether the header was valid, so it never claims True"
    for key in ("page_size", "pages_in_file", "difference", "trailing_bytes", "file_bytes"):
        assert by_engine[key] == by_bytes[key], key
    assert by_engine["pages_in_database"] == by_bytes["pages_in_header"]
    assert "pages_in_header" not in by_engine, "with a -wal the engine's count is not the header's, so it is never offered as it"
    assert by_engine["difference"] == 0


def test_the_engine_reading_finds_pages_appended_beyond_what_the_header_counts(tmp_path):
    path = _store(tmp_path)
    before = page_reading.read_header(path)
    with open(path, "ab") as fh:
        fh.write(b"\x00" * (3 * before["page_size"]))
    conn = sqlite3.connect(path)
    try:
        r = page_reading.from_connection(conn, path)
    finally:
        conn.close()
    assert r["difference"] == 3 and r["pages_in_database"] == before["pages_in_header"]
    assert page_reading.read_header(path)["difference"] == 3, "the two sources agree on a file the engine can open"
    said = page_reading.line_of(r)
    assert said and "engine-pragma" in said and "counted by the engine" in said and "no -wal" in said


def test_an_engine_that_raises_is_its_class_and_never_its_message(tmp_path):
    class Wrong:
        def execute(self, sql, *args):
            raise sqlite3.OperationalError(f"file is not a database: {MARKER} {tmp_path}")

    r = page_reading.from_connection(Wrong(), tmp_path / "engine.db")
    assert r["state"] == "unreadable" and r["error"] and r["source"] == "engine-pragma"
    assert MARKER not in json.dumps(r) and str(tmp_path) not in json.dumps(r)


def test_an_engine_that_answers_a_page_size_of_zero_is_a_reason_and_not_a_division_by_zero(tmp_path):
    path = _store(tmp_path)

    class Zero:
        def execute(self, sql, *args):
            class Cur:
                def fetchone(self_inner):
                    return (0,)

            return Cur()

    r = page_reading.from_connection(Zero(), path)
    assert r["state"] == "bad-page-size" and "difference" not in r and "pages_in_file" not in r


# --------------------------------------------------------------------------- #
#  A -wal changes what either count means (the independent read of the first head)
# --------------------------------------------------------------------------- #
def _wal_store_with_a_shrunk_database_in_its_log(tmp_path: Path):
    """A WAL store whose main file is long and whose log holds a committed SHRINK (rows deleted, then ``incremental_vacuum`` drained):
    what any unclean end inside the idle window's vacuum leaves. Returns ``(path, holder)``; the holder keeps the log from being
    checkpointed away and is closed by the caller."""
    path = tmp_path / "wal.db"
    holder = sqlite3.connect(path, isolation_level=None)
    holder.execute("PRAGMA auto_vacuum = INCREMENTAL")
    holder.execute("PRAGMA journal_mode = WAL")
    holder.execute("PRAGMA wal_autocheckpoint = 0")
    holder.execute("CREATE TABLE t(x BLOB)")
    holder.execute("BEGIN")
    holder.executemany("INSERT INTO t VALUES(?)", [(b"x" * 3000,) for _ in range(200)])
    holder.execute("COMMIT")
    holder.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    holder.execute("DELETE FROM t")
    for _ in range(20):  # bounded: a vacuum that drains nothing must fail this fixture, not hang the run
        if not holder.execute("PRAGMA freelist_count").fetchone()[0]:
            break
        holder.execute("PRAGMA incremental_vacuum(50)").fetchall()
    assert holder.execute("PRAGMA freelist_count").fetchone()[0] == 0, "the fixture could not drain the free pages it needs"
    return path, holder


def test_a_shrink_held_in_the_log_is_a_positive_difference_that_the_engine_source_names_as_the_databases_and_logs_no_line(tmp_path):
    """The block of the independent read: with a -wal, ``PRAGMA page_count`` is the database's size at the log's last commit, NOT the
    header's, so a store whose log holds a shrink looked like the Asus signature (the file holds pages the header does not count)
    and was logged at WARNING as such. The figures stay on the event; the sentence is only written when there is no log."""
    path, holder = _wal_store_with_a_shrunk_database_in_its_log(tmp_path)
    try:
        assert (tmp_path / "wal.db-wal").stat().st_size > 0
        other = sqlite3.connect(path)
        try:
            r = page_reading.from_connection(other, path)
        finally:
            other.close()
    finally:
        holder.close()
    assert r["state"] == "read" and r["source"] == "engine-pragma" and "pages_in_header" not in r
    assert r["wal_bytes"] and r["pages_in_database"] < r["pages_in_file"] and r["difference"] > 0, r
    assert page_reading.line_of(r) is None, "a shrink in the log is expected, not the Asus signature"
    r["wal_bytes"] = 0
    assert page_reading.line_of(r), "the same figures with no log are the signature"


def test_the_header_bytes_source_also_gives_a_positive_difference_while_a_log_holds_frames_and_logs_no_line(tmp_path):
    """A passive checkpoint that backfilled page 1 but could not truncate (a reader pinned the log) leaves a header that counts
    FEWER pages than the file; the log says the rest."""
    path = _file(tmp_path, in_file=204, pages=4)
    (tmp_path / (path.name + "-wal")).write_bytes(b"\x00" * 4152)
    r = page_reading.read_header(path)
    assert r["difference"] == 200 and r["wal_bytes"] == 4152
    assert page_reading.line_of(r) is None
    (tmp_path / (path.name + "-wal")).write_bytes(b"")
    assert page_reading.line_of(page_reading.read_header(path)), "an EMPTY log holds no frames: the sentence is written"
    (tmp_path / (path.name + "-wal")).unlink()
    assert page_reading.line_of(page_reading.read_header(path))


@pytest.fixture()
def unreadable_log(monkeypatch):
    """``install(exc)`` makes every ``stat`` of a ``-wal`` name raise ``exc`` (a log that is there and cannot be looked at: no
    permission, an I/O error); any other path is the real one."""

    def install(exc: OSError) -> None:
        real = Path.stat

        def stat(self, *args, **kwargs):
            if self.name.endswith("-wal"):
                raise exc
            return real(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", stat)

    return install


_LOG_ERRORS = [
    (PermissionError(errno.EACCES, "denied", f"/home/{MARKER}/open_omniscience.db-wal"), "PermissionError EACCES"),
    (OSError(errno.ENOTDIR, "not a directory", f"/home/{MARKER}/open_omniscience.db-wal"), "NotADirectoryError ENOTDIR"),
    (OSError(errno.EIO, f"disk error at /home/{MARKER}/x", f"/home/{MARKER}/open_omniscience.db-wal"), "OSError EIO"),
]


@pytest.mark.parametrize(("exc", "label"), _LOG_ERRORS, ids=["eacces", "enotdir", "eio"])
def test_a_log_that_cannot_be_looked_at_is_not_no_log_and_writes_no_line_from_the_header_bytes(tmp_path, unreadable_log, exc, label):
    """Only an ABSENT ``-wal`` (the file does not exist) is "no -wal": the sentence says so, so an unreadable one fails closed. The
    reason is its class and errno name, never the message or the path (the marker stands for a person's home folder)."""
    path = _file(tmp_path, in_file=20, pages=5)
    control = page_reading.read_header(path)
    assert control["difference"] == 15 and control["wal_error"] is None and page_reading.line_of(control), "absent log: the line"
    unreadable_log(exc)
    r = page_reading.read_header(path)
    assert r["wal_bytes"] is None and r["wal_error"] == label
    assert r["difference"] == 15, "the figures are still a fact"
    assert page_reading.line_of(r) is None
    kept = page_reading.compact(r)
    assert kept is not None and kept["wal_error"] == label and "wal_bytes" not in kept
    assert MARKER not in json.dumps(r) and MARKER not in json.dumps(kept)


def test_a_log_that_cannot_be_looked_at_writes_no_line_from_the_engine_either(tmp_path, unreadable_log):
    path, holder = _wal_store_with_a_shrunk_database_in_its_log(tmp_path)
    try:
        other = sqlite3.connect(path)
        try:
            unreadable_log(OSError(errno.EIO, f"disk error at /home/{MARKER}/x", f"/home/{MARKER}/wal.db-wal"))
            r = page_reading.from_connection(other, path)
        finally:
            other.close()
    finally:
        holder.close()
    assert r["state"] == "read" and r["wal_bytes"] is None and r["wal_error"] == "OSError EIO" and r["difference"] > 0, r
    assert page_reading.line_of(r) is None
    assert MARKER not in json.dumps(r)
    r["wal_error"] = None
    assert page_reading.line_of(r), "the same figures with the log ABSENT are the signature"


def test_the_log_sentence_is_withheld_for_any_wal_error_and_only_that():
    said = {"difference": 3, "pages_in_file": 8, "pages_in_header": 5, "source": "header-bytes"}
    assert page_reading.line_of(said)
    assert page_reading.line_of({**said, "wal_error": "OSError EIO"}) is None
    assert page_reading.line_of({**said, "wal_error": None, "wal_bytes": None}), "an absent log is None, with no error"


def test_the_engine_source_with_a_torn_tail_counts_the_tail_apart_and_never_rounds_it_into_a_page(tmp_path):
    path = _store(tmp_path)
    before = page_reading.read_header(path)
    with open(path, "ab") as fh:
        fh.write(b"\x00" * 1000)
    conn = sqlite3.connect(path)
    try:
        r = page_reading.from_connection(conn, path)
    finally:
        conn.close()
    assert r["trailing_bytes"] == 1000 and r["pages_in_file"] == before["pages_in_file"] and r["difference"] == 0


def test_the_engine_source_zeroes_the_busy_timeout_before_it_asks_and_a_busy_answer_is_an_unreadable_reading(tmp_path):
    asked: list[str] = []

    class Busy:
        def execute(self, sql, *args):
            asked.append(sql)
            if sql != "PRAGMA busy_timeout = 0":
                raise sqlite3.OperationalError("database is locked")
            return self

    r = page_reading.from_connection(Busy(), tmp_path / "x.db")
    assert asked[0] == "PRAGMA busy_timeout = 0", "an instrument must not make an unlock wait on the connection's long timeout"
    assert r["state"] == "unreadable" and r["error"] == "OperationalError"


def test_refused_attempts_before_the_reading_are_kept_when_there_are_some_and_omitted_when_there_are_none(tmp_path):
    path = _store(tmp_path)
    conn = sqlite3.connect(path)
    try:
        none = page_reading.from_connection(conn, path)
        two = page_reading.from_connection(conn, path, refused_before=2)
    finally:
        conn.close()
    assert "refused_attempts_before" not in page_reading.compact(none)
    assert page_reading.compact(two)["refused_attempts_before"] == 2


def test_a_file_shorter_than_the_magic_is_short_and_never_called_encrypted(tmp_path):
    path = tmp_path / "open_omniscience.db"
    path.write_bytes(b"SQLite fo")
    assert page_reading.read_header(path)["state"] == "short"
    path.write_bytes(b"\x07")
    assert page_reading.read_header(path)["state"] == "short"


# --------------------------------------------------------------------------- #
#  compact and line_of
# --------------------------------------------------------------------------- #
def test_compact_keeps_only_what_was_read_and_drops_what_was_not(tmp_path):
    assert page_reading.compact(None) is None and page_reading.compact("no") is None  # type: ignore[arg-type]
    assert page_reading.compact({"source": "header-bytes", "state": "no-file"}) == {"source": "header-bytes", "state": "no-file"}
    full = page_reading.compact(page_reading.read_header(_file(tmp_path, in_file=9, pages=5)))
    assert full is not None
    assert set(full) == {"source", "state", "pages_in_file", "pages_in_header", "difference", "page_size", "header_valid",
                         "trailing_bytes", "file_bytes"}, "no wal_bytes while there is no -wal, no error while none occurred"
    kept = page_reading.compact({"source": "engine-pragma", "state": "unreadable", "error": "OperationalError", "pages_in_database": 0,
                                 "refused_attempts_before": 2, "wal_bytes": 0, "pages_in_header": None})
    assert kept == {"source": "engine-pragma", "state": "unreadable", "error": "OperationalError", "pages_in_database": 0,
                    "refused_attempts_before": 2, "wal_bytes": 0}, "the reason an unreadable reading has no figure is kept, so is a 0"
    assert full["header_valid"] is True and full["trailing_bytes"] == 0, "a falsy value that WAS read is kept, only None is dropped"
    assert len(json.dumps(full)) < 400, "an event carries this ten times over, inside a fixed budget"


def test_the_log_sentence_is_only_for_a_file_longer_than_its_header_and_is_counts_only():
    assert page_reading.line_of(None) is None and page_reading.line_of({}) is None
    for diff in (0, -4, None, "3", 2.5):
        assert page_reading.line_of({"difference": diff, "pages_in_file": 9, "pages_in_header": 9, "source": "x"}) is None, diff
    said = page_reading.line_of({"difference": 1, "pages_in_file": 8, "pages_in_header": 7, "source": "engine-pragma"})
    assert said and said.startswith("the database file holds 1 pages more")


def test_the_caveat_says_what_a_difference_cannot_prove():
    text = page_reading.CAVEAT
    assert text.startswith("A fact, not a verdict.")
    for clause in (
        "negative",
        "-wal",
        "version-valid-for",
        "does not rule out a stale header",
        "pages_in_database",
        "refused_attempts_before",
        "either sign",
        "absent refused_attempts_before means none",
        "wal_error",
    ):
        assert clause in text, clause


# --------------------------------------------------------------------------- #
#  The boot reading (forensics)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def boot(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(forensics, "_PREV_AT_BOOT", None)
    monkeypatch.setattr(forensics, "_PREV_LOADED", False)
    monkeypatch.setattr(forensics, "_WAL_AT_BOOT", None)
    monkeypatch.setattr(forensics, "_EARLY_WAL", None)
    monkeypatch.setattr(forensics, "_PAGES_AT_BOOT", None)
    monkeypatch.setattr(forensics, "_EARLY_PAGES", None)
    return tmp_path


def test_the_boot_reads_the_file_in_the_data_folder_before_any_connection(boot):
    _file(boot, in_file=12, pages=7, name=forensics._DB_NAME)
    assert forensics.pages_at_boot() is None, "nothing is read until the boot reads"
    forensics.record_session_start()
    r = forensics.pages_at_boot()
    assert r and r["source"] == "header-bytes" and r["difference"] == 5


def test_the_early_reading_taken_ahead_of_serve_is_the_one_the_lifespan_keeps(boot):
    path = _file(boot, in_file=12, pages=7, name=forensics._DB_NAME)
    forensics.take_boot_wal_reading()
    path.write_bytes(b"")  # whatever happens to the file between serve and the lifespan, the reading was already taken
    forensics.record_session_start()
    r = forensics.pages_at_boot()
    assert r and r["state"] == "read" and r["difference"] == 5
    forensics.record_session_start()
    assert forensics.pages_at_boot()["state"] == "empty", "the early reading is used once; a later start takes its own"


def test_a_data_folder_that_cannot_be_resolved_is_an_unreadable_reading_by_class_only(boot, monkeypatch):
    def gone():
        raise RuntimeError(f"{MARKER} cannot resolve the folder")

    monkeypatch.setattr(forensics, "data_dir", gone)
    r = forensics.pages_state_before_open()
    assert r == {"source": "header-bytes", "state": "unreadable", "error": "RuntimeError"}


def test_a_boot_with_no_store_yet_says_no_file(boot):
    forensics.record_session_start()
    assert forensics.pages_at_boot() == {"source": "header-bytes", "state": "no-file"}


# --------------------------------------------------------------------------- #
#  The sites: the unlock reads off its verify connection, the boot off the bytes
# --------------------------------------------------------------------------- #
TYPED = "typed-key-7Qz!it's-here"


@pytest.fixture()
def unlock_ready(monkeypatch, tmp_path):
    """An unlock that reaches the verify: the engine is a plain SQLite connection (the keyed one is the same API), the finish is
    captured, and nothing is forensic."""
    from src.api import unlock as unlock_mod
    from src.database import connect as connect_mod

    monkeypatch.setattr(forensics, "wal_state_before_open", lambda: None)
    monkeypatch.setattr(unlock_mod, "_begin_recovery_notice", lambda wal_state: None)
    monkeypatch.setattr(unlock_mod, "_end_recovery_notice", lambda token: None)
    monkeypatch.setattr(unlock_mod, "_close_after_checkpoint", lambda conn, passphrase=None: None)
    monkeypatch.setattr(connect_mod, "_passphrase", None)
    monkeypatch.setattr(connect_mod, "set_passphrase", lambda p: None)
    monkeypatch.setattr(unlock_mod, "_REFUSED_ATTEMPTS", 0)
    finished: list[dict] = []
    monkeypatch.setattr(unlock_mod, "_finish_unlock", lambda **kw: finished.append(kw))
    return unlock_mod, connect_mod, finished, tmp_path / "engine.db"


def test_an_unlock_reads_the_pages_off_the_verify_connection_before_the_finish_and_logs_a_longer_file(unlock_ready, monkeypatch, caplog):
    import logging

    unlock_mod, connect_mod, finished, path = unlock_ready
    path = _store(path.parent)
    with open(path, "ab") as fh:
        fh.write(b"\x00" * (4 * page_reading.read_header(path)["page_size"]))
    monkeypatch.setattr(connect_mod, "connect", lambda p, key=None, **kw: sqlite3.connect(p))
    caplog.set_level(logging.WARNING, logger="api.unlock")
    unlock_mod._unlock_locked(unlock_mod.PassphraseBody(passphrase=TYPED), path)
    (call,) = finished
    assert call["pages"]["source"] == "engine-pragma" and call["pages"]["difference"] == 4
    said = [r.getMessage() for r in caplog.records if r.name == "api.unlock" and r.levelno == logging.WARNING]
    assert len(said) == 1 and said[0].startswith("unlock: the database file holds 4 pages more than the database the engine counts")


def test_a_healthy_file_unlocks_with_a_reading_and_no_log_line(unlock_ready, monkeypatch, caplog):
    import logging

    unlock_mod, connect_mod, finished, path = unlock_ready
    path = _store(path.parent)
    monkeypatch.setattr(connect_mod, "connect", lambda p, key=None, **kw: sqlite3.connect(p))
    caplog.set_level(logging.DEBUG, logger="api.unlock")
    unlock_mod._unlock_locked(unlock_mod.PassphraseBody(passphrase=TYPED), path)
    (call,) = finished
    assert call["pages"]["difference"] == 0
    assert not [r for r in caplog.records if "pages more" in r.getMessage()]


def test_an_engine_that_quotes_the_typed_key_while_the_pages_are_read_leaves_it_out_of_the_reading(unlock_ready, monkeypatch, caplog):
    """The reading is taken while the key is still only typed (not held), so no net that scrubs what the process holds can know it:
    the error is its class, by construction."""
    import logging

    unlock_mod, connect_mod, finished, path = unlock_ready

    class Quotes:
        def execute(self, sql, *args):
            raise sqlite3.OperationalError(f"near \"PRAGMA key = '{TYPED}'\": syntax error")

    monkeypatch.setattr(connect_mod, "connect", lambda p, key=None, **kw: Quotes())
    caplog.set_level(logging.DEBUG)
    unlock_mod._unlock_locked(unlock_mod.PassphraseBody(passphrase=TYPED), path)
    (call,) = finished
    assert call["pages"]["state"] == "unreadable" and call["pages"]["error"]
    written = json.dumps(call["pages"]) + "\n".join(r.getMessage() for r in caplog.records)
    assert TYPED not in written and "PRAGMA key" not in written


def test_the_forensic_timer_hands_the_reading_to_the_open_event(tmp_path, monkeypatch):
    from src.api.unlock import _forensic_timer
    from src.monitoring import storage_events as se

    path = tmp_path / "storage_events.json"
    monkeypatch.setattr(se, "_path", lambda: path)
    monkeypatch.setattr(se, "FLUSH_DELAY_S", 0.02)
    se.reset_for_tests()
    try:
        reading = page_reading.read_header(_file(tmp_path, in_file=12, pages=7))
        t = _forensic_timer(wal_state={"bytes": 0, "state": "absent", "reason": "x"}, pages=reading)
        monkeypatch.setattr("src.monitoring.forensics.record_unlock_timing", lambda rec: None)
        t.finish()
        (event,) = se.diagnostics_member(10_000_000)["kinds"]["open"]["events"]
        assert event["via"] == "unlock" and event["pages"]["difference"] == 5 and event["pages"]["pages_in_file"] == 12
        _forensic_timer().finish()
        events = se.diagnostics_member(10_000_000)["kinds"]["open"]["events"]
        assert len(events) == 2 and "pages" not in events[-1], "a fresh store has no reading and the event says nothing of pages"
    finally:
        se.reset_for_tests()


def test_a_boot_journals_the_reading_it_took_before_any_connection_and_logs_a_longer_file(boot, monkeypatch, caplog):
    import logging

    from src.api import main as main_mod
    from src.database import init_steps
    from src.monitoring import storage_events as se

    path = boot / "storage_events.json"
    monkeypatch.setattr(se, "_path", lambda: path)
    monkeypatch.setattr(se, "FLUSH_DELAY_S", 0.02)
    se.reset_for_tests()
    try:
        _file(boot, in_file=30, pages=10, name=forensics._DB_NAME)
        forensics.record_session_start()
        record = {"steps": [{"step": "create_all", "ms": 5.0}], "total_ms": 5.0, "process_call": 1, "earlier_complete_calls": 0,
                  "complete": True}
        monkeypatch.setattr(init_steps, "first_record", lambda: record)
        monkeypatch.setattr(init_steps, "last_record", lambda: record)
        caplog.set_level(logging.WARNING)
        main_mod._note_boot_init_db()
        (event,) = se.diagnostics_member(10_000_000)["kinds"]["open"]["events"]
        assert event["via"] == "boot" and event["pages"]["source"] == "header-bytes" and event["pages"]["difference"] == 20
        said = [r.getMessage() for r in caplog.records if "pages more than its header counts" in r.getMessage()]
        assert len(said) == 1 and said[0].startswith("boot: the database file holds 20 pages more")
    finally:
        se.reset_for_tests()


def test_the_unlock_reads_the_pages_before_the_connection_that_proved_the_key_is_checkpointed_and_closed():
    """MUTATION TARGET: the order. The close folds the log into the file and rewrites the header's size, so a reading taken after it
    describes the file the unlock left and not the one the last session did. The unlock-recovery test pins the same order on the
    real close (``test_the_verify_connection_is_checkpointed_through_execute_before_it_closes``); the behavioural tests above stub the
    close out, so the order is also pinned on the source."""
    import inspect

    from src.api import unlock as unlock_mod

    src = inspect.getsource(unlock_mod._unlock_locked)
    assert 0 < src.index("page_reading.from_connection(conn, p, refused_before=_REFUSED_ATTEMPTS)") < src.index("_close_after_checkpoint(conn")


def test_a_refused_passphrase_is_counted_and_the_next_unlocks_reading_says_so(unlock_ready, monkeypatch):
    """Each refused key's connection folds the -wal into the file and deletes it, so the reading the right key takes afterwards
    describes the file after that: a 0 there is not a healthy previous end. The count rides the reading."""
    from fastapi import HTTPException

    unlock_mod, connect_mod, finished, path = unlock_ready
    path = _store(path.parent)

    def refuse(*a, **k):
        raise connect_mod.WrongPassphraseError("not it")

    monkeypatch.setattr(connect_mod, "connect", refuse)
    for _ in range(2):
        with pytest.raises(HTTPException):
            unlock_mod._unlock_locked(unlock_mod.PassphraseBody(passphrase=TYPED), path)
    assert unlock_mod._REFUSED_ATTEMPTS == 2 and finished == []
    monkeypatch.setattr(connect_mod, "connect", lambda p, key=None, **kw: sqlite3.connect(p))
    unlock_mod._unlock_locked(unlock_mod.PassphraseBody(passphrase=TYPED), path)
    (call,) = finished
    assert call["pages"]["refused_attempts_before"] == 2
    assert page_reading.compact(call["pages"])["refused_attempts_before"] == 2


def test_the_early_page_reading_a_serve_leaves_behind_is_set_by_one_test(tmp_path, monkeypatch):
    """First of a PAIR (the second asserts the conftest fixture cleared it): ``main._serve()`` run in-process takes the early reading."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    forensics.take_boot_wal_reading()
    assert forensics._EARLY_PAGES is not None


def test_the_early_page_reading_does_not_leak_into_the_next_test():
    """Second of the pair: a reading taken for another test's data folder would be journaled as this boot's."""
    assert forensics._EARLY_PAGES is None
