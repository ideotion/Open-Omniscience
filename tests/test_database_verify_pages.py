"""The page pass of an encrypted file (damaged-database plan, slice E2b).

Measured on real SQLCipher stores (see ``src/database/verify.py``): a page that fails its authentication tag makes the per-table
``quick_check`` either answer a row (filed ``damaged``) or raise the driver's generic ``SQLITE_ERROR`` (filed ``unchecked``): of
40 single pages overwritten on a 500-article store, 10 files came out damaged and 30 unchecked, and ``PRAGMA
cipher_integrity_check`` named the page in every one of them. E2b asks that pragma once, and only after such an ``unchecked``.

Every claim here is made against REAL encrypted files damaged the way a bad sector damages them (one whole page overwritten with
random bytes), through the real check, the real registry and the real re-read; only the answers the driver cannot be made to give
on demand (a build without the pragma, a disk error in the middle of a pass, a million failing pages) are stood in for, and said:

  * the pass runs after the generic error on an ENCRYPTED file and after nothing else (a healthy file, a wrong passphrase and a busy
    file never reach it) and names the page that was overwritten; a disk error on a page IS answered by the pass as a row, never
    raised (measured with a ``pread`` that returned EIO), and is counted apart from a page that failed, never filed as damage;
  * a table that did not answer STAYS unchecked: a clean pass never makes a file clean;
  * a pass that cannot be made (no such pragma in this build, a stop, a driver error) is ``unchecked`` with the reason, and the
    connection it used is closed on every path;
  * the page list is capped and the count is not; an answer the pass cannot read is damage, never a clean file;
  * the finding rides the record, the incident and the latch like a table's; the next start and a start of collection ask again, and
    only a pass that reads ``ok`` clears it;
  * a quit while the pass runs (it cannot be interrupted, and its thread is a daemon) gives the attempt back at the stop.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import random
import shutil
import sqlite3
import threading
import types
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


def _find_page(base: Path, tmp_path_factory, want: str, *, code: int | None, required: bool = True) -> int | None:
    """A page of ``articles`` whose overwriting makes its table check answer ``want`` (with the driver code ``code``), found by trying
    pages in a seeded order: which pages do which is the driver's business, so the test asks it instead of assuming. ``None`` (or a
    failure when ``required``) when the installed engine has no such page."""
    work = tmp_path_factory.mktemp("find") / "w.db"
    n = os.path.getsize(base) // PAGE
    for pg in random.Random(5).sample(range(2, n + 1), n - 1):
        shutil.copy(base, work)
        _overwrite(work, pg)
        r = verify.check_table(work, "articles")
        if r["verdict"] == want and r.get("sqlite_code") == code:
            return pg
    if required:
        pytest.fail(f"no page of the articles table made its check answer {want} (code {code})")
    return None


@pytest.fixture(scope="module")
def real_unchecked_page(base, tmp_path_factory) -> int | None:
    """A page whose damage makes THIS engine's table check raise the generic error (SQLCipher 4.12 does for most leaf pages), or ``None``:
    SQLCipher 4.19 (sqlcipher3 0.6.4) answers ``damaged`` for every page it can read a row for and has no such page
    (``docs/ledger/OPEN_QUEUE.md``, the sqlcipher3 qualification)."""
    return _find_page(base, tmp_path_factory, VERDICT_UNCHECKED, code=1, required=False)


@pytest.fixture(scope="module")
def unchecked_page(base, tmp_path_factory, real_unchecked_page) -> int:
    if real_unchecked_page is not None:
        return real_unchecked_page
    return _find_page(base, tmp_path_factory, VERDICT_DAMAGED, code=None)  # any page: the generic error is stood in below


@pytest.fixture(scope="module")
def damaged_page(base, tmp_path_factory) -> int:
    return _find_page(base, tmp_path_factory, VERDICT_DAMAGED, code=None)


def _stand_in_the_generic_error(monkeypatch, damaged_copy: Path) -> None:
    """On an engine whose table check never raises the generic error (SQLCipher 4.19), make it do so, for THIS file only: the rest of the
    pass (the page check, the second read, the registry, the re-read) runs for real on the real damaged file. Said here and nowhere else:
    the answer is the driver's, produced by hand, because the engine no longer produces it on demand."""
    sha = H.sha(damaged_copy)
    real_open = verify._open

    class _Con:
        def __init__(self, con):
            self._con = con

        def execute(self, sql, *args, **kwargs):
            if str(sql).lstrip().upper().startswith("PRAGMA QUICK_CHECK") and "articles" in str(sql).lower():  # the damaged table only
                raise _driver_error("SQL logic error", 1)
            return self._con.execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._con, name)

    def opener(path):
        con = real_open(path)
        try:
            same = H.sha(path) == sha
        except OSError:
            same = False
        return _Con(con) if same else con

    monkeypatch.setattr(verify, "_open", opener)


@pytest.fixture
def healthy(tmp_path, base) -> Path:
    path = tmp_path / "healthy.db"  # its own name: a test may hold a damaged copy beside it
    shutil.copy(base, path)
    return path


@pytest.fixture
def unchecked(tmp_path, base, unchecked_page, real_unchecked_page, monkeypatch) -> Path:
    """A copy with one page overwritten that the table check cannot answer for (on an engine that answers it for every readable page, the
    generic error is stood in for this file: :func:`_stand_in_the_generic_error`)."""
    path = tmp_path / "corpus.db"
    shutil.copy(base, path)
    _overwrite(path, unchecked_page)
    if real_unchecked_page is None:
        _stand_in_the_generic_error(monkeypatch, path)
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


def test_the_floor_leg_still_has_a_real_unchecked_page(real_unchecked_page):
    """THE FLOOR LEG'S GUARD: ``real_unchecked_page`` falls back to a stand-in when the engine has none, so the blocking floor leg would pass
    without ever running the real ``unchecked`` path. The ``sqlcipher-engines`` job sets ``OO_EXPECT_SQLCIPHER_ENGINE=floor`` there."""
    if os.environ.get("OO_EXPECT_SQLCIPHER_ENGINE") != "floor":
        pytest.skip("not the floor leg of the sqlcipher-engines job")
    assert real_unchecked_page is not None, "the floor engine no longer gives a page whose table check answers unchecked (generic error)"


