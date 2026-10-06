"""The page pass of an encrypted file (damaged-database plan, slice E2b).

Measured on real SQLCipher stores (see ``src/database/verify.py``): a page that fails its authentication tag makes the per-table
``quick_check`` either answer a row (filed ``damaged``) or raise the driver's generic ``SQLITE_ERROR`` (filed ``unchecked``): of
40 single pages overwritten on a 500-article store, 10 files came out damaged and 30 unchecked, and ``PRAGMA
cipher_integrity_check`` named the page in every one of them. E2b asks that pragma once, and only after such an ``unchecked``.

Every claim here is made against REAL encrypted files damaged the way a bad sector damages them (one whole page overwritten with
random bytes), through the real check, the real registry and the real re-read; only the answers the driver cannot be made to give
on demand (a build without the pragma, a disk error in the middle of a pass, a million failing pages) are stood in for, and said:

  * the pass runs after the generic error on an ENCRYPTED file and after nothing else (a healthy file, a wrong passphrase, a busy
    file and an I/O error never reach it) and names the page that was overwritten;
  * a table that did not answer STAYS unchecked: a clean pass never makes a file clean;
  * a pass that cannot be made (no such pragma in this build, a stop, a driver error) is ``unchecked`` with the reason, and the
    connection it used is closed on every path;
  * the page list is capped and the count is not; an answer the pass cannot read is damage, never a clean file;
  * the finding rides the record, the incident and the latch like a table's; the next start and a start of collection ask again, and
    only a pass that reads ``ok`` clears it.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import sqlite3
import threading
from pathlib import Path

import pytest

from src.database import connect as connect_mod
from src.database import damage, verify
from src.database.damage import (
    FILE_CORPUS,
    SCOPE_DATA,
    VERDICT_DAMAGED,
    VERDICT_OK,
    VERDICT_UNCHECKED,
    DamageRegistry,
)
from src.scheduler import storage_guard as sg

from . import damaged_store_helpers as H

PAGE = H.CIPHER_PAGE
UNCLEAN = {"clean": False, "at": "2026-10-06T01:00:00+00:00", "basis": "the liveness file"}
CLEAN = {"clean": True, "at": "2026-10-06T01:00:00+00:00", "basis": "the sentinel"}


# --------------------------------------------------------------------------- #
#  fixtures: a small real encrypted store, a page of it whose damage the table check cannot answer for
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module", autouse=True)
def _driver():
    H.needs_sqlcipher()
    previous = connect_mod.get_passphrase()
    connect_mod.set_passphrase(H.KEY)
    yield
    connect_mod.set_passphrase(previous)


@pytest.fixture(scope="module")
def base(tmp_path_factory, _driver) -> Path:
    """An encrypted store of 16 KiB pages with a big table (``articles``, with an index), a small one (``notes``) and nothing else."""
    path = tmp_path_factory.mktemp("pages") / "base.db"
    con = connect_mod.connect(str(path), create_encrypted=True, check_same_thread=False)
    try:
        con.execute("CREATE TABLE articles(id INTEGER PRIMARY KEY, title TEXT, body TEXT)")
        con.execute("CREATE INDEX ix_articles_title ON articles(title)")
        con.execute("CREATE TABLE notes(id INTEGER PRIMARY KEY, note TEXT)")
        rng = random.Random(1)
        words = [f"w{i}" for i in range(2000)]
        for i in range(1500):
            con.execute(
                "INSERT INTO articles(title, body) VALUES (?, ?)",
                (f"t{i} " + rng.choice(words), " ".join(rng.choice(words) for _ in range(120))),
            )
        for i in range(50):
            con.execute("INSERT INTO notes(note) VALUES (?)", (f"n{i}",))
        con.commit()
    finally:
        con.close()
    return path


def _overwrite(path: Path, page: int) -> None:
    H.overwrite_pages(path, [page], PAGE)


def _find_page(base: Path, tmp_path_factory, want: str, *, code: int | None) -> int:
    """A page of ``articles`` whose overwriting makes its table check answer ``want`` (with the driver code ``code``), found by trying
    pages in a seeded order: which pages do which is the driver's business, so the test asks it instead of assuming."""
    work = tmp_path_factory.mktemp("find") / "w.db"
    n = os.path.getsize(base) // PAGE
    for pg in random.Random(5).sample(range(2, n + 1), n - 1):
        shutil.copy(base, work)
        _overwrite(work, pg)
        r = verify.check_table(work, "articles")
        if r["verdict"] == want and r.get("sqlite_code") == code:
            return pg
    pytest.fail(f"no page of the articles table made its check answer {want} (code {code})")