def test_the_engines_answers_for_a_damaged_page_are_the_ones_the_module_knows(base, tmp_path):
    """The qualification of a new engine, as a test: every page of ``articles`` overwritten, one at a time, and the table check answers
    ``damaged``, ``ok`` (a page nothing reads) or ``unchecked`` WITH the generic code, never a third thing. SQLCipher 4.12 answers
    ``unchecked`` for most leaf pages; 4.19 answers ``damaged`` for them (measured 2026-10-13: 53 of 69 against 0). A new engine that
    answers something else fails here, by name, before it fails in a user's damaged file."""
    work = tmp_path / "w.db"
    n = os.path.getsize(base) // PAGE
    seen: dict[tuple[str, int | None], int] = {}
    for pg in range(2, n + 1):
        shutil.copy(base, work)
        _overwrite(work, pg)
        r = verify.check_table(work, "articles")
        key = (r["verdict"], r.get("sqlite_code"))
        seen[key] = seen.get(key, 0) + 1
    allowed = {(VERDICT_DAMAGED, None), (VERDICT_OK, None), (VERDICT_UNCHECKED, 1)}
    assert set(seen) <= allowed, f"the engine answered something the module does not know: {sorted(seen.items(), key=str)}"
    assert seen.get((VERDICT_DAMAGED, None), 0) > 0, "no overwritten page was filed damaged: the check reads nothing"
    assert seen.get((VERDICT_OK, None), 0) == 1, f"exactly one page (a page nothing reads) may leave the table check ok; an engine that stopped detecting damage fails here: {seen}"


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
    # a damaged answer is read AGAIN on a new connection (here the opener hands out the same stand-in), each pass closing its own
    passes = 2 if verdict == VERDICT_DAMAGED else 1
    assert con.closed == passes, "a pass's connection was not closed exactly once"
    assert con.statements == ["PRAGMA cipher_integrity_check"] * passes


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
    out = verify.confirm_encrypted_damage(unchecked)
    # the file is damaged, so the pass is read again on a new connection: both opens are read-only
    assert out["verdict"] == VERDICT_DAMAGED and seen == ["True", "True"], "the pass opened the file for writing"


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


# --------------------------------------------------------------------------- #
#  the deep delta read of E2b: an I/O error, a quit during the pass, the survivors of 18 mutants
# --------------------------------------------------------------------------- #
EIO_ROW = "error reading 16384 bytes from file page 40 at offset 638976"  # the driver's own row, measured with a pread that returned EIO
#: The same row for a page at 2 GiB or later: SQLCipher prints the offset through a 32-bit ``%d``, so it is NEGATIVE (measured on a 3 GiB store
#: with EIO at page 140000; the coordinator's check of E2).
EIO_ROW_PAST_2_GIB = "error reading 16384 bytes from file page 140000 at offset -2001223680"


@pytest.mark.parametrize(
    "line",
    [
        EIO_ROW,
        EIO_ROW_PAST_2_GIB,
        "HMAC operation failed for page 3",
        "HMAC is not enabled, unable to integrity check",
        "database file is undefined",
    ],
)
def test_a_row_that_says_the_pass_could_not_read_is_unchecked_never_damage(line):
    """The deep read's F1: a disk error on a page is ANSWERED as a row by the pass (it does not raise), and filing it ``damaged`` made
    an I/O error a verdict on the file (and, with the repair, a reason to replace it): not reading is not a verdict."""
    entry = verify.confirm_encrypted_damage(Path("x.db"), opener=lambda p: _Rows(rows=[(line,)]))
    assert entry["verdict"] == VERDICT_UNCHECKED, entry
    assert entry["pages_unread"] == 1 and "pages" not in entry and "pages_total" not in entry
    assert "could not read 1 page(s)" in entry["detail"][0] and entry["detail"][1] == line


def test_a_page_the_pass_could_not_read_beside_a_page_that_failed_is_counted_and_never_dropped():
    rows = [("HMAC verification failed for page 7",), (EIO_ROW,), ("HMAC operation failed for page 9",)]
    entry = verify.confirm_encrypted_damage(Path("x.db"), opener=lambda p: _Rows(rows=rows))
    assert entry["verdict"] == VERDICT_DAMAGED and entry["pages"] == [7] and entry["pages_total"] == 1, "an unread page was counted as failing"
    assert entry["pages_unread"] == 2, "the pages that could not be read vanished from the record"
    assert "7" in entry["detail"][0] and "2 page(s) could not be read" in entry["detail"][1] and EIO_ROW in entry["detail"][1]


def test_a_read_error_past_2_gib_beside_a_failing_page_is_unread_not_unknown():
    rows = [("HMAC verification failed for page 7",), (EIO_ROW_PAST_2_GIB,)]
    entry = verify.confirm_encrypted_damage(Path("x.db"), opener=lambda p: _Rows(rows=rows))
    assert entry["pages_unread"] == 1 and "strange_rows" not in entry, "a negative offset made the row an unknown one, which is damage"
    assert entry["pages"] == [7]


def test_a_row_the_pass_does_not_know_beside_unread_pages_is_still_damage_in_its_own_words():
    rows = [(EIO_ROW,), ("something this app has never seen",)]
    entry = verify.confirm_encrypted_damage(Path("x.db"), opener=lambda p: _Rows(rows=rows))
    assert entry["verdict"] == VERDICT_DAMAGED and entry["pages"] == [] and entry["pages_unread"] == 1
    assert entry["detail"][0] == "something this app has never seen"


def test_a_pass_of_unread_pages_files_the_file_unchecked_and_latches_nothing(tmp_path, unchecked, files, monkeypatch):
    monkeypatch.setattr(verify, "confirm_encrypted_damage", lambda path, **kw: {
        "table": verify.PAGES_ENTRY, "verdict": VERDICT_UNCHECKED, "seconds": 0.0, "detail": [EIO_ROW], "pages_unread": 1,
    })
    _run(files, unchecked, monkeypatch)
    entry = _record(tmp_path)["verification"][FILE_CORPUS]
    assert entry["verdict"] == VERDICT_UNCHECKED and _by_table(entry)[verify.PAGES_ENTRY]["pages_unread"] == 1
    assert not damage.registry.latched(FILE_CORPUS), "a read the pass could not make latched the file"


def test_the_non_hmac_rows_are_capped_in_the_record_and_counted():
    unread = [(f"error reading 16384 bytes from file page {n} at offset {n * 16384}",) for n in range(1, 5001)]
    entry = verify.confirm_encrypted_damage(Path("x.db"), opener=lambda p: _Rows(rows=unread))
    assert entry["pages_unread"] == 5000 and len(entry["detail"]) <= verify.DETAIL_LINES
    assert len(json.dumps(entry)) < 1024, "a drive that fails every page made the record a line per page"
    strange = [(f"something new {n}",) for n in range(5000)]
    entry = verify.confirm_encrypted_damage(Path("x.db"), opener=lambda p: _Rows(rows=strange))
    assert entry["verdict"] == VERDICT_DAMAGED and len(entry["detail"]) == verify.DETAIL_LINES and len(json.dumps(entry)) < 1024
    assert entry["strange_rows"] == 5000, "the cut shrank what is printed AND what is counted"