@pytest.fixture(scope="module")
def unchecked_page(base, tmp_path_factory) -> int:
    return _find_page(base, tmp_path_factory, VERDICT_UNCHECKED, code=1)


@pytest.fixture(scope="module")
def damaged_page(base, tmp_path_factory) -> int:
    return _find_page(base, tmp_path_factory, VERDICT_DAMAGED, code=None)


@pytest.fixture
def healthy(tmp_path, base) -> Path:
    path = tmp_path / "healthy.db"  # its own name: a test may hold a damaged copy beside it
    shutil.copy(base, path)
    return path


@pytest.fixture
def unchecked(tmp_path, base, unchecked_page) -> Path:
    """A copy with one page overwritten that the table check cannot answer for."""
    path = tmp_path / "corpus.db"
    shutil.copy(base, path)
    _overwrite(path, unchecked_page)
    return path


@pytest.fixture
def damaged(tmp_path, base, damaged_page) -> Path:
    """A copy with one page overwritten that the table check files ``damaged`` by itself."""
    path = tmp_path / "corpus.db"
    shutil.copy(base, path)
    _overwrite(path, damaged_page)
    return path


@pytest.fixture
def registry(tmp_path, monkeypatch):
    reg = DamageRegistry(path_fn=lambda: tmp_path / "database-damage.json")
    monkeypatch.setattr(damage, "registry", reg)
    verify._reset_for_tests()
    yield reg
    verify._reset_for_tests()


@pytest.fixture
def files(tmp_path, monkeypatch, registry):
    paths: dict[str, Path] = {}

    def fake(key):
        p = paths.get(key)
        return (p, p.name) if p else (None, None)

    monkeypatch.setattr(damage, "_file_paths", fake)
    return paths


@pytest.fixture
def asked(monkeypatch):
    """The paths the page pass was asked about, in order (the real pass still runs)."""
    calls: list[Path] = []
    real = verify.confirm_encrypted_damage

    def spy(path, **kw):
        calls.append(Path(path))
        return real(path, **kw)

    monkeypatch.setattr(verify, "confirm_encrypted_damage", spy)
    return calls


def _record(tmp_path) -> dict:
    return json.loads((tmp_path / "database-damage.json").read_text(encoding="utf-8"))


def _by_table(entry: dict) -> dict[str, dict]:
    return {t["table"]: t for t in entry["tables"]}


def _run(files, path, monkeypatch, end=UNCLEAN) -> None:
    files[FILE_CORPUS] = path
    monkeypatch.setattr(damage, "_previous_end", lambda: end)
    assert verify.arm_at_boot() is True
    assert verify.run_armed() is True


def _new_process(tmp_path, monkeypatch) -> DamageRegistry:
    reg = DamageRegistry(path_fn=lambda: tmp_path / "database-damage.json")
    monkeypatch.setattr(damage, "registry", reg)
    verify._reset_for_tests()
    return reg


def _join_rechecks(timeout: float = 60.0) -> None:
    for t in [t for t in threading.enumerate() if t.name == "oo-database-recheck"]:
        t.join(timeout)
        assert not t.is_alive(), "a re-read did not end"


class _Cursor:
    """What a stand-in connection's statement answers: iterable (the page pass reads it row by row) and ``fetchall`` (the probe)."""

    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)

    def fetchall(self):
        return list(self.rows)


class _Rows:
    """A stand-in connection answering the page pass's one statement with the rows it is given (a generator, so a million rows
    are never held), and recording that it was closed."""

    def __init__(self, rows=(), boom: BaseException | None = None):
        self.rows, self.boom, self.closed, self.statements = rows, boom, 0, []

    def execute(self, sql, *args):
        self.statements.append(sql)
        if self.boom is not None:
            raise self.boom
        return _Cursor(self.rows)

    def close(self):
        self.closed += 1