def test_unknown_rows_beside_a_failing_page_and_unread_pages_are_counted_though_the_detail_is_cut():
    """The coordinator's check of E2, item 3: ``lines[:DETAIL_LINES]`` dropped the unknown rows that sit beside a failing page once the unread
    line was present, and nothing counted them (the maintainer's ruling of 2026-09-11: a cap may shrink what is printed, never what is counted)."""
    rows = [("HMAC verification failed for page 7",), (EIO_ROW,), (EIO_ROW_PAST_2_GIB,)] + [(f"something new {n}",) for n in range(5)]
    entry = verify.confirm_encrypted_damage(Path("x.db"), opener=lambda p: _Rows(rows=rows))
    assert entry["verdict"] == VERDICT_DAMAGED and entry["pages"] == [7] and entry["pages_total"] == 1
    assert entry["pages_unread"] == 2 and entry["strange_rows"] == 5, entry
    assert len(entry["detail"]) == verify.DETAIL_LINES and "something new 0" in entry["detail"][2]


def test_the_kept_lines_are_bounded_and_the_count_is_not():
    kept = verify._Kept(3)
    for n in range(10_000):
        kept.add(f"row {n}")
    assert kept.count == 10_000 and kept.lines == ["row 0", "row 1", "row 2"]


def test_the_page_pass_limit_is_exactly_four_gib():
    assert verify.PAGE_PASS_LIMIT_BYTES == 1 << 32


class _PragmaCon:
    """A stand-in connection for a pass that is asked two things: the cipher settings (the SQLCipher 4 defaults) and the pragma (the rows it
    is given). The sizes it is built with are the real file's, so the own check can run on the real file beside it."""

    SETTINGS = {
        "cipher_page_size": "16384",
        "cipher_kdf_algorithm": "PBKDF2_HMAC_SHA512",
        "cipher_hmac_algorithm": "HMAC_SHA512",
        "kdf_iter": "256000",
        "cipher_use_hmac": "1",
        "cipher_plaintext_header_size": "0",
        "cipher_hmac_salt_mask": "3a",
        "cipher_hmac_pgno": "le",
    }

    def __init__(self, rows=(), settings=None):
        self.rows, self.closed = rows, 0
        self.settings = {**self.SETTINGS, **(settings or {})}

    def execute(self, sql, *args):
        text = str(sql)
        if "cipher_integrity_check" in text:
            return _Cursor(self.rows)
        value = self.settings.get(text.removeprefix("PRAGMA ").strip())
        return types.SimpleNamespace(fetchone=lambda: None if value is None else (value,))

    def close(self):
        self.closed += 1


def _past_the_limit(monkeypatch, path: Path) -> int:
    """Make ``path`` 'longer than 4 GiB' by lowering the limit under its real length; returns the length."""
    size = path.stat().st_size
    monkeypatch.setattr(verify, "PAGE_PASS_LIMIT_BYTES", size - 1)
    return size


def test_a_file_longer_than_the_limit_is_given_to_the_own_check_and_one_of_exactly_the_limit_to_the_pragma(healthy, monkeypatch):
    """The boundary is a page that STARTS at 2^32: a file of exactly 2^32 bytes ends there and is still the pragma's. The same real file is
    answered by each, so the entry's ``method`` says which (only the own check carries one)."""
    size = healthy.stat().st_size
    monkeypatch.setattr(verify, "PAGE_PASS_LIMIT_BYTES", size)
    exact = verify.confirm_encrypted_damage(healthy)
    assert exact["verdict"] == VERDICT_OK and "method" not in exact and "file_bytes" not in exact, exact
    monkeypatch.setattr(verify, "PAGE_PASS_LIMIT_BYTES", size - 1)
    over = verify.confirm_encrypted_damage(healthy)
    assert over["verdict"] == VERDICT_OK and over["method"] == "own-tag-check" and over["file_bytes"] == size, over
    assert over["pages_checked"] == size // PAGE, "every page of the file was judged"


def test_a_page_past_the_limit_is_named_as_the_pragma_names_it_and_confirmed_by_a_second_read(damaged, damaged_page, monkeypatch):
    """The same damaged file, answered by the pragma and by the own check: the same pages and the same count, in the same entry shape."""
    by_pragma = verify.confirm_encrypted_damage(damaged)
    _past_the_limit(monkeypatch, damaged)
    by_own = verify.confirm_encrypted_damage(damaged)
    assert by_own["verdict"] == VERDICT_DAMAGED and by_own["method"] == "own-tag-check", by_own
    assert by_own["pages"] == by_pragma["pages"] == [damaged_page] and by_own["pages_total"] == by_pragma["pages_total"] == 1
    assert by_own["second_read"] == verify.SECOND_READ_AGREED, "a damaged answer stands only when a second pass agrees (R100)"
    assert by_own["detail"][0] == by_pragma["detail"][0] and verify._TAG_ON_BIG_FILE in by_own["detail"]


def test_the_own_check_files_what_a_scripted_second_read_did_not_repeat_as_unchecked(healthy, monkeypatch):
    """R100 holds past 4 GiB: damage the first pass reported and the second did not is ``unchecked`` with the first read's line kept."""
    _past_the_limit(monkeypatch, healthy)
    answers = iter(
        [
            {"state": "checked", "failing": 2, "pages": [7, 9], "unread": 0, "examined": 300, "pages_in_file": 300, "trailing_bytes": 0, "file_bytes": 1, "failure": None},
            {"state": "checked", "failing": 0, "pages": [], "unread": 0, "examined": 300, "pages_in_file": 300, "trailing_bytes": 0, "file_bytes": 1, "failure": None},
        ]
    )
    monkeypatch.setattr(verify.page_auth, "check_path", lambda *a, **k: next(answers))
    entry = verify.confirm_encrypted_damage(healthy)
    assert entry["verdict"] == VERDICT_UNCHECKED and entry["second_read"] == verify.SECOND_READ_CLEAN, entry
    assert "2 page(s) failed" in entry["first_read"][0] and entry["detail"] == [verify._DIFFERENTLY[: verify.DETAIL_CHARS]]


_CHECKED = {
    "state": "checked", "failing": 0, "pages": [], "unread": 0, "examined": 299, "lock_byte_page": 65_537, "pages_in_file": 300, "trailing_bytes": 0,
    "file_bytes": 4_900_000, "failure": None,
}