# --------------------------------------------------------------------------- #
#  the generic error, told from the errors that are not it
# --------------------------------------------------------------------------- #
def _driver_error(message: str, code: int):
    sqc = pytest.importorskip("sqlcipher3.dbapi2")
    e = sqc.OperationalError(message)
    e.sqlite_errorcode = code
    return e


@pytest.mark.parametrize(
    ("message", "code", "generic"),
    [
        ("SQL logic error", 1, True),
        ("SQL logic error or missing database", 1, True),
        ("no such module: fts5", 1, False),
        ("no such table: articles", 1, False),
        ("database is locked", 5, False),
        ("disk I/O error", 10, False),
        ("database disk image is malformed", 11, False),
        ("file is not a database", 26, False),
        ("interrupted", 9, False),
    ],
)
def test_the_generic_error_is_told_from_the_codes_that_are_not_it(message, code, generic):
    assert verify.is_generic_error(_driver_error(message, code)) is generic


def test_an_error_that_is_not_the_drivers_is_never_the_generic_error():
    assert verify.is_generic_error(ValueError("SQL logic error")) is False
    assert verify.is_generic_error(connect_mod.WrongPassphraseError("the passphrase did not open the file")) is False


def test_the_list_of_tables_carries_the_generic_code_when_it_could_not_be_read_and_nothing_else_does(tmp_path):
    def opener_raising(message, code):
        def opener(p):
            raise _driver_error(message, code)

        return opener

    path = tmp_path / "x.db"
    path.write_bytes(b"\x00" * 100)
    generic = verify.inspect_file(path, opener=opener_raising("SQL logic error", 1))
    assert generic["error"][0] == VERDICT_UNCHECKED and generic["sqlite_code"] == 1
    for message, code in (("database is locked", 5), ("disk I/O error", 10), ("no such module: fts5", 1)):
        other = verify.inspect_file(path, opener=opener_raising(message, code))
        assert other["error"][0] == VERDICT_UNCHECKED and "sqlite_code" not in other, (message, other)


def test_a_table_the_check_cannot_answer_for_carries_the_code_and_nothing_else_does(healthy, unchecked):
    answer = verify.check_table(unchecked, "articles")
    assert answer["verdict"] == VERDICT_UNCHECKED and answer["sqlite_code"] == 1
    assert "sqlite_code" not in verify.check_table(healthy, "articles"), "a clean answer carries a driver code"
    wrong = verify.check_table(healthy, "articles", opener=lambda p: H.open_store(p, key="not the passphrase at all, but long"))
    assert wrong["verdict"] == VERDICT_UNCHECKED and "sqlite_code" not in wrong, "a wrong passphrase reached the page pass"
    stopped = threading.Event()
    stopped.set()
    answer = verify.check_table(unchecked, "articles", cancel=stopped)
    assert answer["verdict"] == VERDICT_UNCHECKED and "sqlite_code" not in answer, "a stop reads as the generic error"


# --------------------------------------------------------------------------- #
#  the pass itself, on real pages
# --------------------------------------------------------------------------- #
def test_the_page_pass_names_the_page_the_table_check_could_not(unchecked, unchecked_page):
    entry = verify.confirm_encrypted_damage(unchecked)
    assert entry["table"] == verify.PAGES_ENTRY and entry["verdict"] == VERDICT_DAMAGED
    assert entry["pages"] == [unchecked_page] and entry["pages_total"] == 1, "exactly the one page that was overwritten"
    assert f"{unchecked_page}" in entry["detail"][0] and "authentication" in entry["detail"][0]
    assert "sqlite_code" not in entry


def test_the_page_pass_says_ok_for_a_file_whose_pages_all_pass_and_writes_nothing(healthy):
    before = H.sha(healthy)
    entry = verify.confirm_encrypted_damage(healthy)
    assert entry["verdict"] == VERDICT_OK and "pages" not in entry and "pages_total" not in entry
    assert H.sha(healthy) == before, "the pass changed the file"
    assert not [p for p in healthy.parent.iterdir() if p.name != healthy.name], "the pass left a file beside the store"


def test_the_page_pass_names_many_pages_and_a_page_the_table_check_would_have_filed_itself(base, tmp_path):
    path = tmp_path / "corpus.db"
    shutil.copy(base, path)
    n = os.path.getsize(path) // PAGE
    bad = sorted(random.Random(8).sample(range(5, n + 1), 6))
    H.overwrite_pages(path, bad, PAGE)
    entry = verify.confirm_encrypted_damage(path)
    assert entry["verdict"] == VERDICT_DAMAGED and entry["pages"] == bad and entry["pages_total"] == 6


# --------------------------------------------------------------------------- #
#  when it runs, and when it does not
# --------------------------------------------------------------------------- #
def test_a_healthy_encrypted_file_is_asked_nothing(tmp_path, healthy, files, monkeypatch, asked):
    _run(files, healthy, monkeypatch)
    entry = _record(tmp_path)["verification"][FILE_CORPUS]
    assert entry["verdict"] == VERDICT_OK and verify.PAGES_ENTRY not in _by_table(entry)
    assert asked == [], "the page pass ran on a file whose tables all read clean"


def test_a_table_the_check_files_damaged_by_itself_does_not_ask_the_pass(tmp_path, damaged, files, monkeypatch, asked):
    _run(files, damaged, monkeypatch)
    entry = _record(tmp_path)["verification"][FILE_CORPUS]
    assert entry["verdict"] == VERDICT_DAMAGED and _by_table(entry)["articles"]["verdict"] == VERDICT_DAMAGED
    assert verify.PAGES_ENTRY not in _by_table(entry) and asked == []


def test_only_the_generic_error_on_an_encrypted_file_asks_the_pass(healthy, tmp_path):
    unchecked_no_code = [{"table": "articles", "verdict": VERDICT_UNCHECKED, "detail": ["the file was busy"]}]
    for answers in (
        unchecked_no_code,  # busy, locked, a wrong passphrase, an I/O error, a stop: unchecked WITHOUT the generic code
        [{"table": "articles", "verdict": VERDICT_OK}],
        [{"table": "articles", "verdict": VERDICT_DAMAGED, "sqlite_code": 1}],  # damaged is already a verdict
        [],
    ):
        assert verify.page_check(healthy, answers) is None, answers
    asking = [{"table": "articles", "verdict": VERDICT_UNCHECKED, "sqlite_code": 1}]
    entry = verify.page_check(healthy, asking)
    assert entry is not None and entry["table"] == verify.PAGES_ENTRY and entry["verdict"] == VERDICT_OK
    plain = tmp_path / "plain.db"
    con = sqlite3.connect(plain)
    con.execute("CREATE TABLE t(x)")
    con.commit()
    con.close()
    assert verify.page_check(plain, asking) is None, "a plaintext file has no page tags: the generic error there is about something else"


def test_an_earlier_pages_finding_is_asked_again_and_a_plaintext_or_unreadable_file_answers_in_its_own_words(healthy, tmp_path):
    again = [verify.PAGES_ENTRY]
    assert verify.page_check(healthy, [], earlier=again)["verdict"] == VERDICT_OK
    plain = tmp_path / "plain.db"
    con = sqlite3.connect(plain)
    con.execute("CREATE TABLE t(x)")
    con.commit()
    con.close()
    entry = verify.page_check(plain, [], earlier=again)
    assert entry["verdict"] == VERDICT_OK and "not encrypted" in entry["detail"][0]
    entry = verify.page_check(tmp_path / "missing.db", [], earlier=again)
    assert entry["verdict"] == VERDICT_UNCHECKED and "could not be examined" in entry["detail"][0]