@pytest.mark.parametrize(
    ("found", "verdict", "needle"),
    [
        ({**_CHECKED, "state": "mismatch", "failing": 1, "pages": [1]}, VERDICT_UNCHECKED, "did not match this file's first page"),
        ({**_CHECKED, "state": "no-key", "examined": 0}, VERDICT_UNCHECKED, "no passphrase is held"),
        ({**_CHECKED, "state": "stopped", "examined": 12}, VERDICT_UNCHECKED, "the check was stopped"),
        ({**_CHECKED, "state": "unreadable", "failure": "OSError EIO"}, VERDICT_UNCHECKED, "OSError EIO"),
        ({**_CHECKED, "state": "unreadable"}, VERDICT_UNCHECKED, "a short read"),
        ({**_CHECKED, "unread": 3, "examined": 297, "failure": "OSError EIO"}, VERDICT_UNCHECKED, "could not read 3 page(s)"),
        ({**_CHECKED, "failing": 40, "pages": list(range(10, 42)), "unread": 2, "failure": "OSError EIO"}, VERDICT_DAMAGED, "40 page(s) failed"),
        (_CHECKED, VERDICT_OK, "no page of the file failed"),
    ],
)
def test_every_state_of_the_own_check_is_one_entry_that_is_never_damage_unless_a_page_failed(healthy, monkeypatch, found, verdict, needle):
    _past_the_limit(monkeypatch, healthy)
    monkeypatch.setattr(verify.page_auth, "check_path", lambda *a, **k: found)
    first = verify._page_pass(healthy)
    assert first["verdict"] == verdict and first["method"] == "own-tag-check" and needle in " | ".join(first["detail"]), first
    assert len(first["detail"]) <= verify.DETAIL_LINES and all(len(d) <= verify.DETAIL_CHARS for d in first["detail"])
    if verdict != VERDICT_DAMAGED:
        assert "pages" not in first and "pages_total" not in first, "only a failing page is a finding"
    if found["unread"]:
        assert first["pages_unread"] == found["unread"], "what was counted stays in the record"
    assert first["lock_byte_page"] == 65_537, "the one page that was not judged is said, whatever the verdict"
    if verdict == VERDICT_DAMAGED:
        assert first["pages"] == found["pages"] and first["pages_total"] == 40 and "…" not in first["detail"][0]
        assert first["detail"][0].endswith("and more"), "eight numbers are shown and the rest is said"


def test_a_calibration_that_disagrees_is_unchecked_with_the_reason_and_nothing_latches(tmp_path, healthy, files, monkeypatch):
    """A key that does not match the file (here the key of another file's salt): the check says the METHOD did not match, files nothing as
    damaged, runs no second read, and the file is not latched."""
    _past_the_limit(monkeypatch, healthy)
    real = verify.page_auth.derive_tag_key
    monkeypatch.setattr(verify.page_auth, "derive_tag_key", lambda salt: real(bytes(16)))
    direct = verify.confirm_encrypted_damage(healthy)
    assert direct["verdict"] == VERDICT_UNCHECKED and direct["detail"] == [verify._TAG_MISMATCH] and "second_read" not in direct, direct
    monkeypatch.setattr(verify, "inspect_file", lambda path, opener=None: {"error": (VERDICT_UNCHECKED, "OperationalError"), "sqlite_code": 1})
    _run(files, healthy, monkeypatch)
    entry = _record(tmp_path)["verification"][FILE_CORPUS]
    assert entry["verdict"] == VERDICT_UNCHECKED and "did not match" in entry["reason"], entry
    assert not damage.registry.latched(FILE_CORPUS)


def test_settings_the_check_was_not_measured_on_are_refused_before_the_file_is_read(healthy, monkeypatch):
    _past_the_limit(monkeypatch, healthy)
    called: list[object] = []
    monkeypatch.setattr(verify.page_auth, "check_path", lambda *a, **k: called.append(a))
    con = _PragmaCon(settings={"cipher_kdf_algorithm": "PBKDF2_HMAC_SHA1"})
    entry = verify.confirm_encrypted_damage(healthy, opener=lambda p: con)
    assert entry["verdict"] == VERDICT_UNCHECKED and entry["detail"][0].endswith("so its pages were not checked"), entry
    assert called == [] and con.closed == 1, "the connection was closed before anything else, and the file was not read"


def test_a_missing_passphrase_is_named_and_the_connection_is_closed_before_the_read(healthy, monkeypatch):
    _past_the_limit(monkeypatch, healthy)
    con = _PragmaCon()
    monkeypatch.setattr(connect_mod, "_passphrase", None)
    entry = verify.confirm_encrypted_damage(healthy, opener=lambda p: con)
    assert entry["verdict"] == VERDICT_UNCHECKED and entry["detail"] == [verify._TAG_NO_KEY] and con.closed == 1, entry


def test_a_connection_that_cannot_be_opened_is_classified_as_any_pass_is(healthy, monkeypatch):
    _past_the_limit(monkeypatch, healthy)

    def refuse(path):
        raise _driver_error("database is locked", 5)

    entry = verify.confirm_encrypted_damage(healthy, opener=refuse)
    assert entry["verdict"] == VERDICT_UNCHECKED and entry["detail"] == ["the file was busy"] and entry["method"] == "own-tag-check", entry


def test_a_stop_asked_for_before_the_pass_ends_it_before_anything_is_opened(healthy, monkeypatch):
    _past_the_limit(monkeypatch, healthy)
    opened: list[object] = []
    stop = threading.Event()
    stop.set()
    entry = verify.confirm_encrypted_damage(healthy, opener=lambda p: opened.append(p), cancel=stop)
    assert entry["verdict"] == VERDICT_UNCHECKED and opened == [], entry


def test_the_reasons_the_own_check_gives_survive_the_cut_to_a_detail_line():
    """``entry()`` cuts every detail at ``DETAIL_CHARS``; the half of each sentence that matters is its end."""
    for reason in (verify._TAG_MISMATCH, verify._TAG_NO_KEY, verify._TAG_ON_BIG_FILE, verify._TAG_CLEAN):
        assert len(reason) < verify.DETAIL_CHARS, reason
    assert verify._TAG_MISMATCH.endswith("were not checked") and verify._TAG_NO_KEY.endswith("were not checked")


def test_a_file_that_crossed_4_gib_while_the_pragma_ran_drops_its_rows_and_is_answered_by_the_own_check(healthy, monkeypatch):
    """The pragma's rows are about wrong bytes once the file is past 2^32 (here a false failing page and an unknown row): they are dropped,
    and the app's own check of the real file answers instead."""
    sizes = iter([100, 10**10])
    monkeypatch.setattr(verify, "PAGE_PASS_LIMIT_BYTES", 1000)
    monkeypatch.setattr(verify, "_size_of", lambda path: next(sizes))
    rows = [("HMAC verification failed for page 262145",), ("something this app has never seen",)]
    entry = verify.confirm_encrypted_damage(healthy, opener=lambda p: _PragmaCon(rows=rows))
    assert entry["verdict"] == VERDICT_OK and entry["method"] == "own-tag-check", entry
    assert "pages" not in entry and "pages_total" not in entry and "strange_rows" not in entry, "the rows of a pass past 4 GiB were kept"


def test_the_kept_lines_of_the_pass_are_bounded_by_the_detail_lines(monkeypatch):
    """A ``_Kept(10**9)`` would keep a second copy of every unknown row of a pass in which every row is unknown: the limit each is made with is pinned."""
    made: list[int] = []

    class Spy(verify._Kept):
        def __init__(self, limit: int) -> None:
            made.append(limit)
            super().__init__(limit)

    monkeypatch.setattr(verify, "_Kept", Spy)
    verify.confirm_encrypted_damage(Path("x.db"), opener=lambda p: _Rows(rows=[(EIO_ROW,), ("something new",)]))
    assert made and set(made) == {verify.DETAIL_LINES}, made