# --------------------------------------------------------------------------- #
#  what the check does with the answer
# --------------------------------------------------------------------------- #
def test_the_file_is_damaged_when_the_pass_names_a_page_and_the_table_that_did_not_answer_stays_unchecked(
    tmp_path, unchecked, unchecked_page, files, monkeypatch, asked
):
    _run(files, unchecked, monkeypatch)
    reg = damage.registry
    assert reg.latched(FILE_CORPUS), "pages that fail their authentication did not latch the file"
    assert sg.StorageGuard().admit() == "damage"
    rec = _record(tmp_path)
    entry = rec["verification"][FILE_CORPUS]
    tables = _by_table(entry)
    assert entry["verdict"] == VERDICT_DAMAGED and entry["tables_total"] == 2
    assert tables[verify.PAGES_ENTRY]["verdict"] == VERDICT_DAMAGED and tables[verify.PAGES_ENTRY]["pages"] == [unchecked_page]
    assert tables["articles"]["verdict"] == VERDICT_UNCHECKED and tables["articles"]["sqlite_code"] == 1, "the table's own answer was rewritten"
    assert tables["notes"]["verdict"] == VERDICT_OK
    assert len(asked) == 1, "the pass ran more than once for one check of one file"
    [inc] = rec["incidents"]
    assert inc["file"] == FILE_CORPUS and inc["scope"] == SCOPE_DATA and verify.PAGES_ENTRY in inc["tables"]
    assert "cipher_integrity_check" in inc["statement_shape"] and "quick_check" not in inc["statement_shape"], inc["statement_shape"]
    assert reg.state(detail=True)["files"][FILE_CORPUS]["check_tables"] == [verify.PAGES_ENTRY]


def test_a_clean_pass_never_makes_a_file_with_an_unanswered_table_clean(tmp_path, healthy, files, monkeypatch, asked):
    real = verify.check_table

    def one_table_cannot_answer(path, table, **kw):
        if table == "articles":
            return {"table": table, "verdict": VERDICT_UNCHECKED, "seconds": 0.0, "detail": ["OperationalError"], "sqlite_code": 1}
        return real(path, table, **kw)

    monkeypatch.setattr(verify, "check_table", one_table_cannot_answer)
    _run(files, healthy, monkeypatch)
    entry = _record(tmp_path)["verification"][FILE_CORPUS]
    tables = _by_table(entry)
    assert asked == [healthy]
    assert tables[verify.PAGES_ENTRY]["verdict"] == VERDICT_OK and tables["articles"]["verdict"] == VERDICT_UNCHECKED
    assert entry["verdict"] == VERDICT_UNCHECKED, "a pass that found nothing called a file with an unanswered table clean"
    assert not damage.registry.latched(FILE_CORPUS), "a clean pass latched the file"


def test_a_table_list_that_cannot_be_read_is_asked_too_and_a_damaged_answer_keeps_the_schema_entry(
    tmp_path, unchecked, unchecked_page, files, monkeypatch
):
    monkeypatch.setattr(verify, "inspect_file", lambda path, opener=None: {"error": (VERDICT_UNCHECKED, "OperationalError"), "sqlite_code": 1})
    _run(files, unchecked, monkeypatch)
    entry = _record(tmp_path)["verification"][FILE_CORPUS]
    tables = _by_table(entry)
    assert entry["verdict"] == VERDICT_DAMAGED and entry["listed"] is False
    assert tables[verify.SCHEMA_ENTRY]["verdict"] == VERDICT_DAMAGED, "(schema) is what makes a re-read read every table again"
    assert tables[verify.PAGES_ENTRY]["pages"] == [unchecked_page]
    assert damage.registry.state(detail=True)["files"][FILE_CORPUS]["check_tables"] == sorted([verify.PAGES_ENTRY, verify.SCHEMA_ENTRY])


def test_a_table_list_that_cannot_be_read_and_pages_that_pass_stays_unchecked_and_says_both(tmp_path, healthy, files, monkeypatch):
    monkeypatch.setattr(verify, "inspect_file", lambda path, opener=None: {"error": (VERDICT_UNCHECKED, "OperationalError"), "sqlite_code": 1})
    _run(files, healthy, monkeypatch)
    entry = _record(tmp_path)["verification"][FILE_CORPUS]
    assert entry["verdict"] == VERDICT_UNCHECKED and entry["tables"] == []
    assert "OperationalError" in entry["reason"] and verify.PAGES_ENTRY in entry["reason"]
    assert not damage.registry.latched(FILE_CORPUS)