def test_a_table_list_that_cannot_be_read_beside_a_pass_that_could_not_read_keeps_the_unread_count_as_a_number(tmp_path, healthy, files, monkeypatch):
    """The coordinator's check of E2, item 3, the unchecked error branch: ``pages_unread`` was only words inside ``reason`` there."""
    monkeypatch.setattr(verify, "inspect_file", lambda path, opener=None: {"error": (VERDICT_UNCHECKED, "OperationalError"), "sqlite_code": 1})
    monkeypatch.setattr(
        verify,
        "confirm_encrypted_damage",
        lambda path, **kw: {"table": verify.PAGES_ENTRY, "verdict": VERDICT_UNCHECKED, "seconds": 0.0, "detail": [EIO_ROW], "pages_unread": 2},
    )
    _run(files, healthy, monkeypatch)
    entry = _record(tmp_path)["verification"][FILE_CORPUS]
    assert entry["verdict"] == VERDICT_UNCHECKED and entry["tables"] == []
    assert entry["pages_unread"] == 2, "the count of pages the drive could not give was kept only as text"
    assert not damage.registry.latched(FILE_CORPUS)


def test_a_table_list_that_cannot_be_read_on_a_file_past_4_gib_says_what_the_own_check_found(tmp_path, healthy, files, monkeypatch):
    """The unreadable-table-list branch pastes the pass's reason into its own; with the limit made small the real file is 'past 4 GiB'.
    The own check read every page and none failed, so the file is neither called clean (the list was not read) nor damaged."""
    _past_the_limit(monkeypatch, healthy)
    monkeypatch.setattr(verify, "inspect_file", lambda path, opener=None: {"error": (VERDICT_UNCHECKED, "OperationalError"), "sqlite_code": 1})
    _run(files, healthy, monkeypatch)
    entry = _record(tmp_path)["verification"][FILE_CORPUS]
    assert entry["verdict"] == VERDICT_UNCHECKED and entry["tables"] == []
    assert "OperationalError" in entry["reason"] and "no page of the file failed" in entry["reason"], entry["reason"]
    assert not damage.registry.latched(FILE_CORPUS)


def test_a_table_list_that_cannot_be_read_on_a_damaged_file_past_4_gib_files_the_named_page_and_latches(tmp_path, damaged, damaged_page, files, monkeypatch):
    _past_the_limit(monkeypatch, damaged)
    monkeypatch.setattr(verify, "inspect_file", lambda path, opener=None: {"error": (VERDICT_UNCHECKED, "OperationalError"), "sqlite_code": 1})
    _run(files, damaged, monkeypatch)
    entry = _record(tmp_path)["verification"][FILE_CORPUS]
    pages = _by_table(entry)[verify.PAGES_ENTRY]
    assert entry["verdict"] == VERDICT_DAMAGED and pages["pages"] == [damaged_page] and pages["method"] == "own-tag-check", entry
    assert pages["second_read"] == verify.SECOND_READ_AGREED and damage.registry.latched(FILE_CORPUS)


@pytest.mark.parametrize(("message", "code", "verdict"), [("database disk image is malformed", 11, VERDICT_DAMAGED), ("database is locked", 5, VERDICT_UNCHECKED)])
def test_a_pass_that_raises_takes_its_verdict_from_the_class_of_the_error_as_a_table_does(message, code, verdict):
    """The pass's own open or statement can raise corruption (the tables are then damaged too); it must not read ``unchecked``."""
    entry = verify.confirm_encrypted_damage(Path("x.db"), opener=lambda p: _Rows(boom=_driver_error(message, code)))
    assert entry["verdict"] == verdict, entry


def test_a_pass_that_cannot_be_made_for_a_list_that_could_not_be_read_files_nothing_as_damaged(tmp_path, healthy, files, monkeypatch):
    """The survivor M02: after an unreadable table list an ``unchecked`` pass was filed ``damaged`` with a ``(schema)`` entry and a latch."""
    monkeypatch.setattr(verify, "inspect_file", lambda path, opener=None: {"error": (VERDICT_UNCHECKED, "OperationalError"), "sqlite_code": 1})
    monkeypatch.setattr(verify, "cipher_check_present", lambda: False)
    _run(files, healthy, monkeypatch)
    entry = _record(tmp_path)["verification"][FILE_CORPUS]
    assert entry["verdict"] == VERDICT_UNCHECKED and entry["tables"] == [], entry
    assert verify.SCHEMA_ENTRY not in {t["table"] for t in entry["tables"]}
    assert "no page-authentication check" in entry["reason"]
    assert not damage.registry.latched(FILE_CORPUS), "an unchecked pass latched the file"


def test_a_pages_finding_beside_index_only_damage_is_data_scope_not_a_search_index_one():
    """The survivor M01: ``(pages)`` is no table of the search index, so damage that names it is not index-only damage."""
    reg = DamageRegistry(path_fn=lambda: Path(os.devnull))
    reg._note_verified_damage(FILE_CORPUS, ["article_fts_data", verify.PAGES_ENTRY], path=None, at="2026-10-06T02:00:00+00:00")
    assert reg.state(detail=True)["files"][FILE_CORPUS]["scope"] == SCOPE_DATA
    only = DamageRegistry(path_fn=lambda: Path(os.devnull))
    only._note_verified_damage(FILE_CORPUS, ["article_fts_data", "article_fts_idx"], path=None, at="2026-10-06T02:00:00+00:00")
    assert only.state(detail=True)["files"][FILE_CORPUS]["scope"] == damage.SCOPE_SEARCH_INDEX, "the test cannot tell the two apart"


def _latch_a_table_then_swap_in(files, healthy, damaged_source, monkeypatch, *, tables):
    """A clean run (no pass owed, so no ``(pages)`` entry), then the file is replaced by one whose ``articles`` raise the generic error and
    a table of it is latched: what a re-read of a latch finds."""
    _run(files, healthy, monkeypatch)
    assert verify.PAGES_ENTRY not in _by_table(damage.registry.state(detail=True)["verification"][FILE_CORPUS])
    shutil.copy(damaged_source, healthy)
    damage.registry._note_verified_damage(FILE_CORPUS, tables, path=healthy, at="2026-10-06T02:00:00+00:00")
    assert damage.registry.latched(FILE_CORPUS)
    assert damage.retry_for_collection_start("the network toggle went online") == []
    _join_rechecks()


def test_a_re_read_whose_table_raises_the_generic_error_asks_the_pass_and_the_pages_join_the_latch(tmp_path, healthy, unchecked, unchecked_page, files, monkeypatch):
    """The survivor M03: the re-read asked the pass only when an earlier ``(pages)`` was owed, never for a table that raised the code."""
    _latch_a_table_then_swap_in(files, healthy, unchecked, monkeypatch, tables=["articles"])
    entry = damage.registry.state(detail=True)["verification"][FILE_CORPUS]
    assert _by_table(entry)[verify.PAGES_ENTRY]["pages"] == [unchecked_page], entry
    assert damage.registry.latched(FILE_CORPUS)
    assert damage.registry.state(detail=True)["files"][FILE_CORPUS]["check_tables"] == [verify.PAGES_ENTRY, "articles"]


def test_a_re_read_whose_pass_could_not_be_made_still_records_that_in_the_entry(tmp_path, healthy, unchecked, files, monkeypatch):
    """The survivor M15: an ``unchecked`` pass of a re-read was dropped, so the record said nothing of it."""
    monkeypatch.setattr(verify, "cipher_check_present", lambda: False)
    _latch_a_table_then_swap_in(files, healthy, unchecked, monkeypatch, tables=["articles"])
    entry = damage.registry.state(detail=True)["verification"][FILE_CORPUS]
    assert _by_table(entry)[verify.PAGES_ENTRY]["verdict"] == VERDICT_UNCHECKED, entry
    assert damage.registry.latched(FILE_CORPUS), "a pass that could not be made released the latch"


# --- a quit while the page pass runs (F2) ---------------------------------------------------------------------------
def _blocking_pass(monkeypatch, *, entered, release, table_seen=None):
    def slow(path, **kw):
        if table_seen is not None:
            table_seen.append((damage.registry.state(detail=True).get("verifying") or {}).get("table"))
        entered.set()
        assert release.wait(60), "the test never let the pass end"
        return {"table": verify.PAGES_ENTRY, "verdict": VERDICT_UNCHECKED, "seconds": 0.0, "detail": ["released"]}

    monkeypatch.setattr(verify, "confirm_encrypted_damage", slow)


@pytest.mark.parametrize("list_readable", [True, False])
def test_a_quit_during_the_pass_gives_the_attempt_back_at_the_stop_and_once(tmp_path, unchecked, files, monkeypatch, list_readable):
    """The deep read's F2: the pass is one C call and its thread is a daemon, so nothing after the call runs at a quit; three quits in
    the pass spent the file's three attempts, and the next start skipped the check with no finding recorded."""
    if not list_readable:
        monkeypatch.setattr(verify, "inspect_file", lambda path, opener=None: {"error": (VERDICT_UNCHECKED, "OperationalError"), "sqlite_code": 1})
    entered, release = threading.Event(), threading.Event()
    seen: list = []
    _blocking_pass(monkeypatch, entered=entered, release=release, table_seen=seen)
    gave: list[str] = []
    real = damage.registry.verification_file_stopped
    monkeypatch.setattr(damage.registry, "verification_file_stopped", lambda key: (gave.append(key), real(key))[1])
    files[FILE_CORPUS] = unchecked
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    assert verify.arm_at_boot() is True
    runner = threading.Thread(target=verify.run_armed, name="the-check")
    runner.start()
    try:
        assert entered.wait(60), "the pass was never reached"
        if list_readable:
            assert seen == [verify.PAGES_ENTRY], f"the progress line did not name the pass while it ran: {seen}"
        before = damage.registry.state(detail=True)["verification"][FILE_CORPUS]
        assert before["state"] == "running" and before["attempts"] == 1
        verify.stop()  # the quit: the pass cannot end, and nothing after it will run
        now = _record(tmp_path)["verification"][FILE_CORPUS]
        assert now["state"] == "running" and now["attempts"] == 0, "the quit did not give the attempt back while the pass was running"
    finally:
        release.set()
        runner.join(60)
    assert not runner.is_alive()
    assert gave == [FILE_CORPUS], f"the attempt was given back {len(gave)} times"
    final = _record(tmp_path)["verification"][FILE_CORPUS]
    assert final["state"] == "running" and "verdict" not in final and final["attempts"] == 0, "the stopped pass's answer was recorded"
    assert not damage.registry.latched(FILE_CORPUS)


def test_a_stop_after_the_pass_gives_nothing_back_twice(tmp_path, unchecked, files, monkeypatch):
    """A stop that arrives once the pass has ended is the tables' stop, not the pass's: one give-back, not two."""
    gave: list[str] = []
    real = damage.registry.verification_file_stopped
    monkeypatch.setattr(damage.registry, "verification_file_stopped", lambda key: (gave.append(key), real(key))[1])
    real_pass = verify.confirm_encrypted_damage

    def pass_then_quit(path, **kw):
        out = real_pass(path, **kw)
        verify._CANCEL.set()  # the quit lands right after the pass, before the run looks again
        return out

    monkeypatch.setattr(verify, "confirm_encrypted_damage", pass_then_quit)
    _run(files, unchecked, monkeypatch)
    assert gave == [FILE_CORPUS]
    assert _record(tmp_path)["verification"][FILE_CORPUS]["attempts"] == 0


def test_a_stop_while_no_pass_runs_leaves_the_pass_marker_clear():
    verify._reset_for_tests()
    verify.stop()
    assert verify._PASS_FILE is None and not verify._GAVE_BACK
    verify._reset_for_tests()


# --------------------------------------------------------------------------- #
#  a damaged pass is read AGAIN on a new connection and stands only when the second pass agrees (E2 fold 3, R100)
# --------------------------------------------------------------------------- #
_FAILING = [("HMAC verification failed for page 7",), ("HMAC verification failed for page 9",)]


def _openers(*cons):
    """An opener that hands out ``cons`` in turn (one per call), and the list of calls it saw."""
    calls: list[Path] = []
    queue = list(cons)

    def opener(path):
        calls.append(Path(path))
        nxt = queue.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt

    return opener, calls


def test_a_damaged_pass_stands_when_a_second_pass_on_a_new_connection_agrees_and_keeps_the_first_pass_pages():
    first, second = _Rows(rows=_FAILING), _Rows(rows=_FAILING[:1])
    opener, calls = _openers(first, second)
    entry = verify.confirm_encrypted_damage(Path("x.db"), opener=opener)
    assert entry["verdict"] == VERDICT_DAMAGED and entry["second_read"] == verify.SECOND_READ_AGREED
    assert entry["pages"] == [7, 9] and entry["pages_total"] == 2, "the first pass's finding was replaced"
    assert len(calls) == 2 and first.closed == 1 and second.closed == 1


def test_a_second_pass_that_reads_clean_files_the_pages_unchecked_and_says_what_each_read_said():
    opener, calls = _openers(_Rows(rows=_FAILING), _Rows(rows=[]))
    entry = verify.confirm_encrypted_damage(Path("x.db"), opener=opener)
    assert entry["verdict"] == VERDICT_UNCHECKED and entry["second_read"] == verify.SECOND_READ_CLEAN
    assert entry["detail"] == [verify._DIFFERENTLY] and "pages" not in entry and "pages_total" not in entry
    assert "2 page(s) failed" in entry["first_read"][0], entry
    assert len(calls) == 2