# --------------------------------------------------------------------------- #
#  a pass that cannot be made
# --------------------------------------------------------------------------- #
def test_a_build_without_the_pragma_is_unchecked_with_that_reason_never_clean(tmp_path, unchecked, files, monkeypatch):
    sqc = pytest.importorskip("sqlcipher3.dbapi2")
    verify._reset_for_tests()
    assert verify.cipher_check_present() is True, "this build's SQLCipher has the pragma: the probe cannot see it"

    class Probe(_Rows):
        pass

    monkeypatch.setattr(sqc, "connect", lambda *a, **k: Probe(rows=[]))  # an unknown pragma answers no rows at all
    verify._reset_for_tests()
    assert verify.cipher_check_present() is False
    monkeypatch.undo()
    # With the probe saying no, the file stays unchecked: no pragma means no answer, and no answer is not "clean".
    monkeypatch.setattr(verify, "cipher_check_present", lambda: False)
    entry = verify.confirm_encrypted_damage(unchecked)
    assert entry["verdict"] == VERDICT_UNCHECKED and "no page-authentication check" in entry["detail"][0]
    assert "pages" not in entry


def test_the_probe_reads_no_answer_from_a_driver_that_cannot_be_asked_as_no_pragma(monkeypatch):
    sqc = pytest.importorskip("sqlcipher3.dbapi2")

    def boom(*a, **k):
        raise sqc.OperationalError("unable to open database file")

    monkeypatch.setattr(sqc, "connect", boom)
    verify._reset_for_tests()
    assert verify.cipher_check_present() is False
    monkeypatch.undo()
    verify._reset_for_tests()
    assert verify.cipher_check_present() is True


def test_a_run_whose_pass_cannot_be_made_files_the_file_unchecked_and_the_record_says_why(tmp_path, unchecked, files, monkeypatch):
    monkeypatch.setattr(verify, "cipher_check_present", lambda: False)
    _run(files, unchecked, monkeypatch)
    entry = _record(tmp_path)["verification"][FILE_CORPUS]
    tables = _by_table(entry)
    assert entry["verdict"] == VERDICT_UNCHECKED and tables[verify.PAGES_ENTRY]["verdict"] == VERDICT_UNCHECKED
    assert not damage.registry.latched(FILE_CORPUS), "a pass nobody could make latched the file"


def test_a_stop_before_the_pass_begins_is_unchecked_and_a_stopped_run_has_no_verdict(tmp_path, unchecked, files, monkeypatch, asked):
    stopped = threading.Event()
    stopped.set()
    entry = verify.confirm_encrypted_damage(unchecked, cancel=stopped)
    assert entry["verdict"] == VERDICT_UNCHECKED and entry["detail"] == ["the check was stopped"]
    asked.clear()  # the direct call above is counted by the spy; the run below is what must not ask

    real = verify.check_table

    def stop_after_the_table(path, table, **kw):
        out = real(path, table, **kw)
        verify._CANCEL.set()
        return out

    monkeypatch.setattr(verify, "check_table", stop_after_the_table)
    _run(files, unchecked, monkeypatch)
    entry = _record(tmp_path)["verification"][FILE_CORPUS]
    assert entry["state"] == "running" and "verdict" not in entry, "a stopped run wrote a verdict"
    assert asked == [], "the pass began after a stop was asked for"
    assert not damage.registry.latched(FILE_CORPUS)


@pytest.mark.parametrize(
    ("rows", "boom", "verdict", "words"),
    [
        ([], None, VERDICT_OK, "no page"),
        ([("HMAC verification failed for page 7",)], None, VERDICT_DAMAGED, "1 page"),
        ([], "io", VERDICT_UNCHECKED, "disk I/O"),
        ([], "other", VERDICT_UNCHECKED, "OperationalError"),
    ],
)
def test_the_connection_is_closed_on_every_path(rows, boom, verdict, words):
    sqc = pytest.importorskip("sqlcipher3.dbapi2")
    err = None
    if boom == "io":
        err = sqc.OperationalError("disk I/O error")
        err.sqlite_errorcode = 10
    elif boom:
        err = sqc.OperationalError("something else")
    con = _Rows(rows=rows, boom=err)
    verify._reset_for_tests()
    entry = verify.confirm_encrypted_damage(Path("whatever.db"), opener=lambda p: con)
    assert entry["verdict"] == verdict and words in entry["detail"][0], entry
    assert con.closed == 1, "the pass's connection was not closed exactly once"
    assert con.statements == ["PRAGMA cipher_integrity_check"]