def test_a_second_pass_that_could_not_be_made_files_the_pages_unchecked_with_why():
    sqc = pytest.importorskip("sqlcipher3.dbapi2")
    busy = sqc.OperationalError("database is locked")
    busy.sqlite_errorcode = 5
    opener, _calls = _openers(_Rows(rows=_FAILING), busy)
    entry = verify.confirm_encrypted_damage(Path("x.db"), opener=opener)
    assert entry["verdict"] == VERDICT_UNCHECKED and entry["second_read"] == verify.SECOND_READ_UNAVAILABLE
    assert entry["detail"] == [verify._SECOND_UNMADE] and entry["second_detail"] == ["the file was busy"], entry
    assert "2 page(s) failed" in entry["first_read"][0]


def test_a_stop_between_the_two_passes_makes_no_second_pass_and_no_verdict():
    stopped = threading.Event()

    class Stopping(_Rows):
        def close(self):
            super().close()
            stopped.set()  # the stop arrives as the first pass ends

    first = Stopping(rows=_FAILING)
    opener, calls = _openers(first)
    entry = verify.confirm_encrypted_damage(Path("x.db"), opener=opener, cancel=stopped)
    assert entry["verdict"] == VERDICT_UNCHECKED and entry["second_read"] == verify.SECOND_READ_UNAVAILABLE
    assert entry["second_detail"] == ["the check was stopped"] and len(calls) == 1


def test_a_clean_pass_and_a_pass_that_could_not_be_made_cost_one_pass():
    for rows, boom in ((_Rows(rows=[]), None), (None, OSError("gone"))):
        con = rows if rows is not None else _Rows(boom=boom)
        opener, calls = _openers(con, _Rows(rows=_FAILING))
        entry = verify.confirm_encrypted_damage(Path("x.db"), opener=opener)
        assert entry["verdict"] in (VERDICT_OK, VERDICT_UNCHECKED) and "second_read" not in entry
        assert len(calls) == 1, "a pass that was not damaged was read twice"


def test_the_two_reasons_fit_the_detail_cut_and_end_on_what_matters():
    for reason in (verify._DIFFERENTLY, verify._SECOND_UNMADE):
        assert len(reason) <= verify.DETAIL_CHARS, "the sentence would be cut before it says nothing was concluded"
        assert reason.endswith("nothing was concluded")


def test_real_damage_is_confirmed_by_two_real_passes_and_a_real_flaky_first_read_is_not(tmp_path, unchecked, healthy):
    """Real encrypted files: the damaged file's two passes agree; a first pass that reads the damaged file and a second pass that reads a
    healthy one (what a read that differs between two connections looks like to the check) is unchecked."""
    confirmed = verify.confirm_encrypted_damage(unchecked)
    assert confirmed["verdict"] == VERDICT_DAMAGED and confirmed["second_read"] == verify.SECOND_READ_AGREED
    assert confirmed["pages_total"] >= 1

    paths = iter([unchecked, healthy])
    flaky = verify.confirm_encrypted_damage(unchecked, opener=lambda p: verify._open(next(paths)))
    assert flaky["verdict"] == VERDICT_UNCHECKED and flaky["second_read"] == verify.SECOND_READ_CLEAN, flaky


def test_a_run_files_a_page_finding_damaged_only_after_two_passes_and_latches_on_it(tmp_path, unchecked, files, monkeypatch, asked):
    _run(files, unchecked, monkeypatch)
    entry = _record(tmp_path)["verification"][FILE_CORPUS]
    pages = _by_table(entry)[verify.PAGES_ENTRY]
    assert pages["verdict"] == VERDICT_DAMAGED and pages["second_read"] == verify.SECOND_READ_AGREED
    assert damage.registry.latched(FILE_CORPUS)


def test_a_run_whose_second_pass_reads_a_different_file_latches_nothing_and_says_so(tmp_path, unchecked, healthy, files, monkeypatch):
    real_open = verify._open
    seen = {"n": 0}

    def flaky(path):
        seen["n"] += 1
        # the list (1), the two tables (2, 3) and the first pass (4) read the damaged file; the read after them (the second pass) reads
        # the healthy copy
        return real_open(unchecked if seen["n"] <= 4 else healthy)

    files[FILE_CORPUS] = unchecked
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    assert verify.arm_at_boot() is True
    assert verify.run_armed(opener=flaky) is True
    entry = _record(tmp_path)["verification"][FILE_CORPUS]
    pages = _by_table(entry)[verify.PAGES_ENTRY]
    assert pages["verdict"] == VERDICT_UNCHECKED and pages["second_read"] == verify.SECOND_READ_CLEAN, pages
    assert entry["verdict"] == VERDICT_UNCHECKED
    assert not damage.registry.latched(FILE_CORPUS), "a finding that two connections disagreed about latched the file"
    assert sg.StorageGuard().admit() is None


# --------------------------------------------------------------------------- #
#  the passphrase rule (R134 (3)): the passphrase and the derived key reach no sink, on a success and on every failure
# --------------------------------------------------------------------------- #
MARKER_PASS = "MARKER-pass-4711-correct-horse-ÄÖ"


def _spec_key(passphrase: str, salt: bytes) -> bytes:
    """SQLCipher 4's tag key written out from the specification (not through ``page_auth``), to know what must never be written."""
    enc = hashlib.pbkdf2_hmac("sha512", passphrase.encode("utf-8"), salt, 256000, 32)
    return hashlib.pbkdf2_hmac("sha512", enc, bytes(b ^ 0x3A for b in salt), 2, 32)


def _forbidden(passphrase: str, key: bytes) -> dict[str, str]:
    """Every form either secret could be written in, by what it is: the passphrase as text, as its UTF-8 bytes in hex and as the repr of
    those bytes (and the ASCII part of it alone); the key in hex (both cases), as the repr of bytes or a bytearray, and as a list of ints."""
    raw = passphrase.encode("utf-8")
    return {
        "passphrase": passphrase,
        "passphrase marker": passphrase.split("-Ä")[0],
        "passphrase hex": raw.hex(),
        "passphrase repr": repr(raw),
        "key hex": key.hex(),
        "key HEX": key.hex().upper(),
        "key repr": repr(key),
        "key bytearray": repr(bytearray(key)),
        "key list": str(list(key)),
    }


def _leaks(texts: dict[str, str], forbidden: dict[str, str]) -> list[tuple[str, str]]:
    return [(sink, what) for sink, text in texts.items() for what, form in forbidden.items() if form in text]


@pytest.fixture
def marker_store(tmp_path):
    previous = connect_mod.get_passphrase()
    connect_mod.set_passphrase(MARKER_PASS)
    path = tmp_path / "marker.db"
    con = connect_mod.connect(str(path), create_encrypted=True, check_same_thread=False)
    try:
        con.execute("CREATE TABLE t(x BLOB)")
        rng = random.Random(2)
        for _ in range(600):
            con.execute("INSERT INTO t VALUES (?)", (rng.randbytes(3000),))
        con.commit()
    finally:
        con.close()
    yield path
    connect_mod.set_passphrase(previous)


@pytest.fixture
def sinks(tmp_path, monkeypatch, caplog):
    """Every place the pass's words can land, read back after it: the log (every logger, DEBUG), the error journal (``app_errors.jsonl``,
    through its own handler on the root logger), the storage-events journal, the damage record's file, and that record as the Diagnostics
    archive carries it (the slot's answer written through the bundle's own member writer into a real zip)."""
    import io
    import logging
    import zipfile

    from src.api import diagnostics_slots as slots
    from src.api.diagnostics import bundle as bundle_mod
    from src.monitoring import errorlog
    from src.monitoring import storage_events as se

    monkeypatch.setattr(errorlog, "_log_path", lambda: tmp_path / "app_errors.jsonl")
    monkeypatch.setattr(se, "_path", lambda: tmp_path / "storage_events.json")
    se.reset_for_tests()
    root = logging.getLogger()
    handler = errorlog._JsonlErrorHandler(level=logging.WARNING)
    root.addHandler(handler)
    caplog.set_level(logging.DEBUG)

    def collect() -> dict[str, str]:
        se.flush()
        out = {"log": caplog.text}
        for name, path in (("app_errors", tmp_path / "app_errors.jsonl"), ("storage events", tmp_path / "storage_events.json"), ("damage record", tmp_path / "database-damage.json")):
            out[name] = path.read_text(encoding="utf-8") if path.exists() else ""
        (slot,) = [s for s in slots.SLOTS if s.name == "database-damage.json"]
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as zf:
            bundle_mod._write_member(zf, "database-damage.json", slots.thunk(slot)())
        with zipfile.ZipFile(io.BytesIO(raw.getvalue())) as zf:
            out["diagnostics zip"] = zf.read("database-damage.json").decode("utf-8")
        return out

    try:
        yield collect
    finally:
        root.removeHandler(handler)
        se.reset_for_tests()


def test_the_sink_check_can_fail(sinks, marker_store):
    """The harness is not vacuous: a record that carries the key (or the passphrase) in the shapes it checks is found in the log."""
    import logging

    with open(marker_store, "rb") as fh:
        salt = fh.read(16)
    key = _spec_key(MARKER_PASS, salt)
    logging.getLogger("tests.page_auth").warning("leak %s %s", key.hex(), MARKER_PASS)
    found = _leaks(sinks(), _forbidden(MARKER_PASS, key))
    assert ("log", "key hex") in found and ("log", "passphrase") in found, found
    assert ("app_errors", "key hex") in found, "the error journal keeps a hex key (it only scrubs the passphrases the process holds)"


def _scenario(name: str, path: Path, monkeypatch) -> None:
    """Set the failure up. The messages every stand-in failure carries hold the passphrase and the real key, so a pass that wrote an exception's
    words anywhere would leave both in a sink."""
    page_auth = verify.page_auth
    with open(path, "rb") as fh:
        salt = fh.read(16)
    poison = f"{MARKER_PASS} {_spec_key(MARKER_PASS, salt).hex()}"
    if name == "damaged":
        H.overwrite_pages(path, [60], PAGE)
    elif name == "mismatch":
        real = page_auth.derive_tag_key
        monkeypatch.setattr(page_auth, "derive_tag_key", lambda s: real(bytes(16)))
    elif name == "unreadable":

        class Eio:
            def __init__(self, real):
                self.real = real

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.real.close()

            def seek(self, *args):
                return self.real.seek(*args)

            def readinto(self, view):
                pos = self.real.tell()
                if pos < 40 * PAGE and pos + len(view) > 39 * PAGE:  # page 40
                    raise OSError(errno.EIO, poison, f"/home/{MARKER_PASS}/f.db")
                return self.real.readinto(view)

        monkeypatch.setattr(page_auth, "_raw_open", lambda p, mode="rb", buffering=0: Eio(open(p, mode, buffering=buffering)))  # noqa: SIM115 - the wrapper owns the handle and closes it
    elif name == "hmac raises":

        def boom(*args, **kwargs):
            raise RuntimeError(poison)

        monkeypatch.setattr(page_auth, "hmac", types.SimpleNamespace(new=boom, compare_digest=lambda a, b: False))
    elif name == "derivation raises":
        real_hashlib = hashlib
        calls = []

        class Spy:
            @staticmethod
            def pbkdf2_hmac(*args):
                calls.append(args)
                if len(calls) % 2 == 0:  # the second derivation of every pass
                    raise RuntimeError(poison)
                return real_hashlib.pbkdf2_hmac(*args)

        monkeypatch.setattr(page_auth, "hashlib", Spy)


@pytest.mark.parametrize("scenario", ["clean", "damaged", "mismatch", "unreadable", "hmac raises", "derivation raises"])
def test_neither_the_passphrase_nor_the_derived_key_reaches_any_sink_on_any_path(scenario, marker_store, files, tmp_path, monkeypatch, sinks):
    _scenario(scenario, marker_store, monkeypatch)
    _past_the_limit(monkeypatch, marker_store)
    monkeypatch.setattr(verify, "inspect_file", lambda path, opener=None: {"error": (VERDICT_UNCHECKED, "OperationalError"), "sqlite_code": 1})
    held: list[bytes] = []
    real = verify.page_auth.derive_tag_key

    def watch(salt):
        key = real(salt)
        if key is not None:
            held.append(bytes(key))
        return key

    monkeypatch.setattr(verify.page_auth, "derive_tag_key", watch)
    _run(files, marker_store, monkeypatch)
    direct = verify.confirm_encrypted_damage(marker_store)  # the entry as the pass returns it, and the pass's own result below
    with open(marker_store, "rb") as fh:
        salt = fh.read(16)
    raw = verify.page_auth.check_path(marker_store, PAGE)
    texts = {**sinks(), "entry": json.dumps(direct), "result": json.dumps(raw)}
    forbidden = _forbidden(MARKER_PASS, _spec_key(MARKER_PASS, salt))
    for key in held:  # whatever key the pass held, the right one or the wrong one
        forbidden.update({f"held key hex {i}": k.hex() for i, k in enumerate([key])})
    assert held or scenario == "derivation raises", "the pass derived no key: the scenario is vacuous"
    assert _leaks(texts, forbidden) == [], _leaks(texts, forbidden)
    assert texts["damage record"], "the pass left a record to read"
    verdicts = {"clean": VERDICT_OK, "damaged": VERDICT_DAMAGED}
    assert direct["verdict"] == verdicts.get(scenario, VERDICT_UNCHECKED), direct