def test_a_connection_that_cannot_be_opened_is_unchecked_and_nothing_is_left_open():
    sqc = pytest.importorskip("sqlcipher3.dbapi2")

    def opener(p):
        e = sqc.OperationalError("unable to open database file")
        e.sqlite_errorcode = 14
        raise e

    entry = verify.confirm_encrypted_damage(Path("whatever.db"), opener=opener)
    assert entry["verdict"] == VERDICT_UNCHECKED and "could not be opened" in entry["detail"][0]


def test_the_pass_opens_the_file_read_only(unchecked, monkeypatch):
    seen: list[str] = []
    real = connect_mod.connect

    def spy(path, **kw):
        seen.append(str(kw.get("read_only")))
        return real(path, **kw)

    monkeypatch.setattr(connect_mod, "connect", spy)
    verify.confirm_encrypted_damage(unchecked)
    assert seen == ["True"], "the pass opened the file for writing"


# --------------------------------------------------------------------------- #
#  the record's size
# --------------------------------------------------------------------------- #
def test_the_page_list_is_capped_and_the_count_is_not():
    rows = [(f"HMAC verification failed for page {n}",) for n in range(5000, 0, -1)]  # worst order: the highest first
    entry = verify.confirm_encrypted_damage(Path("x.db"), opener=lambda p: _Rows(rows=rows))
    assert entry["pages_total"] == 5000, "the count of failing pages is always kept"
    assert entry["pages"] == list(range(1, verify.MAX_PAGES_LISTED + 1)), "the list is the lowest page numbers, in order"
    assert len(json.dumps(entry)) < 1024, "the record's entry for a file in which every page fails is no longer a few hundred bytes"
    assert len(entry["detail"][0]) <= verify.DETAIL_CHARS and "5000 page(s)" in entry["detail"][0]


def test_a_million_failing_pages_are_counted_without_holding_them():
    def rows():
        for n in range(1_000_000):
            yield (f"HMAC verification failed for page {n + 1}",)

    entry = verify.confirm_encrypted_damage(Path("x.db"), opener=lambda p: _Rows(rows=rows()))
    assert entry["pages_total"] == 1_000_000 and len(entry["pages"]) == verify.MAX_PAGES_LISTED


def test_an_answer_the_pass_cannot_read_is_damage_with_its_own_words_never_a_clean_file():
    entry = verify.confirm_encrypted_damage(Path("x.db"), opener=lambda p: _Rows(rows=[("something this app has never seen",)]))
    assert entry["verdict"] == VERDICT_DAMAGED and entry["pages"] == [] and entry["pages_total"] == 0
    assert entry["detail"] == ["something this app has never seen"]


# --------------------------------------------------------------------------- #
#  the next start, and a start of collection
# --------------------------------------------------------------------------- #
def test_the_next_start_asks_again_and_only_a_pass_that_reads_ok_clears_the_finding(tmp_path, base, unchecked, files, monkeypatch, asked):
    _run(files, unchecked, monkeypatch)

    # the next process, after a clean end: the finding is what makes the file due, and the pass is owed again
    _new_process(tmp_path, monkeypatch)
    assert damage.carried_damage(damage.registry.previous_verification(FILE_CORPUS)) == [verify.PAGES_ENTRY]
    asked.clear()
    _run(files, unchecked, monkeypatch, end=CLEAN)
    assert asked == [unchecked], "an earlier (pages) finding did not ask the pass again"
    assert damage.registry.latched(FILE_CORPUS)

    # the file is replaced by a healthy one: every table reads ok and so does the pass, and the finding goes
    _new_process(tmp_path, monkeypatch)
    shutil.copy(base, unchecked)
    asked.clear()
    _run(files, unchecked, monkeypatch, end=CLEAN)
    entry = _record(tmp_path)["verification"][FILE_CORPUS]
    assert entry["verdict"] == VERDICT_OK and _by_table(entry)[verify.PAGES_ENTRY]["verdict"] == VERDICT_OK
    assert asked == [unchecked]
    assert not damage.registry.latched(FILE_CORPUS)
    _new_process(tmp_path, monkeypatch)
    assert damage.carried_damage(damage.registry.previous_verification(FILE_CORPUS)) is None, "an ok pass left the finding standing"


def test_a_finding_the_run_never_asked_the_pass_about_is_not_cleared(monkeypatch):
    ok = [{"table": "articles", "verdict": VERDICT_OK}, {"table": "notes", "verdict": VERDICT_OK}]
    carry = DamageRegistry._carry_after
    assert carry({verify.PAGES_ENTRY}, ok, listed=True, damaged=set()) == [verify.PAGES_ENTRY], "a run with no pass cleared (pages)"
    assert carry({verify.PAGES_ENTRY}, [*ok, {"table": verify.PAGES_ENTRY, "verdict": VERDICT_OK}], listed=True, damaged=set()) == []
    assert carry({verify.PAGES_ENTRY}, [*ok, {"table": verify.PAGES_ENTRY, "verdict": VERDICT_UNCHECKED}], listed=True, damaged=set()) == [
        verify.PAGES_ENTRY
    ]
    assert carry({verify.PAGES_ENTRY, "articles"}, ok, listed=True, damaged=set()) == [verify.PAGES_ENTRY]
    assert carry({verify.PAGES_ENTRY}, [], listed=False, damaged=set()) == [verify.PAGES_ENTRY]


def test_a_start_of_collection_reads_the_pages_too_and_pages_that_still_fail_keep_the_latch(tmp_path, unchecked, files, monkeypatch):
    _run(files, unchecked, monkeypatch)
    assert damage.registry.latched(FILE_CORPUS)
    assert damage.retry_for_collection_start("the network toggle went online") == []
    assert damage.registry.latched(FILE_CORPUS), "the latch was dropped while the pages were being read"
    _join_rechecks()
    assert damage.registry.latched(FILE_CORPUS), "pages that still fail released the latch"
    entry = damage.registry.state(detail=True)["verification"][FILE_CORPUS]
    assert _by_table(entry)[verify.PAGES_ENTRY]["verdict"] == VERDICT_DAMAGED and entry["rechecked_at"]


def test_a_start_of_collection_releases_the_latch_when_the_pages_pass_and_the_tables_read_clean(tmp_path, base, unchecked, files, monkeypatch):
    _run(files, unchecked, monkeypatch)
    shutil.copy(base, unchecked)  # the file is replaced in place, as a repair or a restore would
    assert damage.retry_for_collection_start("the network toggle went online") == []
    _join_rechecks()
    assert not damage.registry.latched(FILE_CORPUS), "pages that pass and tables that read clean did not release the latch"
    entry = damage.registry.state(detail=True)["verification"][FILE_CORPUS]
    assert _by_table(entry)[verify.PAGES_ENTRY]["verdict"] == VERDICT_OK and entry["rechecked_at"]
    assert sg.StorageGuard().admit() is None


def test_a_re_read_of_tables_that_read_clean_does_not_release_a_latch_whose_pages_still_fail(tmp_path, unchecked, files, monkeypatch):
    """The latch names ``notes`` (which reads ok) and ``(pages)``: the pages were not found by any table, so only the pass can answer
    for them, and a re-read that treated ``(pages)`` as a table "no longer in the file" would release the latch."""
    files[FILE_CORPUS] = unchecked
    damage.registry._note_verified_damage(FILE_CORPUS, ["notes", verify.PAGES_ENTRY], path=unchecked, at="2026-10-06T02:00:00+00:00")
    assert damage.registry.latched(FILE_CORPUS)
    assert damage.retry_for_collection_start("the network toggle went online") == []
    _join_rechecks()
    assert damage.registry.latched(FILE_CORPUS), "(pages) was answered by its absence from the table list"
    assert damage.registry.state(detail=True)["files"][FILE_CORPUS]["check_tables"] == [verify.PAGES_ENTRY]


def test_the_module_declares_what_it_measured():
    doc = verify.__doc__ or ""
    assert "MEASURED 2026-10-06" in doc and "234 MB" in doc and "cipher_integrity_check" in doc
    assert verify.MAX_PAGES_LISTED == 32
