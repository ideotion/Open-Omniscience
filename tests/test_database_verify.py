"""The per-table check after an unexpected stop (damaged-database plan, slice E2).

E1 notices damage when something READS a damaged page and fails. A file that is damaged but not read keeps
collecting into it (measured on the Asus bundle: ``count(*)``, ``max(id)`` and the first page all answered for a
day and a half). E2 reads each table once, with ``PRAGMA quick_check(<table>)`` on its own read-only connection,
BEFORE collection writes to the file again, when the previous session did not end cleanly.

Every claim about a verdict is made against the REAL drivers on REAL damaged copies (pages overwritten as
``test_database_damage.py`` and the plan's measurements do), because a check that only passes on a hand-built
exception proves nothing about the pages SQLite actually reads:

  * a damaged table is ``damaged`` and a healthy one in the same file is ``ok`` (the check is per table);
  * a busy or locked file, a wrong or missing passphrase and a stop are ``unchecked`` and NEVER ``damaged``;
  * the check runs only after an unclean end (an unknown end is not a reason), or when an earlier check was
    left unfinished, at most ``MAX_VERIFY_ATTEMPTS`` starts in a row;
  * from the moment it is armed until it ends, collection, the Wikipedia lane, the law lane and the off-peak
    maintenance wait, and "Resume anyway" is refused with a sentence; it always ends, however the run ends;
  * a damaged table latches its file by the SAME door a corruption error does, with the scope the tables name.
"""
from __future__ import annotations

import json
import os
import random
import re
import sqlite3
import sys
import threading
from pathlib import Path

import pytest

from src.database import damage, verify
from src.database.damage import (
    FILE_CORPUS,
    FILE_LAW,
    FILE_WIKI,
    MAX_VERIFY_ATTEMPTS,
    SCOPE_DATA,
    SCOPE_SEARCH_INDEX,
    VERDICT_DAMAGED,
    VERDICT_OK,
    VERDICT_UNCHECKED,
    DamageRegistry,
)
from src.scheduler import runner
from src.scheduler import storage_guard as sg

ROOT = Path(__file__).resolve().parents[1]
PAGE = 4096
UNCLEAN = {"clean": False, "at": "2026-10-06T01:00:00+00:00", "basis": "the liveness file"}
CLEAN = {"clean": True, "at": "2026-10-06T01:00:00+00:00", "basis": "the sentinel"}


# --------------------------------------------------------------------------- #
#  fixtures: a real store with a big table and a small one, and a real damaged copy of it
# --------------------------------------------------------------------------- #
def _build_store(path: Path, rows: int = 3000, fts: bool = False) -> None:
    con = sqlite3.connect(path)
    con.execute(f"PRAGMA page_size={PAGE}")
    con.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT, content TEXT)")
    con.execute("CREATE INDEX ix_articles_title ON articles (title)")
    con.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
    rng = random.Random(7)
    con.executemany(
        "INSERT INTO articles (title, content) VALUES (?, ?)",
        [(f"title {i}", "".join(rng.choice("abcdefghij ") for _ in range(900))) for i in range(rows)],
    )
    con.executemany("INSERT INTO notes (body) VALUES (?)", [(f"note {i}",) for i in range(20)])
    if fts:
        con.execute("CREATE VIRTUAL TABLE article_fts USING fts5(title, content)")
        con.execute("INSERT INTO article_fts (title, content) SELECT title, content FROM articles")
    con.execute("ANALYZE")
    con.commit()
    con.close()


def _leaf_pages(path: Path, table: str) -> list[int]:
    con = sqlite3.connect(path)
    try:
        return [p for p, t in con.execute("SELECT pageno, pagetype FROM dbstat WHERE name=?", (table,)) if t == "leaf"]
    except sqlite3.OperationalError:
        reason = "this SQLite build has no dbstat virtual table (SQLITE_ENABLE_DBSTAT_VTAB)"
        if os.getenv("CI") and sys.platform.startswith("linux"):
            pytest.fail(reason + " -- the Linux CI lane must run the damaged-page tests")
        pytest.skip(reason)
    finally:
        con.close()


def _overwrite(path: Path, pages: list[int]) -> None:
    with open(path, "r+b") as f:
        for pg in pages:
            f.seek((pg - 1) * PAGE)
            f.write(random.Random(pg).randbytes(PAGE))


@pytest.fixture
def healthy(tmp_path):
    path = tmp_path / "corpus.db"
    _build_store(path)
    return path


@pytest.fixture
def damaged(tmp_path):
    """(path, damaged leaf pages): three random leaf pages of ``articles`` overwritten; ``notes`` is whole."""
    path = tmp_path / "corpus.db"
    _build_store(path)
    bad = sorted(random.Random(1).sample(_leaf_pages(path, "articles"), 3))
    _overwrite(path, bad)
    return path, bad


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """A registry over a record file of this test's own, as the process-global one, with the verify module's
    state reset around the test."""
    reg = DamageRegistry(path_fn=lambda: tmp_path / "database-damage.json")
    monkeypatch.setattr(damage, "registry", reg)
    verify._reset_for_tests()
    yield reg
    verify._reset_for_tests()


@pytest.fixture
def files(tmp_path, monkeypatch, registry):
    """Point each file key at a path of this test's own (a key with no file is simply absent)."""
    paths: dict[str, Path] = {}

    def fake(key):
        p = paths.get(key)
        return (p, p.name) if p else (None, None)

    monkeypatch.setattr(damage, "_file_paths", fake)
    return paths


def _record(tmp_path) -> dict:
    return json.loads((tmp_path / "database-damage.json").read_text(encoding="utf-8"))


def _by_table(entry: dict) -> dict[str, dict]:
    return {t["table"]: t for t in entry["tables"]}


# --------------------------------------------------------------------------- #
#  one table, on real pages
# --------------------------------------------------------------------------- #
def test_a_healthy_table_is_ok(healthy):
    out = verify.check_table(healthy, "articles")
    assert out["verdict"] == VERDICT_OK and out["table"] == "articles" and "detail" not in out


def test_a_damaged_table_is_damaged_and_the_healthy_one_beside_it_is_not(damaged):
    """The measurement the plan rests on: a healthy count is no evidence, ``quick_check(table)`` is."""
    path, _bad = damaged
    con = sqlite3.connect(path)
    assert con.execute("SELECT count(*) FROM articles").fetchone()[0] == 3000, "the damage is invisible to count(*)"
    con.close()
    bad = verify.check_table(path, "articles")
    assert bad["verdict"] == VERDICT_DAMAGED and bad["detail"], bad
    assert verify.check_table(path, "notes")["verdict"] == VERDICT_OK, "a whole table was called damaged"


def test_the_detail_is_bounded_and_names_pages_never_values(damaged):
    path, _bad = damaged
    detail = verify.check_table(path, "articles")["detail"]
    assert 1 <= len(detail) <= verify.DETAIL_LINES
    assert all(len(line) <= verify.DETAIL_CHARS for line in detail)
    assert not any("title " in line for line in detail), "a row value reached the record"


def test_a_table_name_with_a_quote_is_one_identifier_not_a_statement(tmp_path):
    path = tmp_path / "q.db"
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE "we""ird" (id INTEGER PRIMARY KEY, x TEXT)')
    con.execute('INSERT INTO "we""ird" (x) VALUES (\'a\')')
    con.commit()
    con.close()
    assert verify.check_table(path, 'we"ird')["verdict"] == VERDICT_OK


def test_the_check_opens_read_only_so_nothing_on_it_can_write(healthy):
    con = verify._open(healthy)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly|read-only|query_only"):
            con.execute("CREATE TABLE intruder (x)")
    finally:
        con.close()
    con = sqlite3.connect(healthy)
    assert con.execute("SELECT count(*) FROM sqlite_master WHERE name='intruder'").fetchone()[0] == 0
    con.close()


def test_the_files_bytes_are_unchanged_by_a_check(damaged):
    path, _bad = damaged
    before = path.read_bytes()
    verify.check_table(path, "articles")
    verify.inspect_file(path)
    assert path.read_bytes() == before, "the check wrote into the file it was reading"


# --------------------------------------------------------------------------- #
#  not reading is not a verdict
# --------------------------------------------------------------------------- #
def test_a_locked_file_is_unchecked_never_damaged(healthy):
    holder = sqlite3.connect(healthy, isolation_level=None)
    holder.execute("BEGIN EXCLUSIVE")
    try:
        out = verify.check_table(healthy, "articles", opener=lambda p: _quick(p, timeout=0.05))
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert out["verdict"] == VERDICT_UNCHECKED, out
    assert out["detail"] and "damage" not in out["detail"][0].lower()


def _quick(path, timeout):
    con = sqlite3.connect(path, timeout=timeout, check_same_thread=False)
    con.execute("PRAGMA query_only=ON")
    return con


@pytest.mark.parametrize(
    ("make", "verdict", "words"),
    [
        (lambda: sqlite3.OperationalError("database is locked"), VERDICT_UNCHECKED, None),
        (lambda: ValueError("boom"), VERDICT_UNCHECKED, "ValueError"),
        (lambda: PermissionError("no"), VERDICT_UNCHECKED, "PermissionError"),
    ],
)
def test_an_error_that_is_not_corruption_is_unchecked_with_a_reason(make, verdict, words):
    got, reason = verify.classify_error(make())
    assert got == verdict and reason
    if words:
        assert words in reason


def test_a_locked_library_and_a_wrong_passphrase_are_unchecked_with_their_own_words():
    from src.database.connect import DatabaseLockedError, WrongPassphraseError

    v1, r1 = verify.classify_error(DatabaseLockedError("locked"))
    v2, r2 = verify.classify_error(WrongPassphraseError("wrong"))
    assert (v1, v2) == (VERDICT_UNCHECKED, VERDICT_UNCHECKED)
    assert "passphrase" in r1 and "passphrase" in r2 and r1 != r2


def test_sqlite_corrupt_is_the_only_exception_that_is_damage(damaged):
    path, _bad = damaged
    con = sqlite3.connect(path)
    with pytest.raises(sqlite3.DatabaseError) as err:
        con.execute("SELECT sum(length(content)) FROM articles").fetchall()
    con.close()
    verdict, reason = verify.classify_error(err.value)
    assert verdict == VERDICT_DAMAGED and reason
    for code in (5, 6, 9, 10, 14, 26):  # busy, locked, interrupt, I/O error, can't open, not a database
        exc = sqlite3.DatabaseError("x")
        exc.sqlite_errorcode = code  # type: ignore[attr-defined]
        v, _ = verify.classify_error(exc)
        assert v == VERDICT_UNCHECKED, f"code {code} was called damage"


def test_a_stop_ends_the_table_in_hand_as_unchecked(healthy, monkeypatch):
    monkeypatch.setattr(verify, "_PROGRESS_STEPS", 10)
    cancel = threading.Event()
    cancel.set()
    out = verify.check_table(healthy, "articles", cancel=cancel)
    assert out["verdict"] == VERDICT_UNCHECKED, out
    assert "stopped" in out["detail"][0]


def test_a_wrong_key_on_a_real_encrypted_file_is_unchecked_and_a_bad_page_under_the_right_key_is_damaged(
    tmp_path, monkeypatch
):
    sqc = pytest.importorskip("sqlcipher3.dbapi2")
    path = tmp_path / "enc.db"
    con = sqc.connect(str(path))
    con.execute("PRAGMA key='pass1'")
    con.execute("PRAGMA cipher_page_size=4096")
    con.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, body TEXT)")
    con.executemany("INSERT INTO articles (body) VALUES (?)", [("x" * 500 + str(i),) for i in range(8000)])
    con.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
    con.execute("INSERT INTO notes (body) VALUES ('n')")
    con.commit()
    con.close()

    def keyed(key):
        def opener(p):
            c = sqc.connect(str(p), check_same_thread=False)
            c.execute(f"PRAGMA key='{key}'")
            c.execute("PRAGMA query_only=ON")
            return c

        return opener

    wrong = verify.check_table(path, "articles", opener=keyed("wrong"))
    assert wrong["verdict"] == VERDICT_UNCHECKED, "a wrong passphrase was called damage"
    assert verify.check_table(path, "articles", opener=keyed("pass1"))["verdict"] == VERDICT_OK
    pages = path.stat().st_size // 4096
    _overwrite(path, [pages // 3, pages // 2])
    assert verify.check_table(path, "articles", opener=keyed("pass1"))["verdict"] == VERDICT_DAMAGED
    assert verify.check_table(path, "notes", opener=keyed("pass1"))["verdict"] == VERDICT_OK


def test_the_default_opener_goes_through_the_one_connection_factory(healthy, monkeypatch):
    import src.database.connect as connect_mod

    seen: list[dict] = []
    real = connect_mod.connect

    def spy(path, **kw):
        seen.append({"path": str(path), **kw})
        return real(path, **kw)

    monkeypatch.setattr(connect_mod, "connect", spy)
    assert verify.check_table(healthy, "notes")["verdict"] == VERDICT_OK
    assert seen and seen[0]["path"] == str(healthy) and seen[0]["check_same_thread"] is False


def test_a_missing_default_never_creates_a_file(tmp_path):
    ghost = tmp_path / "ghost.db"
    out = verify.inspect_file(ghost)
    assert "error" in out and not ghost.exists(), "a check created the file it was asked to read"


# --------------------------------------------------------------------------- #
#  the order, and the file verdict
# --------------------------------------------------------------------------- #
def test_tables_are_checked_smallest_first_by_the_planners_statistics_and_the_unmeasured_after(healthy):
    out = verify.inspect_file(healthy)
    assert out["names"][0] == "notes" and out["names"][1] == "articles", out["names"]
    con = sqlite3.connect(healthy)
    con.execute("CREATE TABLE zeta (id INTEGER PRIMARY KEY)")
    con.execute("CREATE TABLE alpha (id INTEGER PRIMARY KEY)")
    con.commit()
    con.close()
    names = verify.inspect_file(healthy)["names"]
    assert names[:2] == ["notes", "articles"] and names[2:] == ["alpha", "zeta"], names


def test_the_list_carries_the_files_facts_and_no_internal_table(healthy):
    out = verify.inspect_file(healthy)
    assert not any(n.startswith("sqlite_") for n in out["names"])
    facts = out["facts"]
    assert facts["page_size"] == PAGE and facts["page_count"] > 0 and facts["file_bytes"] == healthy.stat().st_size


def test_a_damaged_schema_page_under_the_right_key_is_damage_not_a_wrong_passphrase(tmp_path, monkeypatch):
    """``connect()`` tries the page size that opened the path last (then the standard sizes, then the undeclared one)
    and used to chain the LAST candidate's error, which is always code 26 (the HMAC check) whatever the file's state:
    a schema page damaged under the right key and size read as ``the passphrase did not open the file``."""
    pytest.importorskip("sqlcipher3.dbapi2")
    from src.database import connect as C

    path = tmp_path / "enc.db"
    con = C.connect(path, key="the-right-passphrase", check_same_thread=False)
    con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    con.commit()
    con.close()
    tried: list[int | None] = []

    def fake(_p, _key, _cst, _timeout, page_size, *, last_error=None, read_only=False):
        tried.append(page_size)
        if last_error is not None:
            err = _driver_corrupt() if len(tried) == 1 else _driver_hmac()
            last_error[:] = [err]
        return None

    monkeypatch.setattr(C, "_try_open_encrypted", fake)
    with pytest.raises(C.WrongPassphraseError) as caught:
        C.connect(path, key="the-right-passphrase", check_same_thread=False)
    assert len(tried) > 1, "the first candidate was the only one tried"
    assert verify.classify_error(caught.value)[0] == VERDICT_DAMAGED, "the FIRST candidate's error was not chained"
    # and with nothing but the HMAC failure (a wrong passphrase) it stays unchecked, in its own words
    monkeypatch.setattr(
        C, "_try_open_encrypted", lambda *a, last_error=None, **k: last_error.__setitem__(slice(None), [_driver_hmac()])
    )
    with pytest.raises(C.WrongPassphraseError) as wrong:
        C.connect(path, key="a-wrong-passphrase", check_same_thread=False)
    verdict, reason = verify.classify_error(wrong.value)
    assert verdict == VERDICT_UNCHECKED and "passphrase" in reason
    # the right size is not always the FIRST candidate (nothing opened this path in this process): the error of the
    # candidate that got past page 1 is the one that says what happened
    tried.clear()

    def fake_later(_p, _key, _cst, _timeout, page_size, *, last_error=None, read_only=False):
        tried.append(page_size)
        if last_error is not None:
            last_error[:] = [_driver_corrupt() if len(tried) == 3 else _driver_hmac()]
        return None

    monkeypatch.setattr(C, "_try_open_encrypted", fake_later)
    with pytest.raises(C.WrongPassphraseError) as later:
        C.connect(path, key="the-right-passphrase", check_same_thread=False)
    assert len(tried) > 3 and verify.classify_error(later.value)[0] == VERDICT_DAMAGED, "the candidate that got past page 1 was not chained"


def test_a_damaged_schema_page_is_damage_on_a_real_encrypted_file_whose_page_size_nothing_has_cached(tmp_path):
    """The same fold on the real driver (a fake pins only the wiring): a store with a 4096-byte page and a schema that
    spans several pages, every page but the first overwritten, opened by a process that has never opened it, so
    ``connect()`` reaches the right page size in the middle of its candidates."""
    pytest.importorskip("sqlcipher3.dbapi2")
    from src.database import connect as C

    path = tmp_path / "enc4k.db"
    con = C.connect(path, key="the-right-passphrase", check_same_thread=False, cipher_page_size=4096)
    for i in range(150):
        con.execute(f"CREATE TABLE tbl_{i:03d} (id INTEGER PRIMARY KEY, a TEXT, b TEXT, c TEXT)")
    con.commit()
    pages = con.execute("PRAGMA page_count").fetchone()[0]
    con.close()
    assert pages > 3
    with open(path, "r+b") as f:
        for pg in range(2, pages + 1):
            f.seek((pg - 1) * 4096)
            f.write(random.Random(pg).randbytes(4096))
    C._last_good_page_size.pop(str(path.resolve()), None)
    with pytest.raises(C.WrongPassphraseError) as caught:
        C.connect(path, key="the-right-passphrase", check_same_thread=False)
    assert verify.classify_error(caught.value)[0] == VERDICT_DAMAGED, caught.value.__cause__


def _driver_hmac():
    err = sqlite3.DatabaseError("file is not a database")
    err.sqlite_errorcode = 26  # type: ignore[attr-defined]
    return err


def test_a_file_that_does_not_open_as_a_database_says_nothing(tmp_path):
    """Code 26 is a wrong passphrase as much as a damaged first page (E1's stated blind spot): unchecked."""
    junk = tmp_path / "junk.db"
    junk.write_bytes(os.urandom(PAGE * 4))
    out = verify.inspect_file(junk)
    assert out["error"][0] == VERDICT_UNCHECKED and out["error"][1]


def test_a_file_is_damaged_if_any_table_is_ok_if_every_table_is_and_unchecked_otherwise():
    ok, bad, un = {"verdict": VERDICT_OK}, {"verdict": VERDICT_DAMAGED}, {"verdict": VERDICT_UNCHECKED}
    assert verify.file_verdict([ok, ok]) == VERDICT_OK
    assert verify.file_verdict([ok, bad, un]) == VERDICT_DAMAGED
    assert verify.file_verdict([ok, un]) == VERDICT_UNCHECKED
    assert verify.file_verdict([]) == VERDICT_UNCHECKED, "nothing read is not 'ok'"


# --------------------------------------------------------------------------- #
#  when the check runs
# --------------------------------------------------------------------------- #
def test_an_unclean_end_plans_the_check_and_a_clean_or_unknown_end_does_not(healthy, files):
    files[FILE_CORPUS] = healthy
    plan = verify.plan_boot(previous_end=UNCLEAN)
    assert plan and plan["trigger"] == verify.TRIGGER_UNCLEAN_END
    assert [k for k, _p, _a in plan["files"]] == [FILE_CORPUS] and plan["skipped"] == []
    assert verify.plan_boot(previous_end=CLEAN) is None
    assert verify.plan_boot(previous_end={"clean": None, "at": None, "basis": None}) is None, (
        "an end nobody knows is not a reason to hold collection"
    )


def test_a_file_that_is_missing_or_empty_is_not_checked_and_never_created(tmp_path, files):
    files[FILE_CORPUS] = tmp_path / "absent.db"
    files["wiki"] = tmp_path / "empty.db"
    files["wiki"].write_bytes(b"")
    assert verify.plan_boot(previous_end=UNCLEAN) is None
    assert not files[FILE_CORPUS].exists()


def test_every_file_damage_can_pause_is_in_the_plan(tmp_path, files):
    for key in damage.PAUSED_FILES:
        p = tmp_path / f"{key}.db"
        _build_store(p, rows=50)
        files[key] = p
    plan = verify.plan_boot(previous_end=UNCLEAN)
    assert sorted(k for k, _p, _a in plan["files"]) == sorted(damage.PAUSED_FILES)


def test_the_switch_turns_the_check_off(healthy, files, monkeypatch):
    files[FILE_CORPUS] = healthy
    monkeypatch.setenv("OO_BOOT_VERIFY", "0")
    assert verify.plan_boot(previous_end=UNCLEAN) is None
    assert verify.arm_at_boot() is False and not damage.registry.verifying()


def _unfinished(tmp_path, attempts, key=FILE_CORPUS, process="another-process"):
    (tmp_path / "database-damage.json").write_text(
        json.dumps(
            {
                "schema": damage.SCHEMA,
                "files": {},
                "incidents": [],
                "verification": {key: {"file": key, "process": process, "state": "running", "attempts": attempts}},
            }
        ),
        encoding="utf-8",
    )


def test_a_check_left_unfinished_is_tried_again_after_a_clean_end_and_counts_its_attempts(tmp_path, healthy, files):
    files[FILE_CORPUS] = healthy
    _unfinished(tmp_path, attempts=1)
    plan = verify.plan_boot(previous_end=CLEAN)
    assert plan and plan["trigger"] == verify.TRIGGER_UNFINISHED
    assert plan["files"] == [(FILE_CORPUS, healthy, 1)]


def test_a_check_that_ends_every_start_unfinished_stops_being_tried_and_says_so(tmp_path, healthy, files, caplog):
    """What the cap protects: a check that itself brings the process down must not become a boot loop that never
    reaches collection."""
    files[FILE_CORPUS] = healthy
    _unfinished(tmp_path, attempts=MAX_VERIFY_ATTEMPTS)
    plan = verify.plan_boot(previous_end=UNCLEAN)
    assert plan["files"] == [] and [s["file"] for s in plan["skipped"]] == [FILE_CORPUS]
    assert verify.arm_at_boot() is False, "nothing to run means nothing to wait for"
    assert not damage.registry.verifying()
    entry = damage.registry.state(detail=True)["verification"][FILE_CORPUS]
    assert entry["state"] == "skipped" and entry["verdict"] == VERDICT_UNCHECKED and "not tried again" in entry["reason"]
    # it is tried again after the NEXT unexpected stop: the skipped entry is not an unfinished one
    reg2 = DamageRegistry(path_fn=lambda: tmp_path / "database-damage.json")
    assert reg2.previous_verification(FILE_CORPUS)["state"] == "skipped"


def test_the_attempt_count_climbs_across_starts_until_the_cap_and_a_later_unclean_end_starts_afresh(
    tmp_path, healthy, files, monkeypatch
):
    files[FILE_CORPUS] = healthy
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    path = tmp_path / "database-damage.json"

    def new_process():
        reg = DamageRegistry(path_fn=lambda: path)  # a new process: a new registry over the same record
        monkeypatch.setattr(damage, "registry", reg)
        verify._reset_for_tests()
        return reg

    for start in range(1, MAX_VERIFY_ATTEMPTS + 1):
        reg = new_process()
        assert verify.arm_at_boot() is True
        [(_key, _path, attempts_before)] = verify._PLAN["files"]
        assert attempts_before == start - 1, "the count did not climb across starts"
        # a start that began the check and ended before it did (a kill, a power loss)
        reg.verification_file_started(
            FILE_CORPUS, path=healthy, trigger=verify.TRIGGER_UNCLEAN_END, tables_total=2, attempts=start
        )
    reg = new_process()
    assert verify.arm_at_boot() is False and not reg.verifying(), "the cap did not stop a check that never ends"
    assert reg.state(detail=True)["verification"][FILE_CORPUS]["state"] == "skipped"
    reg = new_process()  # the next unexpected stop: the skipped entry is not an unfinished one
    assert verify.arm_at_boot() is True and verify._PLAN["files"][0][2] == 0
    assert verify.run_armed() is True
    done = damage.registry.state(detail=True)["verification"][FILE_CORPUS]
    assert done["state"] == "done" and done["attempts"] == 0


def test_a_file_is_checked_once_per_process(healthy, files, monkeypatch):
    """The start-up upkeep can run twice in a process (an unlock after a locked boot): one read per file."""
    files[FILE_CORPUS] = healthy
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    assert verify.arm_at_boot() is True and verify.run_armed() is True
    assert verify.arm_at_boot() is False, "the same process read the file a second time"
    assert not damage.registry.verifying()


# --------------------------------------------------------------------------- #
#  the run: arming, waiting, always ending, the record
# --------------------------------------------------------------------------- #
def test_armed_means_collection_waits_from_that_moment_and_the_end_releases_it(healthy, files, monkeypatch):
    files[FILE_CORPUS] = healthy
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    g = sg.StorageGuard()
    assert g.admit() is None
    assert verify.arm_at_boot() is True
    assert damage.registry.verifying()
    assert g.admit() == "verifying" and g.kind() == "verifying" and g.phase() == sg.PHASE_VERIFY
    assert not g.engaged, "the check is not a storage reading and must not look like one"
    assert verify.run_armed() is True
    assert g.admit() is None and g.phase() is None and not damage.registry.verifying()


def test_the_check_always_ends_the_arming_however_the_run_ends(healthy, files, monkeypatch):
    files[FILE_CORPUS] = healthy
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    verify.arm_at_boot()

    def boom(plan, opener=None):
        raise RuntimeError("the run broke")

    monkeypatch.setattr(verify, "_run_plan", boom)
    assert verify.run_armed() is True
    assert not damage.registry.verifying(), "collection was left waiting for a check that died"


def test_run_armed_without_arm_does_nothing_and_a_withdrawn_check_releases_collection(healthy, files, monkeypatch):
    assert verify.run_armed() is False
    files[FILE_CORPUS] = healthy
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    verify.arm_at_boot()
    verify.disarm()
    assert not damage.registry.verifying() and verify.run_armed() is False


def test_arming_never_raises_and_does_not_hold_collection_for_a_check_that_cannot_be_planned(monkeypatch, registry):
    monkeypatch.setattr(verify, "plan_boot", lambda **kw: (_ for _ in ()).throw(RuntimeError("no ledger")))
    assert verify.arm_at_boot() is False and not registry.verifying()


def test_the_pause_has_its_own_switch(healthy, files, monkeypatch):
    files[FILE_CORPUS] = healthy
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    verify.arm_at_boot()
    monkeypatch.setenv("OO_DAMAGE_GUARD", "0")
    assert not damage.registry.verifying(), "with the pause off, writing carries on"
    verify.run_armed()


def test_a_clean_check_records_the_tables_in_the_record_file_and_latches_nothing(tmp_path, healthy, files, monkeypatch):
    files[FILE_CORPUS] = healthy
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    verify.arm_at_boot()
    verify.run_armed()
    assert not damage.registry.latched(FILE_CORPUS)
    entry = _record(tmp_path)["verification"][FILE_CORPUS]
    assert entry["state"] == "done" and entry["verdict"] == VERDICT_OK and entry["trigger"] == verify.TRIGGER_UNCLEAN_END
    assert {t["table"] for t in entry["tables"]} == {"articles", "notes"}
    assert all(t["verdict"] == VERDICT_OK for t in entry["tables"])
    assert entry["tables_total"] == 2 and entry["facts"]["page_size"] == PAGE and entry["attempts"] == 0
    assert entry["file_name"] == healthy.name
    assert str(healthy.parent) not in json.dumps(_record(tmp_path)), "a path outside the file's own name reached the record"


def test_a_damaged_table_latches_its_file_records_one_incident_and_names_the_table(tmp_path, damaged, files, monkeypatch):
    path, _bad = damaged
    files[FILE_CORPUS] = path
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    g = sg.StorageGuard()
    verify.arm_at_boot()
    verify.run_armed()
    reg = damage.registry
    assert reg.latched(FILE_CORPUS), "a table read as damaged did not latch the file"
    assert g.admit() == "damage", "the latch is the same door a corruption error uses"
    rec = _record(tmp_path)
    tables = _by_table(rec["verification"][FILE_CORPUS])
    assert tables["articles"]["verdict"] == VERDICT_DAMAGED and tables["notes"]["verdict"] == VERDICT_OK
    assert rec["verification"][FILE_CORPUS]["verdict"] == VERDICT_DAMAGED
    [inc] = rec["incidents"]
    assert inc["file"] == FILE_CORPUS and inc["scope"] == SCOPE_DATA and inc["found_by"] == "per-table check"
    assert inc["tables"] == ["articles"] and "articles" in inc["scope_basis"]
    assert inc["route"] == damage.ROUTE_VERIFY_THEN_SALVAGE


def test_the_same_damage_read_twice_is_counted_not_re_recorded(tmp_path, damaged, files, monkeypatch):
    path, _bad = damaged
    files[FILE_CORPUS] = path
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    verify.arm_at_boot()
    verify.run_armed()
    reg = damage.registry
    before = reg.state(detail=True)["files"][FILE_CORPUS]["incidents"]
    reg._note_verified_damage(FILE_CORPUS, ["articles"], path=path, at="2026-10-06T02:00:00+00:00")
    assert reg.state(detail=True)["files"][FILE_CORPUS]["incidents"] == before + 1
    assert len(_record(tmp_path)["incidents"]) == 1, "one table, read as damaged twice, wrote two records"


def _driver_corrupt():
    err = sqlite3.DatabaseError("database disk image is malformed")
    err.sqlite_errorcode = 11  # type: ignore[attr-defined]
    return err


def test_damage_only_in_the_search_index_tables_is_scoped_as_the_search_index(tmp_path, files, monkeypatch):
    path = tmp_path / "corpus.db"
    _build_store(path, fts=True)
    leaves = _leaf_pages(path, "article_fts_data")
    assert leaves, "the FTS5 index has no data leaf pages in this build"
    _overwrite(path, sorted(random.Random(2).sample(leaves, min(2, len(leaves)))))
    files[FILE_CORPUS] = path
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    verify.arm_at_boot()
    verify.run_armed()
    rec = _record(tmp_path)
    tables = _by_table(rec["verification"][FILE_CORPUS])
    assert tables["article_fts_data"]["verdict"] == VERDICT_DAMAGED
    assert tables["articles"]["verdict"] == VERDICT_OK
    if sqlite3.sqlite_version_info >= (3, 44):  # the virtual table's own integrity check runs from 3.44
        assert tables["article_fts"]["verdict"] == VERDICT_DAMAGED
        assert "inverted index" in tables["article_fts"]["detail"][0]
    [inc] = rec["incidents"]
    assert inc["scope"] == SCOPE_SEARCH_INDEX and inc["route"] == damage.ROUTE_REBUILD_INDEX
    assert damage.registry.latched(FILE_CORPUS)


class _FakeConn:
    """A connection whose ``quick_check`` answers the given rows (what FTS5 does when its own check cannot run)."""

    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql):
        rows = self._rows

        class _Cur:
            def fetchall(self_inner):
                return [(r,) for r in rows]

        return _Cur()

    def set_progress_handler(self, *a):
        pass

    def close(self):
        pass


@pytest.mark.parametrize(
    "answer,verdict",
    [
        (["unable to validate the inverted index for FTS5 table main.article_fts: out of memory"], VERDICT_UNCHECKED),
        (["unable to validate the inverted index for FTS5 table main.article_fts: disk I/O error"], VERDICT_UNCHECKED),
        (["unable to validate the inverted index for FTS5 table main.article_fts: database or disk is full"], VERDICT_UNCHECKED),
        (["unable to validate the inverted index for FTS5 table main.article_fts: database disk image is malformed"], VERDICT_DAMAGED),
        (["malformed inverted index for FTS5 table main.article_fts"], VERDICT_DAMAGED),
        (
            [
                "unable to validate the inverted index for FTS5 table main.article_fts: out of memory",
                "Tree 7 page 7: btreeInitPage() returns error code 11",
            ],
            VERDICT_DAMAGED,
        ),
        (["row 12 missing from index ix_x"], VERDICT_DAMAGED),
        (
            [
                "unable to validate the inverted index for FTS5 table main.article_fts: out of memory",
                "unable to validate the inverted index for FTS5 table main.article_fts: database disk image is malformed",
            ],
            VERDICT_DAMAGED,
        ),
    ],
)
def test_an_error_fts5_reports_as_a_row_is_not_damage_unless_it_is_corruption(answer, verdict):
    """FTS5 answers an error that stopped its own check as a ROW. Not reading is not a verdict (measured on 3.45.1)."""
    out = verify.check_table(Path("unused.db"), "article_fts", opener=lambda _p: _FakeConn(answer))
    assert out["verdict"] == verdict, out
    if verdict == VERDICT_UNCHECKED:
        assert out["detail"] == ["the read ran out of memory"] or "disk" in out["detail"][0], out


@pytest.mark.skipif(sqlite3.sqlite_version_info < (3, 44), reason="the virtual table's own integrity check runs from 3.44")
def test_fts5_running_out_of_memory_on_the_real_driver_is_unchecked_never_damage(tmp_path):
    """The fake pins the row parse; this runs it on the real library. The heap limit is a PROCESS-wide setting that cannot
    be lifted again, so the read runs in a process of its own."""
    import subprocess

    path = tmp_path / "fts.db"
    con = sqlite3.connect(path)
    con.execute(f"PRAGMA page_size={PAGE}")
    con.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT, content TEXT)")
    rng = random.Random(7)
    con.executemany(
        "INSERT INTO articles (title, content) VALUES (?, ?)",
        [(f"title {i}", "".join(rng.choice("abcdefghij ") for _ in range(900))) for i in range(3000)],
    )
    con.execute("CREATE VIRTUAL TABLE article_fts USING fts5(title, content, content='articles', content_rowid='id')")
    con.execute("INSERT INTO article_fts(article_fts) VALUES('rebuild')")
    con.commit()
    con.close()
    code = (
        "import json, sqlite3, sys\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "from src.database import verify\n"
        "keep = sqlite3.connect(':memory:')\n"
        "keep.execute('PRAGMA hard_heap_limit=1000000')\n"
        f"print(json.dumps(verify.check_table(Path({str(path)!r}), 'article_fts')))\n"
    )
    done = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr[-800:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["verdict"] == VERDICT_UNCHECKED, out
    assert out["detail"] == ["the read ran out of memory"], out


def test_the_fts5_integrity_check_does_not_compare_the_index_with_the_articles(tmp_path):
    """The claim the docs make, measured here so it cannot drift: a changed article text behind an external-content
    index still answers ``ok``, which is why the check says it does not verify content."""
    if sqlite3.sqlite_version_info < (3, 44):
        pytest.skip("quick_check on a virtual table runs the module's check from SQLite 3.44")
    path = tmp_path / "ext.db"
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE a(id INTEGER PRIMARY KEY, t TEXT);"
        "CREATE VIRTUAL TABLE f USING fts5(t, content='a', content_rowid='id');"
    )
    con.executemany("INSERT INTO a(t) VALUES (?)", [(f"word{i} body",) for i in range(300)])
    con.execute("INSERT INTO f(f) VALUES('rebuild')")
    con.execute("UPDATE a SET t = 'changed completely' WHERE id = 5")
    con.commit()
    con.close()
    assert verify.check_table(path, "f")["verdict"] == VERDICT_OK


def test_damage_in_the_data_and_in_the_index_together_is_data(tmp_path, files, monkeypatch):
    path = tmp_path / "corpus.db"
    _build_store(path, fts=True)
    _overwrite(path, sorted(random.Random(3).sample(_leaf_pages(path, "article_fts_data"), 1)))
    _overwrite(path, sorted(random.Random(1).sample(_leaf_pages(path, "articles"), 2)))
    files[FILE_CORPUS] = path
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    verify.arm_at_boot()
    verify.run_armed()
    [inc] = _record(tmp_path)["incidents"]
    assert inc["scope"] == SCOPE_DATA, "an index incident softened a data one"


def test_a_lane_file_is_checked_and_latches_only_its_own_file(tmp_path, files, monkeypatch):
    corpus, wiki = tmp_path / "corpus.db", tmp_path / "wiki.db"
    _build_store(corpus, rows=50)
    _build_store(wiki)
    _overwrite(wiki, sorted(random.Random(1).sample(_leaf_pages(wiki, "articles"), 2)))
    files[FILE_CORPUS], files["wiki"] = corpus, wiki
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    verify.arm_at_boot()
    verify.run_armed()
    assert damage.registry.latched("wiki") and not damage.registry.latched(FILE_CORPUS)
    assert sg.StorageGuard().admit() is None, "a damaged Wikipedia file paused corpus collection"


def test_a_stop_ends_the_run_without_a_verdict_and_the_next_start_reads_the_file_again(tmp_path, healthy, files, monkeypatch):
    """Stopped (the app is shutting down) is not 'checked': the file's entry stays ``running``, nothing latches and no
    later table is started."""
    files[FILE_CORPUS] = healthy
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    verify.arm_at_boot()
    started: list[str] = []
    real = verify.check_table

    def stop_after_the_first(path, table, **kw):
        started.append(table)
        out = real(path, table, **kw)
        verify.stop()
        return out

    monkeypatch.setattr(verify, "check_table", stop_after_the_first)
    assert verify.run_armed() is True
    assert started == ["notes"], "a table was started after the stop"
    assert not damage.registry.verifying() and not damage.registry.latched(FILE_CORPUS)
    entry = _record(tmp_path)["verification"][FILE_CORPUS]
    assert entry["state"] == "running" and "verdict" not in entry, entry
    reg2 = DamageRegistry(path_fn=lambda: tmp_path / "database-damage.json")  # the next start, after a CLEAN end
    monkeypatch.setattr(damage, "registry", reg2)
    verify._reset_for_tests()
    monkeypatch.setattr(damage, "_previous_end", lambda: CLEAN)
    plan = verify.plan_boot(previous_end=CLEAN)
    assert plan and plan["trigger"] == verify.TRIGGER_UNFINISHED
    assert plan["files"][0][2] == 0, "a quit is not a failed attempt: the count was not given back"


def test_the_shutdown_stops_the_check():
    """Behaviour: the helper the lifespan calls asks the running check to end. Wiring (an AST, so a comment cannot
    satisfy it): the lifespan calls it after its ``yield`` and before the engine is disposed."""
    import ast

    from src.api import main

    assert not verify._CANCEL.is_set()
    try:
        main._stop_database_check()
        assert verify._CANCEL.is_set(), "the shutdown helper did not ask the check to stop"
    finally:
        verify._CANCEL.clear()  # a stop left set would end every check a later test starts

    tree = ast.parse(_main_source())
    [life] = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "lifespan"]
    yield_line = next(n.lineno for n in ast.walk(life) if isinstance(n, ast.Yield))
    calls = [n for n in ast.walk(life) if isinstance(n, ast.Call)]
    stop = [c.lineno for c in calls if isinstance(c.func, ast.Name) and c.func.id == "_stop_database_check"]
    dispose = [c.lineno for c in calls if isinstance(c.func, ast.Name) and c.func.id == "dispose_engine" and c.lineno > yield_line]
    assert stop and stop[0] > yield_line, "the lifespan does not stop the check on shutdown"
    assert not dispose or stop[0] < dispose[0], "the engine is disposed before the check is asked to stop"


def test_the_detail_lines_are_bounded_when_a_check_answers_many_long_lines():
    long = [f"Tree 5 page {i}: " + "x" * 500 for i in range(40)]
    out = verify.check_table(Path("ignored"), "articles", opener=lambda p: _FakeConn(long))
    assert out["verdict"] == VERDICT_DAMAGED
    assert len(out["detail"]) == verify.DETAIL_LINES and all(len(d) <= verify.DETAIL_CHARS for d in out["detail"])


def test_the_pause_off_means_the_guards_state_does_not_say_verifying(healthy, files, monkeypatch):
    g = sg.StorageGuard(readings_fn=lambda: {})
    _arm(files, healthy, monkeypatch)
    assert g.state()["phase"] == sg.PHASE_VERIFY
    monkeypatch.setenv("OO_DAMAGE_GUARD", "0")
    assert g.state()["phase"] is None and g.admit() is None, "the pause is off and the guard still reports it"
    verify.run_armed()


def test_a_file_the_list_could_not_be_read_from_is_unchecked_unless_its_schema_is_damaged(tmp_path, files, monkeypatch):
    path = tmp_path / "corpus.db"
    _build_store(path, rows=50)
    files[FILE_CORPUS] = path
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    verify.arm_at_boot()

    def refused(p):
        raise sqlite3.OperationalError("database is locked")

    verify.run_armed(opener=refused)
    entry = _record(tmp_path)["verification"][FILE_CORPUS]
    assert entry["verdict"] == VERDICT_UNCHECKED and entry["reason"] and not damage.registry.latched(FILE_CORPUS)


def test_a_damaged_schema_page_latches_the_file_and_names_the_schema(tmp_path, files, monkeypatch):
    """The list of tables itself cannot be read: that is damage, not 'unchecked' (the plaintext path; an encrypted
    file reads the same through the chained error, see the connect test above)."""
    path = tmp_path / "corpus.db"
    _build_store(path, rows=50)
    con = sqlite3.connect(path)
    for i in range(120):  # a schema that spans several pages, so one leaf can go and the file still opens
        con.execute(f"CREATE TABLE extra_table_with_a_long_name_{i} (id INTEGER PRIMARY KEY, a TEXT, b TEXT, c TEXT)")
    con.commit()
    con.close()
    leaves = [pg for pg in _leaf_pages(path, "sqlite_schema") if pg != 1]
    assert leaves, "the schema fits one page in this build"
    _overwrite(path, [leaves[len(leaves) // 2]])
    files[FILE_CORPUS] = path
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    verify.arm_at_boot()
    verify.run_armed()
    entry = _record(tmp_path)["verification"][FILE_CORPUS]
    assert entry["verdict"] == VERDICT_DAMAGED, entry
    assert [t["table"] for t in entry["tables"]] == ["(schema)"]
    assert damage.registry.latched(FILE_CORPUS)


def test_the_progress_total_is_the_count_of_tables_the_run_will_read(healthy, files, monkeypatch):
    files[FILE_CORPUS] = healthy
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    verify.arm_at_boot()
    seen: list[dict] = []
    real = damage.registry.verification_progress

    def spy(file_key, table, index):
        seen.append(dict(damage.registry._verifying or {}))
        real(file_key, table, index)

    monkeypatch.setattr(damage.registry, "verification_progress", spy)
    verify.run_armed()
    assert seen and all(v["total"] == 2 for v in seen), seen  # articles and notes


def test_the_check_started_is_on_disk_before_the_first_table_is_read(tmp_path, healthy, files, monkeypatch):
    """A process killed mid-check leaves ``state: running`` behind: that is how the next start knows."""
    files[FILE_CORPUS] = healthy
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    verify.arm_at_boot()
    seen: list[dict] = []

    def spy(path, table, **kw):
        seen.append(dict(_record(tmp_path)["verification"][FILE_CORPUS]))
        raise SystemExit  # as a kill would: nothing after this line runs

    monkeypatch.setattr(verify, "check_table", spy)
    with pytest.raises(SystemExit):
        verify._run_plan(verify._PLAN, opener=None)
    assert seen and seen[0]["state"] == "running" and seen[0]["attempts"] == 1
    reg2 = DamageRegistry(path_fn=lambda: tmp_path / "database-damage.json")
    assert reg2.previous_verification(FILE_CORPUS)["state"] == "running", "the next start could not tell"


# --------------------------------------------------------------------------- #
#  the rest of the app waits for it, and says why
# --------------------------------------------------------------------------- #
def _arm(files, healthy, monkeypatch):
    files[FILE_CORPUS] = healthy
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    assert verify.arm_at_boot()


def test_resume_anyway_is_refused_with_a_sentence_while_the_check_reads_the_files(files, healthy, monkeypatch):
    _arm(files, healthy, monkeypatch)
    g = sg.StorageGuard(readings_fn=lambda: {"wal_bytes": 10, "disk_free_bytes": 10**12})
    out = g.override(reason="test")
    assert out["overridden"] is False and out["engaged"] is False
    monkeypatch.setenv("OO_STORAGE_GUARD", "0")
    assert g.admit() == "verifying", "disabling the resource guard is not saying 'write while the files are read'"


def test_an_engaged_limit_names_itself_first_and_the_refusal_says_the_check(files, healthy, monkeypatch):
    # the one engaged-guard builder
    from tests.test_database_damage import _engaged_guard  # noqa: PLC0415

    g = _engaged_guard(monkeypatch)
    _arm(files, healthy, monkeypatch)
    st = g.state()
    assert st["override_refusal"] == {"kind": "verifying", "frame": sg.FRAME_OVERRIDE_VERIFYING, "vars": {}}
    out = g.override(reason="test")
    assert out["overridden"] is False and out["refused"]["kind"] == "verifying"
    assert g.admit() == "wal", "the storage limit still names itself first while both hold"


def test_the_state_carries_the_progress_note_and_the_phase_once_the_run_has_begun(files, healthy, monkeypatch):
    g = sg.StorageGuard(readings_fn=lambda: {})
    _arm(files, healthy, monkeypatch)
    st = g.state()
    assert st["phase"] == sg.PHASE_VERIFY
    assert st["database_damage"]["notes"] == [], "no number to say before the run has counted its tables"
    reg = damage.registry
    reg.verification_begin(7)
    reg.verification_progress(FILE_CORPUS, "articles", 3)
    note = g.state()["database_damage"]["notes"][0]
    assert note["kind"] == "verifying" and note["frame"] == damage.FRAME_VERIFYING
    assert note["vars"] == {"index": 3, "total": 7}
    assert "table 3 of 7" in g.state()["reason"]
    assert g.state()["engaged"] is False and g.state()["notes"] == []
    verify.run_armed()
    assert g.state()["phase"] is None and g.state()["database_damage"]["notes"] == []


def test_a_latched_file_names_damage_before_the_check_and_the_check_never_hides_it(registry, files, healthy, monkeypatch):
    registry.note(FILE_CORPUS, _driver_corrupt(), statement="SELECT 1")
    _arm(files, healthy, monkeypatch)
    g = sg.StorageGuard(readings_fn=lambda: {})
    assert g.admit() == "damage" and g.phase() == sg.PHASE_DAMAGE


def test_the_status_carries_the_check_briefly_and_the_bundle_member_in_full(tmp_path, damaged, files, monkeypatch):
    path, _bad = damaged
    files[FILE_CORPUS] = path
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    verify.arm_at_boot()
    verify.run_armed()
    brief = damage.registry.state()["verification"][FILE_CORPUS]
    assert "tables" not in brief and brief["damaged"] == ["articles"] and brief["unchecked"] == []
    full = damage.diagnostics_member(10**6)["verification"][FILE_CORPUS]
    assert {t["table"] for t in full["tables"]} == {"articles", "notes"}
    tiny = damage.diagnostics_member(1024)
    assert tiny["verification"][FILE_CORPUS]["damaged"] == ["articles"] and "tables" not in tiny["verification"][FILE_CORPUS]
    assert tiny["verification_tables_dropped_to_fit"] is True and "error" not in tiny


def test_off_peak_maintenance_does_not_run_while_the_check_reads_the_files(files, healthy, monkeypatch):
    from src.scheduler.settings import SchedulerSettings

    sched = runner.BackgroundScheduler(run_once_fn=lambda: {}, settings_provider=lambda: SchedulerSettings())
    _arm(files, healthy, monkeypatch)
    assert sched._run_off_peak_maintenance() is False
    assert sched.status()["maintenance_skips"].get("database_check") == 1


def test_the_housekeeping_lane_waits_for_the_check_and_says_why(registry, monkeypatch):
    """The lane asks the guard before every kind: while the check reads the files nothing in it writes."""
    import src.ingest.fetch_release as fr
    from src.scheduler import runner as rn

    ran: list[str] = []
    monkeypatch.setitem(rn._LANE_STEPS, "law", lambda s, f, st: ran.append("law") or {"ran": True})
    monkeypatch.setitem(rn._LANE_STEPS, "backfill", lambda s, f, st: ran.append("backfill") or {"ran": True})
    monkeypatch.setattr(rn, "_lane_pending_kinds", lambda settings: ["law", "backfill"])
    monkeypatch.setattr(rn, "_lane_kind_order", lambda kinds: list(kinds))
    monkeypatch.setattr(rn, "_activity", lambda *a, **k: None)
    monkeypatch.setattr(fr, "wrap_fetcher", lambda f, s: f)
    monkeypatch.setattr(sg, "storage_guard", sg.StorageGuard(readings_fn=lambda: {}))
    registry.verification_arm(verify.TRIGGER_UNCLEAN_END)
    out = rn.run_housekeeping_lane(object(), object(), object())
    assert ran == [] and out == {"_paused": {"reason": "storage (verifying)", "remaining": ["law", "backfill"]}}
    registry.verification_end()
    assert rn.run_housekeeping_lane(object(), object(), object()) == {"law": {"ran": True}, "backfill": {"ran": True}}


def test_the_pass_loop_waits_in_the_verifying_phase_and_leaves_when_the_check_ends(registry, monkeypatch):
    import time as _time

    from src.scheduler.settings import SchedulerSettings

    monkeypatch.setattr(sg, "storage_guard", sg.StorageGuard(readings_fn=lambda: {}))
    sched = runner.BackgroundScheduler(run_once_fn=lambda: {}, settings_provider=lambda: SchedulerSettings())
    sched._storage_pause_poll_s = 0.02
    registry.verification_arm(verify.TRIGGER_UNCLEAN_END)
    done = threading.Event()

    def _wait():
        sched._wait_while_storage_paused()
        done.set()

    t = threading.Thread(target=_wait, daemon=True)
    t.start()
    try:
        deadline = _time.monotonic() + 5.0
        while runner.current_phase() != "paused-verifying" and _time.monotonic() < deadline:
            _time.sleep(0.02)
        assert runner.current_phase() == "paused-verifying"
        assert not done.is_set() and sched.status()["next_run"] is None, "no stale countdown while it waits"
        registry.verification_end()
        assert done.wait(5.0), "the loop did not leave the wait when the check ended"
        assert runner.current_phase() is None
    finally:
        sched._stop.set()
        t.join(5.0)
        runner._phase_set(None)


def test_the_wiki_loop_waits_while_the_check_reads_the_files_and_carries_on_after(registry):
    from tests.test_database_damage import _FakeRunner  # noqa: PLC0415 - the lane runner stand-in

    f = _FakeRunner()
    registry.verification_arm(verify.TRIGGER_UNCLEAN_END)
    assert f.runner.run_until_stopped(max_drains=3) == 0
    assert f.drained == 0 and f.runner.paused_reason == f.wr.CHECKING == "database-check"
    registry.verification_end()
    assert f.runner.run_until_stopped(max_drains=2) == 2 and f.runner.paused_reason is None


def test_the_wiki_lane_tiers_stop_inside_a_window_when_the_check_is_armed(registry):
    from tests.test_database_damage import _idle_runner  # noqa: PLC0415

    ran: list = []
    r = _idle_runner(ran, on_index=lambda: registry.verification_arm(verify.TRIGGER_UNCLEAN_END))
    r.idle(10.0)
    assert ran == ["index"], ran


# --------------------------------------------------------------------------- #
#  the boot: where it is armed, where it runs, in what order
# --------------------------------------------------------------------------- #
def test_the_check_is_the_boot_sequences_first_step():
    from src.api import boot_sequence

    assert boot_sequence.STEPS[0] == "verify-database" and boot_sequence.STEPS[1] == "warm-cache"


def test_the_boot_step_runs_the_armed_check_and_is_skipped_when_nothing_is_armed(healthy, files, monkeypatch):
    from src.api import boot_sequence

    with pytest.raises(boot_sequence._Skipped):
        boot_sequence._verify_database()
    _arm(files, healthy, monkeypatch)
    boot_sequence._verify_database()
    assert not damage.registry.verifying()
    assert damage.registry.state()["verification"][FILE_CORPUS]["state"] == "done"


def test_the_boot_sequence_runs_a_real_armed_check_and_the_wait_is_over_when_it_returns(healthy, files, monkeypatch):
    from src.api import boot_sequence

    _arm(files, healthy, monkeypatch)
    assert damage.registry.verifying()
    monkeypatch.setattr(boot_sequence, "_rollup_first_build", lambda: None)
    monkeypatch.setattr(boot_sequence, "_start_reindex", lambda: None)
    warmed: list[bool] = []
    try:
        boot_sequence.run(lambda: warmed.append(damage.registry.verifying()))
    finally:
        boot_sequence._reset()
    assert warmed == [False], "the cache warm-up started while the check still held collection"
    assert not damage.registry.verifying(), "the boot sequence returned with collection still waiting for the check"
    assert damage.registry.state()["verification"][FILE_CORPUS]["state"] == "done"


def _main_source() -> str:
    return (ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")


def test_the_check_is_armed_before_the_upkeeps_first_slow_step_and_withdrawn_when_no_thread_took_it(
    files, healthy, monkeypatch
):
    """The upkeep opens with the planner statistics (minutes on a large store): armed after it, an operator who goes
    online in that time would start a pass that writes to a file nothing has read. And an upkeep that ends before
    the boot-sequence thread exists leaves nothing to wait for."""
    import src.api.main as M
    import src.api.startup_status as status

    files[FILE_CORPUS] = healthy
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    monkeypatch.delenv("OO_NO_SCHEDULER", raising=False)
    seen: dict[str, bool] = {}

    class Stop(Exception):
        pass

    def first_phase(name, *a, **k):
        seen["armed_at_first_phase"] = damage.registry.verifying()
        raise Stop

    monkeypatch.setattr(status, "mark_phase", first_phase)
    with pytest.raises(Stop):
        M._run_startup_upkeep()
    assert seen == {"armed_at_first_phase": True}
    assert not damage.registry.verifying() and verify._PLAN is None, "the wait outlived an upkeep that ended"


def test_the_scheduler_off_arms_nothing(files, healthy, monkeypatch):
    import src.api.main as M

    files[FILE_CORPUS] = healthy
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    assert M._arm_database_check() is False and not damage.registry.verifying()


def test_the_wait_is_left_to_the_thread_that_took_the_check(files, healthy, monkeypatch):
    """Once the boot-sequence thread is started the wait is its to end (``run_armed`` does, however the run ends);
    the upkeep's own ending must not cut it short."""
    import src.api.main as M

    _arm(files, healthy, monkeypatch)
    verify.hand_over()
    M._ends_the_check_wait(lambda: None)()
    assert damage.registry.verifying() and verify._PLAN is not None
    assert verify.run_armed() is True and not damage.registry.verifying()


def test_a_new_arming_starts_not_handed_over(tmp_path, files, healthy, monkeypatch):
    """The hand-over belongs to one arming: a file that appears after the first check is read gets its own."""
    import shutil

    _arm(files, healthy, monkeypatch)
    verify.hand_over()
    assert verify.run_armed() is True
    second = tmp_path / "wikipedia.db"
    shutil.copy(healthy, second)
    files[FILE_WIKI] = second
    assert verify.arm_at_boot() is True and [k for k, _p, _a in verify._PLAN["files"]] == [FILE_WIKI]
    assert verify._HANDED_OVER is False
    verify.withdraw_unless_handed_over()
    assert not damage.registry.verifying(), "an arming nobody took was left holding collection"


def test_a_damaged_verdict_survives_a_restart_and_is_read_again_until_the_file_reads_clean(tmp_path, files, damaged, monkeypatch):
    """The latch lives in memory and the ledger reads the next start as clean: without the record the finding would
    be forgotten and collection would write on into a file the check had found damaged."""
    path, _bad = damaged
    files[FILE_CORPUS] = path
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    assert verify.arm_at_boot() is True and verify.run_armed() is True
    assert damage.registry.latched(FILE_CORPUS)

    for _ in range(2):  # restart after restart, each one read as a clean end: the file is read again and latches again
        _new_process(tmp_path, monkeypatch)
        monkeypatch.setattr(damage, "_previous_end", lambda: CLEAN)
        assert verify.arm_at_boot() is True, "the damaged verdict was forgotten at the restart"
        assert verify._PLAN["trigger"] == verify.TRIGGER_DAMAGE_FOUND
        assert verify.run_armed() is True
        assert damage.registry.latched(FILE_CORPUS), "a file the check read as damaged again was not latched"

    healthy_again = tmp_path / "healthy-again.db"  # the file is repaired or replaced
    _build_store(healthy_again)
    files[FILE_CORPUS] = healthy_again
    _new_process(tmp_path, monkeypatch)
    assert verify.arm_at_boot() is True and verify.run_armed() is True
    assert not damage.registry.latched(FILE_CORPUS)
    assert damage.registry.state(detail=True)["verification"][FILE_CORPUS]["verdict"] == VERDICT_OK
    _new_process(tmp_path, monkeypatch)
    assert verify.arm_at_boot() is False, "a file that reads clean is not read again at every start"


def test_a_replaced_file_forgets_the_verdict_about_the_old_one(tmp_path, files, damaged, monkeypatch):
    path, _bad = damaged
    files[FILE_CORPUS] = path
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    verify.arm_at_boot()
    verify.run_armed()
    damage.registry.verification_forget(FILE_CORPUS)
    assert FILE_CORPUS not in _record(tmp_path)["verification"]
    _new_process(tmp_path, monkeypatch)
    monkeypatch.setattr(damage, "_previous_end", lambda: CLEAN)
    assert verify.arm_at_boot() is False


def test_quitting_during_the_check_many_times_never_skips_it(tmp_path, healthy, files, monkeypatch):
    """A quit is the operator's, not the check's failure: only a check that ends by being killed counts."""
    files[FILE_CORPUS] = healthy
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    for i in range(MAX_VERIFY_ATTEMPTS + 2):
        _new_process(tmp_path, monkeypatch)
        monkeypatch.setattr(damage, "_previous_end", (lambda: UNCLEAN) if i == 0 else (lambda: CLEAN))
        verify._CANCEL.clear()
        assert verify.arm_at_boot() is True, "the check was skipped after quits"
        real = verify.check_table

        def stop_first(path, table, _real=real, **kw):
            out = _real(path, table, **kw)
            verify.stop()
            return out

        monkeypatch.setattr(verify, "check_table", stop_first)
        verify.run_armed()
        monkeypatch.setattr(verify, "check_table", real)
    verify._CANCEL.clear()


def test_a_stop_before_a_file_is_begun_spends_no_attempt(tmp_path, healthy, files, monkeypatch):
    files[FILE_CORPUS] = healthy
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    verify.arm_at_boot()
    verify.stop()
    verify.run_armed()
    entry = _record(tmp_path)["verification"][FILE_CORPUS]
    assert entry["state"] == "owed" and entry["attempts"] == 0, entry  # still owed, nothing begun
    verify._CANCEL.clear()


def test_a_record_with_a_non_numeric_attempt_count_does_not_stop_the_plan(tmp_path, files, healthy, monkeypatch):
    files[FILE_CORPUS] = healthy
    monkeypatch.setattr(damage, "_previous_end", lambda: CLEAN)
    doc = tmp_path / "database-damage.json"
    doc.write_text(
        json.dumps({"verification": {FILE_CORPUS: {"state": "running", "process": "another", "attempts": "three"}}}),
        encoding="utf-8",
    )
    _new_process(tmp_path, monkeypatch)
    assert verify.arm_at_boot() is True and verify._PLAN["files"][0][2] == 0


def test_a_check_result_that_arrives_after_the_file_was_replaced_is_dropped(tmp_path, files, damaged, monkeypatch):
    """A restore during the boot check releases the latch and forgets the verdict; the check's own result for the OLD file
    must not latch the new, healthy one."""
    path, _bad = damaged
    files[FILE_CORPUS] = path
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    verify.arm_at_boot()
    real = verify.check_table
    done = []

    def replace_midway(p, table, **kw):
        out = real(p, table, **kw)
        if not done:
            done.append(True)
            damage.registry.verification_forget(FILE_CORPUS)  # the restore swapped the file in
        return out

    monkeypatch.setattr(verify, "check_table", replace_midway)
    verify.run_armed()
    assert not damage.registry.latched(FILE_CORPUS), "a verdict about the old file latched the new one"
    assert FILE_CORPUS not in _record(tmp_path).get("verification", {})


def test_a_second_arming_changes_nothing(files, healthy, monkeypatch):
    _arm(files, healthy, monkeypatch)
    plan = verify._PLAN
    assert verify.arm_at_boot() is True and verify._PLAN is plan


def _new_process(tmp_path, monkeypatch):
    reg = DamageRegistry(path_fn=lambda: tmp_path / "database-damage.json")
    monkeypatch.setattr(damage, "registry", reg)
    verify._reset_for_tests()
    return reg


def test_an_armed_check_is_recorded_as_owed_before_anything_is_read(tmp_path, files, healthy, monkeypatch):
    _arm(files, healthy, monkeypatch)
    record = _record(tmp_path)
    assert record["verification"][FILE_CORPUS]["state"] == "owed"
    assert record["verification"][FILE_CORPUS]["trigger"] == verify.TRIGGER_UNCLEAN_END


def test_a_session_that_ended_before_the_check_began_does_not_cancel_it(tmp_path, files, healthy, monkeypatch):
    """The ledger reads that session as a CLEAN end; the owed record is what keeps the earlier unexpected stop from
    being forgotten."""
    _arm(files, healthy, monkeypatch)  # armed, and the app is closed before the sequence's first step
    _new_process(tmp_path, monkeypatch)
    monkeypatch.setattr(damage, "_previous_end", lambda: CLEAN)
    assert verify.arm_at_boot() is True, "the owed check was forgotten"
    assert verify._PLAN["trigger"] == verify.TRIGGER_UNFINISHED
    assert verify.run_armed() is True
    assert damage.registry.state(detail=True)["verification"][FILE_CORPUS]["state"] == "done"
    _new_process(tmp_path, monkeypatch)
    assert verify.arm_at_boot() is False, "a finished check is not owed again"


def test_a_boot_that_stays_locked_owes_the_check(tmp_path, files, healthy, monkeypatch):
    files[FILE_CORPUS] = healthy
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    verify.owe_at_locked_boot()
    assert not damage.registry.verifying(), "a locked boot cannot read the files and arms nothing"
    assert _record(tmp_path)["verification"][FILE_CORPUS]["state"] == "owed"
    _new_process(tmp_path, monkeypatch)  # closed from the lock screen: the next session's ledger says clean
    monkeypatch.setattr(damage, "_previous_end", lambda: CLEAN)
    assert verify.arm_at_boot() is True


def test_a_locked_boot_followed_by_the_unlock_in_one_process_still_checks(tmp_path, files, healthy, monkeypatch):
    files[FILE_CORPUS] = healthy
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    verify.owe_at_locked_boot()
    assert verify.arm_at_boot() is True and verify.run_armed() is True
    assert damage.registry.state(detail=True)["verification"][FILE_CORPUS]["state"] == "done"


def test_owing_does_not_count_toward_the_attempt_cap(tmp_path, files, healthy, monkeypatch):
    """Only a check that BEGINS counts: a machine that is closed from the lock screen many times is not a machine
    whose check keeps dying."""
    files[FILE_CORPUS] = healthy
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    verify.owe_at_locked_boot()
    for _ in range(MAX_VERIFY_ATTEMPTS + 2):
        _new_process(tmp_path, monkeypatch)
        monkeypatch.setattr(damage, "_previous_end", lambda: CLEAN)  # each locked session ended cleanly
        verify.owe_at_locked_boot()
    _new_process(tmp_path, monkeypatch)
    assert verify.arm_at_boot() is True and verify._PLAN["files"][0][2] == 0


def _locked_boot_then_unlock(tmp_path, monkeypatch, files, path, previous_end):
    """One process of the DEFAULT (encrypted) install: it boots LOCKED (which owes the check) and the unlock, in the SAME
    process, plans it again. Returns whether the unlock armed a check."""
    _new_process(tmp_path, monkeypatch)
    files[FILE_CORPUS] = path
    monkeypatch.setattr(damage, "_previous_end", lambda: previous_end)
    verify.owe_at_locked_boot()
    return verify.arm_at_boot()


def test_a_damaged_verdict_is_read_again_by_a_boot_that_starts_locked_and_is_then_unlocked(tmp_path, damaged, files, monkeypatch):
    """The owed record a locked boot writes over the earlier process's entry used to hide that entry from the unlock's
    plan (the deep delta read's B1): the damaged verdict was erased and collection wrote into the file again."""
    path, _bad = damaged
    _latch_by_check(files, path, monkeypatch)
    assert _locked_boot_then_unlock(tmp_path, monkeypatch, files, path, CLEAN) is True, "the earlier damaged verdict was forgotten"
    assert verify.run_armed() is True
    assert damage.registry.latched(FILE_CORPUS), "the file the check had found damaged was not read again, and was released"
    assert damage.registry.state(detail=True)["verification"][FILE_CORPUS]["verdict"] == VERDICT_DAMAGED


def test_an_unfinished_check_is_read_again_by_a_boot_that_starts_locked_and_is_then_unlocked(tmp_path, healthy, files, monkeypatch):
    files[FILE_CORPUS] = healthy
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    assert verify.arm_at_boot() is True
    damage.registry.verification_file_started(  # the check began and the operator quit before it ended
        FILE_CORPUS, path=healthy, trigger=verify.TRIGGER_UNCLEAN_END, tables_total=2, attempts=1
    )
    assert _locked_boot_then_unlock(tmp_path, monkeypatch, files, healthy, CLEAN) is True, "the unfinished check was forgotten"
    assert verify._PLAN["trigger"] == verify.TRIGGER_UNFINISHED and verify._PLAN["files"][0][2] == 1, "its attempts were not carried"


def test_the_attempt_cap_still_trips_when_every_start_boots_locked_and_is_then_unlocked(tmp_path, healthy, files, monkeypatch):
    """What the cap protects: a check that kills the process (out of memory on a small machine) must not run at every
    start. The default install boots locked EVERY time, so the cap has to count through the owed record."""
    seen: list[int] = []
    armed = True
    for start in range(MAX_VERIFY_ATTEMPTS + 2):
        armed = _locked_boot_then_unlock(tmp_path, monkeypatch, files, healthy, UNCLEAN if start == 0 else CLEAN)
        if not armed:
            break
        before = verify._PLAN["files"][0][2]
        seen.append(before)
        damage.registry.verification_file_started(  # begun, and the process was killed
            FILE_CORPUS, path=healthy, trigger=verify.TRIGGER_UNCLEAN_END, tables_total=2, attempts=before + 1
        )
    assert seen == list(range(MAX_VERIFY_ATTEMPTS)), seen
    assert armed is False and damage.registry.state(detail=True)["verification"][FILE_CORPUS]["state"] == "skipped"


def test_a_check_owed_by_a_locked_boot_that_was_closed_from_the_lock_screen_is_still_owed_at_the_next_locked_boot(
    tmp_path, healthy, files, monkeypatch
):
    files[FILE_CORPUS] = healthy
    _new_process(tmp_path, monkeypatch)
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    verify.owe_at_locked_boot()  # the session after the unexpected stop, closed from the lock screen
    assert _locked_boot_then_unlock(tmp_path, monkeypatch, files, healthy, CLEAN) is True
    assert verify._PLAN["trigger"] == verify.TRIGGER_UNFINISHED


def test_the_lifespan_owes_the_check_on_a_locked_boot_and_the_upkeep_hands_it_over():
    """Wiring, as an AST (a comment cannot satisfy it): the lifespan's locked branch calls ``owe_at_locked_boot`` and its
    unlocked branch ``run_deferred_startup``; the upkeep calls ``verify.hand_over()`` after it starts the boot-sequence
    thread (without it the upkeep's end withdraws the plan the thread was about to run)."""
    import ast

    tree = ast.parse(_main_source())

    def calls(node):
        return [
            (n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None), n.lineno)
            for n in ast.walk(node)
            if isinstance(n, ast.Call)
        ]

    [life] = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "lifespan"]
    [branch] = [
        n
        for n in ast.walk(life)
        if isinstance(n, ast.If) and "startswith" in ast.unparse(n.test) and "unlocked" in ast.unparse(n.test)
    ]
    assert "run_deferred_startup" in [c for c, _ in sum((calls(b) for b in branch.body), [])]
    assert "owe_at_locked_boot" in [c for c, _ in sum((calls(b) for b in branch.orelse), [])], (
        "a locked boot does not record the check as owed"
    )
    [upkeep] = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_run_startup_upkeep"]
    found = calls(upkeep)
    thread_start = [ln for c, ln in found if c == "start"]
    hand_over = [ln for c, ln in found if c == "hand_over"]
    assert hand_over and thread_start and max(thread_start) < hand_over[0], "the upkeep does not hand the check over after it starts its thread"


def test_an_owed_record_is_not_written_over_a_file_this_process_has_begun(tmp_path, files, healthy, monkeypatch):
    _arm(files, healthy, monkeypatch)
    reg = damage.registry
    reg.verification_file_started(FILE_CORPUS, path=healthy, trigger=verify.TRIGGER_UNCLEAN_END, tables_total=2, attempts=1)
    reg.verification_file_owed(FILE_CORPUS, path=healthy, trigger=verify.TRIGGER_UNCLEAN_END, attempts=0)
    assert reg.state(detail=True)["verification"][FILE_CORPUS]["state"] == "running"


def test_the_module_names_no_write_statement():
    """The module never names a write statement: reading is the whole of what it does."""
    src = (ROOT / "src" / "database" / "verify.py").read_text(encoding="utf-8")
    code = re.sub(r'"""(?:.|\n)*?"""', "", src)
    for word in ("INSERT", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "VACUUM", "REINDEX", "journal_mode", "wal_checkpoint"):
        assert word not in code, f"verify.py names {word!r}"
    assert "query_only=ON" in code


def test_every_check_string_is_in_the_twelve_locales_translated():
    keys = [
        damage.FRAME_VERIFYING,
        damage.FRAME_RECHECKING,
        damage.FRAME_CHECK_STOPPED,
        sg.FRAME_OVERRIDE_VERIFYING,
        "Paused: checking the data files after an unexpected stop",
    ]
    base = json.loads((ROOT / "src/static/locales/en.json").read_text(encoding="utf-8"))
    for lang_file in sorted((ROOT / "src/static/locales").glob("*.json")):
        d = json.loads(lang_file.read_text(encoding="utf-8"))
        for k in keys:
            assert k in d and d[k], f"{lang_file.name} lacks {k[:40]!r}"
            if lang_file.name != "en.json":
                assert d[k] != k or lang_file.name == "en.json", f"{lang_file.name} carries the English"
                for ph in re.findall(r"\{\w+\}", k):
                    assert ph in d[k], f"{lang_file.name} lost {ph} in {k[:40]!r}"
    assert all(k in base for k in keys)


# --------------------------------------------------------------------------- #
#  a start of collection re-reads what the check reported, and releases only on a clean read (E2 exit 1)
# --------------------------------------------------------------------------- #
def _latch_by_check(files, path, monkeypatch, key=FILE_CORPUS):
    """Run the start-up check over ``path`` so the file is latched BY THE CHECK (``check_tables`` set)."""
    files[key] = path
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    assert verify.arm_at_boot() is True
    assert verify.run_armed() is True
    assert damage.registry.latched(key)


def _join_rechecks(timeout: float = 30.0) -> None:
    """Wait for every re-read thread a start of collection began."""
    for t in [t for t in threading.enumerate() if t.name == "oo-database-recheck"]:
        t.join(timeout)
        assert not t.is_alive(), "a re-read did not end"


def _file_state(key=FILE_CORPUS) -> dict:
    return damage.registry.state(detail=True)["files"][key]


def _heal(path: Path) -> None:
    """The damaged file reads clean again (the same path, as a repaired or restored-over file would)."""
    fresh = path.with_name("fresh.db")
    _build_store(fresh)
    fresh.replace(path)


def test_a_start_re_reads_the_reported_tables_and_a_file_that_still_reads_damaged_stays_latched(tmp_path, damaged, files, monkeypatch):
    path, _bad = damaged
    _latch_by_check(files, path, monkeypatch)
    assert _file_state()["check_tables"] == ["articles"]
    before = _file_state()["incidents"]

    assert damage.retry_for_collection_start("the network toggle went online") == [], "a check-found latch was released unread"
    assert damage.registry.latched(FILE_CORPUS), "the latch was dropped while the tables were being read"
    _join_rechecks()

    assert damage.registry.latched(FILE_CORPUS), "a table that still reads damaged did not keep the latch"
    st = _file_state()
    assert st["check_tables"] == ["articles"] and st["retries"] == 1 and st["incidents"] == before + 1
    assert "rechecking" not in st, "the claim on the file outlived the read"
    assert damage.registry.state(detail=True)["verification"][FILE_CORPUS]["verdict"] == VERDICT_DAMAGED
    assert sg.StorageGuard().admit() == "damage"


def test_a_start_releases_a_check_found_latch_only_after_the_reported_tables_read_clean(tmp_path, damaged, files, monkeypatch):
    path, _bad = damaged
    _latch_by_check(files, path, monkeypatch)
    _heal(path)

    assert damage.retry_for_collection_start("the network toggle went online") == []
    _join_rechecks()

    assert not damage.registry.latched(FILE_CORPUS), "a table that read clean did not release the latch"
    assert "check_tables" not in _file_state()
    assert sg.StorageGuard().admit() is None, "collection is still held after the latch was released"
    entry = damage.registry.state(detail=True)["verification"][FILE_CORPUS]
    assert entry["verdict"] == VERDICT_OK and entry["rechecked_at"]
    assert _by_table(entry)["articles"]["verdict"] == VERDICT_OK and _by_table(entry)["notes"]["verdict"] == VERDICT_OK
    # What the record says is what the next start decides on: a file that read clean is not read again at every start.
    _new_process(tmp_path, monkeypatch)
    monkeypatch.setattr(damage, "_previous_end", lambda: CLEAN)
    assert verify.arm_at_boot() is False, "the clean re-read was not written into the record"


def test_only_the_reported_tables_are_re_read(damaged, files, monkeypatch):
    path, _bad = damaged
    _latch_by_check(files, path, monkeypatch)
    seen: list[str] = []
    real = verify.check_table
    monkeypatch.setattr(verify, "check_table", lambda p, t, **kw: (seen.append(t), real(p, t, **kw))[1])
    damage.retry_for_collection_start("t")
    _join_rechecks()
    assert seen == ["articles"], seen


def test_the_latch_holds_while_the_re_read_runs_and_says_how_far_it_is_and_a_second_start_starts_no_second_read(
    damaged, files, monkeypatch
):
    path, _bad = damaged
    _latch_by_check(files, path, monkeypatch)
    _heal(path)
    gate, reached = threading.Event(), threading.Event()
    real = verify.check_table

    def slow(p, t, **kw):
        reached.set()
        assert gate.wait(30)
        return real(p, t, **kw)

    monkeypatch.setattr(verify, "check_table", slow)
    damage.retry_for_collection_start("first")
    assert reached.wait(30)
    try:
        assert damage.registry.latched(FILE_CORPUS) and sg.StorageGuard().admit() == "damage"
        [note] = [n for n in damage.registry.notes() if n["kind"] == "verifying"]
        assert note["frame"] == damage.FRAME_RECHECKING and note["file"] == FILE_CORPUS
        assert note["vars"] == {"index": 1, "total": 1}
        damage.retry_for_collection_start("second")  # a second click while it reads
        assert len([t for t in threading.enumerate() if t.name == "oo-database-recheck"]) == 1
    finally:
        gate.set()
    _join_rechecks()
    assert not damage.registry.latched(FILE_CORPUS)
    assert _file_state()["retries"] == 1, "the second click counted as a retry of a read that was already running"


def test_a_table_that_could_not_be_read_keeps_the_latch(tmp_path, damaged, files, monkeypatch):
    path, _bad = damaged
    _latch_by_check(files, path, monkeypatch)
    _heal(path)
    monkeypatch.setattr(
        verify, "check_table", lambda p, t, **kw: {"table": t, "verdict": VERDICT_UNCHECKED, "seconds": 0.0, "detail": ["the file was busy"]}
    )
    damage.retry_for_collection_start("t")
    _join_rechecks()
    assert damage.registry.latched(FILE_CORPUS), "not reading a table is not a clean verdict"
    assert _file_state()["check_tables"] == ["articles"]
    entry = damage.registry.state(detail=True)["verification"][FILE_CORPUS]
    assert _by_table(entry)["articles"]["verdict"] == VERDICT_DAMAGED and entry["verdict"] == VERDICT_DAMAGED, (
        "a read that could not happen replaced a finding of damage in the record"
    )
    _new_process(tmp_path, monkeypatch)
    monkeypatch.setattr(damage, "_previous_end", lambda: CLEAN)
    assert verify.arm_at_boot() is True, "the finding was forgotten at the next start"


def test_a_table_that_reads_clean_leaves_the_set_and_the_one_that_does_not_stays(tmp_path, damaged, files, monkeypatch):
    path, _bad = damaged
    _latch_by_check(files, path, monkeypatch)
    damage.registry._note_verified_damage(FILE_CORPUS, ["articles", "notes"], path=path, at="2026-10-06T02:00:00+00:00")
    assert _file_state()["check_tables"] == ["articles", "notes"]

    def answer(p, t, **kw):
        return {"table": t, "verdict": VERDICT_OK if t == "notes" else VERDICT_DAMAGED, "seconds": 0.0}

    monkeypatch.setattr(verify, "check_table", answer)
    damage.retry_for_collection_start("t")
    _join_rechecks()
    assert damage.registry.latched(FILE_CORPUS)
    assert _file_state()["check_tables"] == ["articles"], "a table that read clean stayed in the set to be read again"
    entry = damage.registry.state(detail=True)["verification"][FILE_CORPUS]
    assert _by_table(entry)["notes"]["verdict"] == VERDICT_OK and entry["verdict"] == VERDICT_DAMAGED
    assert "check_tables" not in _record(tmp_path)["files"][FILE_CORPUS], "an in-memory set was written to the record"
    assert "rechecking" not in _record(tmp_path)["files"][FILE_CORPUS]


def test_a_latch_a_failed_read_set_is_released_by_the_start_as_before_with_no_re_read(tmp_path, files, healthy, monkeypatch):
    files[FILE_CORPUS] = healthy
    reg = damage.registry
    assert reg.note(FILE_CORPUS, _driver_corrupt()) is True and reg.latched(FILE_CORPUS)
    assert "check_tables" not in _file_state()
    assert damage.retry_for_collection_start("t") == [FILE_CORPUS]
    assert not reg.latched(FILE_CORPUS)
    assert not [t for t in threading.enumerate() if t.name == "oo-database-recheck"], "a read-error latch started a re-read"


def test_a_replaced_file_releases_its_latch_outright_and_a_late_re_read_answer_is_dropped(damaged, files, monkeypatch):
    path, _bad = damaged
    _latch_by_check(files, path, monkeypatch)
    gate, reached = threading.Event(), threading.Event()
    real = verify.check_table

    def slow(p, t, **kw):
        reached.set()
        assert gate.wait(30)
        return real(p, t, **kw)

    monkeypatch.setattr(verify, "check_table", slow)
    damage.retry_for_collection_start("t")
    assert reached.wait(30)
    try:
        assert damage.registry.retry(reason="replaced", files=(FILE_CORPUS,), file_replaced=True) == [FILE_CORPUS]
        damage.registry.verification_forget(FILE_CORPUS)
        assert not damage.registry.latched(FILE_CORPUS) and "check_tables" not in _file_state()
        # A new finding about the NEW file arrives before the old read ends: the old read's answer is not about it.
        damage.registry._note_verified_damage(FILE_CORPUS, ["notes"], path=path, at="2026-10-06T03:00:00+00:00")
        incidents = _file_state()["incidents"]
    finally:
        gate.set()
    _join_rechecks()
    assert damage.registry.latched(FILE_CORPUS)
    assert _file_state()["check_tables"] == ["notes"], "an answer about the old file changed the new file's set"
    assert _file_state()["incidents"] == incidents, "an answer about the old file was counted against the new one"


def test_the_restore_swap_releases_a_check_found_latch_outright_and_forgets_the_verdict(tmp_path, damaged, files, monkeypatch):
    """The file was REPLACED: the verdict was about a file that no longer is, so nothing is re-read and nothing waits."""
    from src.backup import merge

    path, _bad = damaged
    _latch_by_check(files, path, monkeypatch)
    incoming = tmp_path / "incoming.db"
    _build_store(incoming)
    merge._replace_live_corpus(incoming, path)
    assert not damage.registry.latched(FILE_CORPUS), "the swap left the old file's latch on the new file"
    assert FILE_CORPUS not in damage.registry.state(detail=True)["verification"]
    assert FILE_CORPUS not in _record(tmp_path).get("verification", {})
    assert not [t for t in threading.enumerate() if t.name == "oo-database-recheck"], "the swap started a re-read"


def test_a_start_while_the_start_up_check_still_reads_keeps_the_latch_and_starts_no_read(damaged, files, monkeypatch):
    path, _bad = damaged
    _latch_by_check(files, path, monkeypatch)
    damage.registry.verification_arm("unclean-end")  # a check is armed: it decides
    assert damage.retry_for_collection_start("t") == []
    assert damage.registry.latched(FILE_CORPUS) and "rechecking" not in _file_state()
    assert not [t for t in threading.enumerate() if t.name == "oo-database-recheck"]


def test_a_check_that_is_switched_off_or_a_file_that_is_gone_releases_the_latch_as_a_plain_retry_does(tmp_path, damaged, files, monkeypatch):
    path, _bad = damaged
    _latch_by_check(files, path, monkeypatch)
    monkeypatch.setenv("OO_BOOT_VERIFY", "0")
    assert damage.retry_for_collection_start("t") == [FILE_CORPUS]
    assert not damage.registry.latched(FILE_CORPUS) and "rechecking" not in _file_state()
    monkeypatch.delenv("OO_BOOT_VERIFY")

    _new_process(tmp_path, monkeypatch)
    _latch_by_check(files, path, monkeypatch)
    path.unlink()
    assert damage.retry_for_collection_start("t") == [FILE_CORPUS], "a file that is not there cannot be read, and holds nothing"
    assert not path.exists(), "the re-read created the file it was asked to read"


def test_a_re_read_that_cannot_start_a_thread_keeps_the_latch_and_the_claim_is_given_up(damaged, files, monkeypatch):
    path, _bad = damaged
    _latch_by_check(files, path, monkeypatch)

    class NoThread:
        def __init__(self, *a, **kw):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(verify.threading, "Thread", NoThread)
    assert damage.retry_for_collection_start("t") == []
    assert damage.registry.latched(FILE_CORPUS), "no read was made, and the latch was released"
    assert "rechecking" not in _file_state(), "the claim on the file was never given up, so no later start can read it"


def test_a_stop_ends_the_re_read_with_no_answer_and_the_latch_stays(damaged, files, monkeypatch):
    path, _bad = damaged
    _latch_by_check(files, path, monkeypatch)
    _heal(path)
    verify._CANCEL.set()
    damage.retry_for_collection_start("t")
    _join_rechecks()
    assert damage.registry.latched(FILE_CORPUS), "a stopped read released the latch"
    assert "rechecking" not in _file_state()


def test_a_failure_in_the_re_read_gives_no_answer_and_the_latch_stays(damaged, files, monkeypatch):
    path, _bad = damaged
    _latch_by_check(files, path, monkeypatch)

    def boom(*a, **kw):
        raise RuntimeError("read failed")

    monkeypatch.setattr(verify, "check_table", boom)
    damage.retry_for_collection_start("t")
    _join_rechecks()
    assert damage.registry.latched(FILE_CORPUS) and "rechecking" not in _file_state()


def test_a_table_that_is_no_longer_in_the_file_has_nothing_in_it_to_be_damaged(tmp_path, files, healthy, monkeypatch):
    files[FILE_CORPUS] = healthy
    damage.registry._note_verified_damage(FILE_CORPUS, ["dropped_table"], path=healthy, at="2026-10-06T02:00:00+00:00")
    assert damage.registry.latched(FILE_CORPUS)
    damage.retry_for_collection_start("t")
    _join_rechecks()
    assert not damage.registry.latched(FILE_CORPUS)


def _reads_every_table(monkeypatch):
    seen: list[str] = []
    real = verify.check_table
    monkeypatch.setattr(verify, "check_table", lambda p, t, **kw: (seen.append(t), real(p, t, **kw))[1])
    return seen


def test_a_schema_the_check_could_not_read_is_released_only_beside_every_table_reading_clean(tmp_path, files, healthy, monkeypatch):
    """The deep delta read's S3: a ``(schema)`` the check could not read means it read NO table; the list reading now
    answers the schema, not the tables, so every table of the list is read and the schema is clean only beside them."""
    files[FILE_CORPUS] = healthy
    damage.registry._note_verified_damage(FILE_CORPUS, [verify.SCHEMA_ENTRY], path=healthy, at="2026-10-06T02:00:00+00:00")
    seen = _reads_every_table(monkeypatch)
    damage.retry_for_collection_start("t")
    _join_rechecks()
    assert sorted(seen) == ["articles", "notes"], seen
    assert not damage.registry.latched(FILE_CORPUS)


def test_a_schema_that_now_lists_is_not_a_clean_file_when_a_table_beside_it_is_damaged(tmp_path, damaged, files, monkeypatch):
    path, _bad = damaged
    files[FILE_CORPUS] = path
    damage.registry._note_verified_damage(FILE_CORPUS, [verify.SCHEMA_ENTRY], path=path, at="2026-10-06T02:00:00+00:00")
    damage.retry_for_collection_start("t")
    _join_rechecks()
    assert damage.registry.latched(FILE_CORPUS), "the list reading released a file whose tables were never read"
    assert _file_state()["check_tables"] == ["articles"], "the schema left the set, and the table that reads damaged joined it"


def test_a_schema_that_is_damaged_when_the_start_re_reads_it_is_recorded_and_the_latch_holds(tmp_path, damaged, files, monkeypatch):
    path, _bad = damaged
    _latch_by_check(files, path, monkeypatch)
    before = _file_state()["incidents"]
    monkeypatch.setattr(verify, "inspect_file", lambda p, **kw: {"error": (VERDICT_DAMAGED, "database disk image is malformed")})
    damage.retry_for_collection_start("t")
    _join_rechecks()
    assert damage.registry.latched(FILE_CORPUS) and "(schema)" in _file_state()["check_tables"]
    assert _file_state()["incidents"] == before + 1
    entry = damage.registry.state(detail=True)["verification"][FILE_CORPUS]
    assert _by_table(entry)[verify.SCHEMA_ENTRY]["verdict"] == VERDICT_DAMAGED and "articles" in _by_table(entry), (
        "a table the first list lacked was dropped from the record instead of being added"
    )


def test_a_table_that_could_not_be_read_stays_in_the_set_beside_one_that_reads_damaged(tmp_path, damaged, files, monkeypatch):
    """The set is a union across answers: replacing it with the tables that read damaged forgot the one that was only
    unread, and a later clean read of the first released a table nothing had ever read clean."""
    path, _bad = damaged
    _latch_by_check(files, path, monkeypatch)
    damage.registry._note_verified_damage(FILE_CORPUS, ["articles", "notes"], path=path, at="2026-10-06T02:00:00+00:00")

    def answer(p, t, **kw):
        return {"table": t, "verdict": VERDICT_DAMAGED if t == "articles" else VERDICT_UNCHECKED, "seconds": 0.0, "detail": ["x"]}

    monkeypatch.setattr(verify, "check_table", answer)
    damage.retry_for_collection_start("t")
    _join_rechecks()
    assert _file_state()["check_tables"] == ["articles", "notes"], _file_state()["check_tables"]
    monkeypatch.setattr(
        verify, "check_table", lambda p, t, **kw: {"table": t, "verdict": VERDICT_OK if t == "articles" else VERDICT_UNCHECKED, "seconds": 0.0}
    )
    damage.retry_for_collection_start("t")
    _join_rechecks()
    assert damage.registry.latched(FILE_CORPUS), "a table that was never read clean was released with the one that was"


def test_a_failed_read_that_lands_while_the_re_read_runs_is_not_answered_by_its_clean_result(tmp_path, damaged, files, monkeypatch):
    """The deep delta read's S1: the re-read answers about the tables the check reported, and says nothing about a read that
    failed after it began; the latch holds, stops being the check's, and the next start releases it the E1 way."""
    path, _bad = damaged
    _latch_by_check(files, path, monkeypatch)
    _heal(path)
    gate, reached = threading.Event(), threading.Event()
    real = verify.check_table

    def slow(p, t, **kw):
        reached.set()
        assert gate.wait(30)
        return real(p, t, **kw)

    monkeypatch.setattr(verify, "check_table", slow)
    damage.retry_for_collection_start("first")
    assert reached.wait(30)
    before = _file_state()["incidents"]
    try:
        damage.registry.note(FILE_CORPUS, _driver_corrupt())  # a page view failed after the operator's start
        assert _file_state()["incidents"] == before + 1
    finally:
        gate.set()
    _join_rechecks()
    assert damage.registry.latched(FILE_CORPUS), "a clean re-read released a file that failed a read after it began"
    assert "check_tables" not in _file_state() and "rechecking" not in _file_state()
    monkeypatch.setattr(verify, "check_table", real)
    assert damage.retry_for_collection_start("second") == [FILE_CORPUS], "the E1 latch was not released by the next start"
    assert not damage.registry.latched(FILE_CORPUS)


def test_a_re_read_settles_only_the_claim_it_was_started_under(tmp_path, damaged, files, monkeypatch):
    """The deep delta read's N1: every method that settles a claim presents its token, so the first read's ending (it
    waits on the record before its ``finally``) cannot give back a second claim, and a third start cannot read the file at
    the same time."""
    path, _bad = damaged
    _latch_by_check(files, path, monkeypatch)
    reg = damage.registry
    gate, reached = threading.Event(), threading.Event()
    real = verify.check_table

    def slow(p, t, **kw):
        reached.set()
        assert gate.wait(30)
        return real(p, t, **kw)

    monkeypatch.setattr(verify, "check_table", slow)
    damage.retry_for_collection_start("t")
    assert reached.wait(30)
    try:
        token = _file_state()["rechecking"]["token"]
        other = token + 100  # a read that was started under a claim that is long gone
        reg.recheck_abandoned(FILE_CORPUS, other)
        reg.recheck_progress(FILE_CORPUS, 99, other)
        reg.recheck_total(FILE_CORPUS, 99, other)
        assert reg.recheck_finished(FILE_CORPUS, [{"table": "articles", "verdict": VERDICT_OK}], path=path, token=other) is False
        st = _file_state()["rechecking"]
        assert st["token"] == token and st["index"] != 99 and st["total"] != 99, st
        assert reg.latched(FILE_CORPUS) and _file_state()["check_tables"] == ["articles"]
    finally:
        gate.set()
    _join_rechecks()
    assert "rechecking" not in _file_state()


def test_a_start_that_lands_between_the_latch_and_its_table_set_re_reads_instead_of_releasing(tmp_path, damaged, files, monkeypatch):
    """The deep delta read's S2: the set that governs the latch's release is stored in the SAME lock block as the latch,
    so a start that lands right after the latch (the operator clicks the airplane button while the check runs) finds
    a check's latch and re-reads it, instead of finding an E1 latch with no set and releasing it unread."""
    path, _bad = damaged
    files[FILE_CORPUS] = path
    reg = damage.registry
    real = reg._apply_incident
    seen: list = []

    def wrapped(*a, **kw):
        out = real(*a, **kw)
        if not seen:  # the re-read's own answer comes through here too
            seen.append(reg.retry(reason="a start in the gap", files=(FILE_CORPUS,)))
        return out

    monkeypatch.setattr(reg, "_apply_incident", wrapped)
    reg._note_verified_damage(FILE_CORPUS, ["articles"], path=path, at="2026-10-06T02:00:00+00:00")
    _join_rechecks()
    assert seen == [[]], seen
    assert reg.latched(FILE_CORPUS), "a start in the gap released a latch the check had just set, unread"
    assert _file_state()["check_tables"] == ["articles"]


def test_the_wikipedia_lane_start_re_reads_its_own_file_and_a_collection_start_leaves_it_alone(tmp_path, damaged, files, monkeypatch):
    path, _bad = damaged
    _latch_by_check(files, path, monkeypatch, key=FILE_WIKI)
    assert damage.retry_for_collection_start("t") == [] and damage.registry.latched(FILE_WIKI)
    assert "rechecking" not in _file_state(FILE_WIKI), "collection's start re-read the Wikipedia lane's file"
    _heal(path)
    assert damage.registry.retry(reason="the Wikipedia lane was started", files=("wiki",)) == []
    _join_rechecks()
    assert not damage.registry.latched(FILE_WIKI)


# --------------------------------------------------------------------------- #
#  the deep delta read's fold: what an earlier check found is never given up by a read that could not answer
# --------------------------------------------------------------------------- #
def _answers(monkeypatch, verdicts: dict[str, str], default: str = VERDICT_OK) -> None:
    """Every table read answers ``verdicts[table]`` (else ``default``): a read that could not happen is not a clean one."""
    monkeypatch.setattr(
        verify,
        "check_table",
        lambda p, t, **kw: {"table": t, "verdict": verdicts.get(t, default), "seconds": 0.0, "detail": ["fake"]},
    )


def _earlier_check_found(tmp_path, files, damaged, monkeypatch):
    """Process one: the start-up check reads ``articles`` as damaged. Returns the file's path."""
    path, _bad = damaged
    _latch_by_check(files, path, monkeypatch)
    return path


def test_a_schema_read_leaves_every_table_that_does_not_answer_clean_not_only_the_damaged_ones(tmp_path, files, healthy, monkeypatch):
    """The check could not list the tables, so it read none; the read that now lists them answers for ALL of them. A table
    that answers ``unchecked`` (a busy file, no memory) is not a clean read, and the old count (damaged ones only) released
    the latch with nothing planning the file again."""
    files[FILE_CORPUS] = healthy
    damage.registry._note_verified_damage(FILE_CORPUS, [verify.SCHEMA_ENTRY], path=healthy, at="2026-10-06T02:00:00+00:00")
    _answers(monkeypatch, {"notes": VERDICT_UNCHECKED})
    damage.retry_for_collection_start("t")
    _join_rechecks()
    assert damage.registry.latched(FILE_CORPUS), "a table that did not answer released a file nothing had read"
    assert _file_state()["check_tables"] == ["notes"], _file_state()
    _answers(monkeypatch, {})  # the next start reads both clean
    damage.retry_for_collection_start("t")
    _join_rechecks()
    assert not damage.registry.latched(FILE_CORPUS)


def test_a_restart_whose_check_could_not_read_the_reported_table_keeps_the_file_latched_and_the_finding(tmp_path, files, damaged, monkeypatch):
    """An answer of ``unchecked`` is no clean read: the earlier process measured damage in ``articles``, and a later process
    that could not read it (busy file, memory) must not turn that into a file collection writes to."""
    path = _earlier_check_found(tmp_path, files, damaged, monkeypatch)
    _new_process(tmp_path, monkeypatch)
    monkeypatch.setattr(damage, "_previous_end", lambda: CLEAN)
    _answers(monkeypatch, {}, default=VERDICT_UNCHECKED)
    assert verify.arm_at_boot() is True and verify.run_armed() is True
    assert damage.registry.latched(FILE_CORPUS), "a check that could not read the table released what an earlier one found"
    assert sg.StorageGuard().admit() == "damage"
    entry = damage.registry.state(detail=True)["verification"][FILE_CORPUS]
    assert entry["state"] == "done" and entry["verdict"] == VERDICT_UNCHECKED and entry["earlier_damaged"] == ["articles"], entry
    assert _record(tmp_path)["verification"][FILE_CORPUS]["earlier_damaged"] == ["articles"], "the carry is not in the record"
    # and the next process still reads it again, until it reads clean
    _new_process(tmp_path, monkeypatch)
    monkeypatch.setattr(damage, "_previous_end", lambda: CLEAN)
    assert verify.arm_at_boot() is True and verify._PLAN["trigger"] == verify.TRIGGER_DAMAGE_FOUND
    _answers(monkeypatch, {})
    assert verify.run_armed() is True
    assert not damage.registry.latched(FILE_CORPUS)
    assert "earlier_damaged" not in damage.registry.state(detail=True)["verification"][FILE_CORPUS], "a clean read did not clear the carry"
    _new_process(tmp_path, monkeypatch)
    monkeypatch.setattr(damage, "_previous_end", lambda: CLEAN)
    assert verify.arm_at_boot() is False and path.is_file()


def test_a_restart_whose_table_list_could_not_be_read_clears_nothing_an_earlier_check_found(tmp_path, files, damaged, monkeypatch):
    """When the list itself cannot be read no table was read, so there is no table to clear: the answer carries the finding."""
    _earlier_check_found(tmp_path, files, damaged, monkeypatch)
    _new_process(tmp_path, monkeypatch)
    monkeypatch.setattr(damage, "_previous_end", lambda: CLEAN)
    monkeypatch.setattr(verify, "inspect_file", lambda p, **kw: {"error": (VERDICT_UNCHECKED, "the file is busy")})
    assert verify.arm_at_boot() is True and verify.run_armed() is True
    assert damage.registry.latched(FILE_CORPUS)
    entry = damage.registry.state(detail=True)["verification"][FILE_CORPUS]
    assert entry["earlier_damaged"] == ["articles"] and entry["listed"] is False, entry


def test_a_table_the_file_no_longer_has_is_not_carried_and_a_table_that_reads_damaged_is_reported_once(tmp_path, files, damaged, monkeypatch):
    _earlier_check_found(tmp_path, files, damaged, monkeypatch)
    _new_process(tmp_path, monkeypatch)
    monkeypatch.setattr(damage, "_previous_end", lambda: CLEAN)
    assert damage.DamageRegistry._carry_after({"articles", "gone"}, [{"table": "notes", "verdict": VERDICT_OK}], listed=True, damaged=set()) == [], (
        "a table that is no longer in the file was carried: nothing in it can be damaged"
    )
    assert damage.DamageRegistry._carry_after(
        {"articles"}, [{"table": "articles", "verdict": VERDICT_DAMAGED}], listed=True, damaged={"articles"}
    ) == [], "a table this check reports as damaged itself is carried as well: it would be named twice"
    assert damage.DamageRegistry._carry_after(
        {"articles", "gone"}, [{"table": "articles", "verdict": VERDICT_UNCHECKED}], listed=True, damaged=set()
    ) == ["articles"]
    assert damage.DamageRegistry._carry_after({"articles"}, [], listed=False, damaged=set()) == ["articles"]
    assert damage.DamageRegistry._carry_after(
        {verify.SCHEMA_ENTRY}, [{"table": "a", "verdict": VERDICT_UNCHECKED}, {"table": "b", "verdict": VERDICT_OK}], listed=True, damaged=set()
    ) == ["a"], "a schema in the set means every table that does not answer clean is left"


def test_carried_damage_reads_what_a_finished_check_read_and_what_a_later_entry_carried():
    assert damage.carried_damage(None) is None and damage.carried_damage({}) is None
    done = {"state": "done", "verdict": VERDICT_DAMAGED, "tables": [{"table": "b", "verdict": VERDICT_DAMAGED}, {"table": "a", "verdict": VERDICT_OK}]}
    assert damage.carried_damage(done) == ["b"]
    assert damage.carried_damage({"state": "done", "verdict": VERDICT_DAMAGED, "tables": []}) == [verify.SCHEMA_ENTRY], (
        "a damaged record with no table to name must still be a finding"
    )
    assert damage.carried_damage({"state": "done", "verdict": VERDICT_OK, "tables": []}) is None
    assert damage.carried_damage({"state": "owed", "earlier_damaged": ["x", "a"]}) == ["a", "x"]
    assert damage.carried_damage({"state": "running", "earlier_damaged": ["x"]}) == ["x"]


def test_every_entry_that_replaces_a_finding_carries_it_until_a_read_clears_it(tmp_path, files, damaged, monkeypatch):
    path = _earlier_check_found(tmp_path, files, damaged, monkeypatch)
    for step in ("owed", "started", "skipped"):
        _new_process(tmp_path, monkeypatch)
        reg = damage.registry
        if step == "owed":
            reg.verification_file_owed(FILE_CORPUS, path=path, trigger=verify.TRIGGER_DAMAGE_FOUND, attempts=0)
        elif step == "started":
            reg.verification_file_started(FILE_CORPUS, path=path, trigger=verify.TRIGGER_DAMAGE_FOUND, tables_total=2, attempts=1)
        else:
            reg.verification_file_skipped(FILE_CORPUS, path=path, attempts=MAX_VERIFY_ATTEMPTS, reason="r")
        entry = _record(tmp_path)["verification"][FILE_CORPUS]
        assert entry["state"] == {"owed": "owed", "started": "running", "skipped": "skipped"}[step]
        assert entry["earlier_damaged"] == ["articles"], f"the {step} entry forgot what the earlier check found"


def test_a_locked_boot_that_follows_a_damaged_verdict_keeps_it_and_the_unlock_reads_the_file_again(tmp_path, files, damaged, monkeypatch):
    path = _earlier_check_found(tmp_path, files, damaged, monkeypatch)
    _new_process(tmp_path, monkeypatch)
    files[FILE_CORPUS] = path
    monkeypatch.setattr(damage, "_previous_end", lambda: CLEAN)
    verify.owe_at_locked_boot()  # the lock screen: nothing is read, the owed record replaces the verdict
    owed = _record(tmp_path)["verification"][FILE_CORPUS]
    assert owed["state"] == "owed" and owed["earlier_damaged"] == ["articles"], owed
    assert verify.arm_at_boot() is True, "the unlock forgot the earlier finding"
    assert verify._PLAN["trigger"] == verify.TRIGGER_DAMAGE_FOUND, "its own owed entry made the finding read as an unfinished check"
    assert verify._PLAN["files"][0][2] == 0
    assert verify.run_armed() is True and damage.registry.latched(FILE_CORPUS)


def test_a_locked_boot_closed_from_the_lock_screen_twice_still_carries_the_finding(tmp_path, files, damaged, monkeypatch):
    _earlier_check_found(tmp_path, files, damaged, monkeypatch)
    for _ in range(2):
        _new_process(tmp_path, monkeypatch)
        monkeypatch.setattr(damage, "_previous_end", lambda: CLEAN)
        verify.owe_at_locked_boot()
        assert _record(tmp_path)["verification"][FILE_CORPUS]["earlier_damaged"] == ["articles"]


def _held_by_the_cap(tmp_path, healthy, files, monkeypatch, *, tables=("articles",), key=FILE_CORPUS, attempts=MAX_VERIFY_ATTEMPTS):
    """Process N: an earlier check reported ``tables`` and every start since ended before a check finished."""
    files[key] = healthy
    (tmp_path / "database-damage.json").write_text(
        json.dumps(
            {
                "schema": damage.SCHEMA,
                "files": {},
                "incidents": [],
                "verification": {
                    key: {
                        "file": key,
                        "process": "another-process",
                        "state": "running",
                        "attempts": attempts,
                        "earlier_damaged": list(tables),
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    _new_process(tmp_path, monkeypatch)
    monkeypatch.setattr(damage, "_previous_end", lambda: CLEAN)


def test_the_attempt_cap_stops_re_running_the_check_and_never_clears_what_it_found(tmp_path, healthy, files, monkeypatch):
    """R120/R121: a check that cannot finish is not run again, and a file an earlier check found damaged stays paused: the
    cap protects against a boot loop, it is not a way to start collecting into a file known to be damaged."""
    _held_by_the_cap(tmp_path, healthy, files, monkeypatch)
    plan = verify.plan_boot(previous_end=CLEAN)
    assert plan["files"] == [] and plan["skipped"][0]["tables"] == ["articles"]
    assert verify.arm_at_boot() is False, "nothing is run, so there is nothing to wait for"
    assert damage.registry.latched(FILE_CORPUS), "the cap released a finding"
    assert sg.StorageGuard().admit() == "damage"
    entry = damage.registry.state(detail=True)["verification"][FILE_CORPUS]
    assert entry["state"] == "skipped" and entry["earlier_damaged"] == ["articles"]
    assert _file_state()["check_tables"] == ["articles"] and _file_state()["incidents"] == 1
    assert _file_state()["scope"] == damage.SCOPE_DATA, "a finding in a data table was scoped as the search index"
    assert any(n["frame"] == damage.FRAME_DATA for n in damage.registry.notes()), damage.registry.notes()
    stopped = [n for n in damage.registry.notes() if n["frame"] == damage.FRAME_CHECK_STOPPED]
    assert [n["vars"] for n in stopped] == [{"tries": MAX_VERIFY_ATTEMPTS}], damage.registry.notes()
    # a start of collection reads the reported table again; clean releases the latch and the note with it
    damage.retry_for_collection_start("t")
    _join_rechecks()
    assert not damage.registry.latched(FILE_CORPUS)
    assert not [n for n in damage.registry.notes() if n["frame"] == damage.FRAME_CHECK_STOPPED], "the note outlived the latch"
    assert "earlier_damaged" not in damage.registry.state(detail=True)["verification"][FILE_CORPUS]


def test_the_cap_note_goes_when_the_file_is_replaced_and_never_reaches_the_record(tmp_path, healthy, files, monkeypatch):
    _held_by_the_cap(tmp_path, healthy, files, monkeypatch)
    verify.arm_at_boot()
    assert "check_stopped_after" not in json.dumps(_record(tmp_path)), "an in-memory note was written into the record"
    assert any(n["frame"] == damage.FRAME_CHECK_STOPPED for n in damage.registry.notes())
    assert damage.registry.retry(reason="the file was replaced", files=(FILE_CORPUS,), file_replaced=True) == [FILE_CORPUS]
    assert not any(n["frame"] == damage.FRAME_CHECK_STOPPED for n in damage.registry.notes()), "the note outlived the file it was about"


def test_a_file_that_cannot_be_examined_is_unchecked_and_an_earlier_finding_stands(tmp_path, files, damaged, monkeypatch):
    """An I/O error from ``stat`` is not "no file": it is a file nothing could read, and what an earlier check found about it
    is held (and said); with no earlier finding there is nothing to hold and nothing is planned."""
    path = _earlier_check_found(tmp_path, files, damaged, monkeypatch)

    class Unexaminable(type(Path())):
        def is_file(self, **kw):
            raise OSError(5, "Input/output error")

    _new_process(tmp_path, monkeypatch)
    monkeypatch.setattr(damage, "_previous_end", lambda: CLEAN)
    files[FILE_CORPUS] = Unexaminable(path)
    plan = verify.plan_boot(previous_end=CLEAN)
    assert plan is not None and plan["files"] == [] and plan["skipped"][0]["tables"] == ["articles"]
    assert "I/O error" in plan["skipped"][0]["reason"]
    assert verify.arm_at_boot() is False
    assert damage.registry.latched(FILE_CORPUS), "a file that could not be examined was released"


def test_a_file_that_cannot_be_examined_and_has_no_earlier_finding_plans_no_check(tmp_path, files, healthy, monkeypatch):
    """Nothing can be run on a file nothing can read: no check is planned. A check that was DUE (an unclean end) is written
    down as owed instead, and with nothing due nothing is planned or recorded at all."""

    class Unexaminable(type(Path())):
        def is_file(self, **kw):
            raise OSError(5, "Input/output error")

    files[FILE_CORPUS] = Unexaminable(healthy)
    plan = verify.plan_boot(previous_end=UNCLEAN)
    assert plan["files"] == [] and [s["owe"] for s in plan["skipped"]] == [verify.TRIGGER_UNCLEAN_END]
    assert verify.plan_boot(previous_end=CLEAN) is None


def test_a_re_read_of_a_file_that_cannot_be_examined_keeps_the_latch_instead_of_releasing_it(tmp_path, files, damaged, monkeypatch):
    """``nothing-to-read`` releases a latch (a switched-off check, a file that is gone); an I/O error says neither."""
    path = _earlier_check_found(tmp_path, files, damaged, monkeypatch)

    class Unexaminable(type(Path())):
        def is_file(self, **kw):
            raise OSError(5, "Input/output error")

    files[FILE_CORPUS] = Unexaminable(path)
    assert verify.recheck({FILE_CORPUS: ["articles"]}, reason="t", claims={FILE_CORPUS: 1}) == {FILE_CORPUS: "kept"}
    assert damage.retry_for_collection_start("t") == []
    assert damage.registry.latched(FILE_CORPUS) and "rechecking" not in _file_state()


def test_a_call_that_names_no_claim_settles_no_claim(tmp_path, damaged, files, monkeypatch):
    path, _bad = damaged
    _latch_by_check(files, path, monkeypatch)
    reg = damage.registry
    gate, reached = threading.Event(), threading.Event()
    real = verify.check_table

    def slow(p, t, **kw):
        reached.set()
        assert gate.wait(30)
        return real(p, t, **kw)

    monkeypatch.setattr(verify, "check_table", slow)
    damage.retry_for_collection_start("t")
    assert reached.wait(30)
    try:
        token = _file_state()["rechecking"]["token"]
        reg.recheck_abandoned(FILE_CORPUS)
        reg.recheck_progress(FILE_CORPUS, 99)
        reg.recheck_total(FILE_CORPUS, 99)
        assert reg.recheck_finished(FILE_CORPUS, [{"table": "articles", "verdict": VERDICT_OK}], path=path) is False
        st = _file_state()["rechecking"]
        assert st["token"] == token and st["index"] != 99 and st["total"] != 99, "a call with no token touched a claim"
        assert reg.latched(FILE_CORPUS) and _file_state()["check_tables"] == ["articles"]
    finally:
        gate.set()
    _join_rechecks()


def test_the_check_opens_every_file_mode_ro_and_leaves_a_leftover_write_ahead_log_as_it_found_it(tmp_path, monkeypatch):
    """``query_only`` does not make a connection harmless: the last connection to close a file with a leftover ``-wal`` folds
    the log into it and deletes it. A check that only reads must not be what does that (the log may be all that is left of
    the last minutes of writes)."""
    src = tmp_path / "live" / "corpus.db"
    src.parent.mkdir()
    con = sqlite3.connect(src)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA wal_autocheckpoint=0")
    con.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.executemany("INSERT INTO notes (body) VALUES (?)", [(f"n{i}",) for i in range(50)])
    con.commit()
    dead = tmp_path / "dead"
    dead.mkdir()
    for suffix in ("", "-wal"):  # the files as a process that was killed leaves them (no -shm, no one holding)
        (dead / f"corpus.db{suffix}").write_bytes((src.parent / f"corpus.db{suffix}").read_bytes())
    con.close()
    path = dead / "corpus.db"
    before = (path.read_bytes(), (dead / "corpus.db-wal").read_bytes())
    assert before[1], "the fixture left no write-ahead log"
    seen: list[dict] = []
    from src.database import connect as connect_mod

    real = connect_mod.connect
    monkeypatch.setattr(connect_mod, "connect", lambda *a, **kw: (seen.append(kw), real(*a, **kw))[1])
    out = verify.check_table(path, "notes")
    assert out["verdict"] == VERDICT_OK, out
    assert seen and all(kw.get("read_only") is True for kw in seen), seen
    assert (dead / "corpus.db-wal").exists(), "the check deleted the leftover write-ahead log"
    assert (path.read_bytes(), (dead / "corpus.db-wal").read_bytes()) == before, "the check changed the file or its log"


def test_a_re_read_that_leaves_a_table_unread_carries_it_in_the_record_so_the_next_start_reads_it_again(tmp_path, files, damaged, monkeypatch):
    """The merged record of a re-read says ``unchecked`` for a table that answered nothing: without the carry the record reads
    as a file with nothing reported, and the next process forgets the finding the first one measured."""
    path = _earlier_check_found(tmp_path, files, damaged, monkeypatch)
    damage.registry._note_verified_damage(FILE_CORPUS, ["articles", "notes"], path=path, at="2026-10-06T02:00:00+00:00")
    _answers(monkeypatch, {"articles": VERDICT_UNCHECKED})  # notes reads clean, articles could not be read
    damage.retry_for_collection_start("t")
    _join_rechecks()
    assert damage.registry.latched(FILE_CORPUS) and _file_state()["check_tables"] == ["articles"]
    entry = damage.registry.state(detail=True)["verification"][FILE_CORPUS]
    assert entry["earlier_damaged"] == ["articles"], entry
    damage.registry._flush_latest()
    assert _record(tmp_path)["verification"][FILE_CORPUS]["earlier_damaged"] == ["articles"]
    _new_process(tmp_path, monkeypatch)
    monkeypatch.setattr(damage, "_previous_end", lambda: CLEAN)
    plan = verify.plan_boot(previous_end=CLEAN)
    assert plan is not None and [f[0] for f in plan["files"]] == [FILE_CORPUS], "the next process forgot what was never read clean"


def _stopped_notes():
    return [n for n in damage.registry.notes() if n["frame"] == damage.FRAME_CHECK_STOPPED]


def test_the_cap_note_is_in_memory_only_and_a_later_latch_of_the_same_file_does_not_inherit_it(tmp_path, healthy, files, monkeypatch):
    """The note says a check STOPPED; it is about one latch. A latch that comes later (a clean read released the first, a
    replaced file ended it) must not be told the check was stopped, and the note never reaches the record."""
    _held_by_the_cap(tmp_path, healthy, files, monkeypatch)
    verify.arm_at_boot()
    assert len(_stopped_notes()) == 1
    damage.registry._flush_latest()
    assert "check_stopped_after" not in json.dumps(_record(tmp_path)), "an in-memory note was written into the record"
    # a clean re-read releases it
    damage.retry_for_collection_start("t")
    _join_rechecks()
    assert not damage.registry.latched(FILE_CORPUS)
    damage.registry._note_verified_damage(FILE_CORPUS, ["articles"], path=healthy, at="2026-10-06T03:00:00+00:00")
    assert damage.registry.latched(FILE_CORPUS) and not _stopped_notes(), "a later latch inherited the note of the one a clean read released"


def test_a_replaced_file_ends_the_cap_note_for_a_later_latch_too(tmp_path, healthy, files, monkeypatch):
    _held_by_the_cap(tmp_path, healthy, files, monkeypatch)
    verify.arm_at_boot()
    assert len(_stopped_notes()) == 1
    assert damage.registry.retry(reason="the file was replaced", files=(FILE_CORPUS,), file_replaced=True) == [FILE_CORPUS]
    damage.registry._note_verified_damage(FILE_CORPUS, ["articles"], path=healthy, at="2026-10-06T03:00:00+00:00")
    assert damage.registry.latched(FILE_CORPUS) and not _stopped_notes(), "a latch on the new file inherited the old file's note"


# --------------------------------------------------------------------------- #
#  the coordinator's check of the fold (F1, F2, F4, F6, F7, F8)
# --------------------------------------------------------------------------- #
def _restart(tmp_path, monkeypatch, end):
    """A new process over the same record, whose previous session ended as ``end`` says."""
    reg = _new_process(tmp_path, monkeypatch)
    monkeypatch.setattr(damage, "_previous_end", lambda: end)
    return reg


def test_a_file_held_at_the_cap_stays_held_at_every_clean_start_and_a_new_unclean_end_starts_the_count_again(
    tmp_path, healthy, files, monkeypatch
):
    """F1: the hold writes a ``skipped`` entry, which the next start used to read as "no attempts", so the check ran three
    more times (a crashing check: 3 runs, 1 held start, 3 runs, ...). The cap protects against a boot loop, so a hold lasts until
    something new asks for a check."""
    _held_by_the_cap(tmp_path, healthy, files, monkeypatch)
    assert verify.arm_at_boot() is False  # the first held start
    for _ in range(3):  # and the clean starts after it
        _restart(tmp_path, monkeypatch, CLEAN)
        plan = verify.plan_boot(previous_end=CLEAN)
        assert plan["files"] == [], "a held file was planned again at a clean start"
        assert [s["tables"] for s in plan["skipped"]] == [["articles"]]
        assert plan["skipped"][0]["attempts"] == MAX_VERIFY_ATTEMPTS
        assert verify.arm_at_boot() is False and not damage.registry.verifying()
        assert damage.registry.latched(FILE_CORPUS), "the hold released the file"
        assert len(_stopped_notes()) == 1, "the note was not shown again"
        entry = damage.registry.state(detail=True)["verification"][FILE_CORPUS]
        assert entry["state"] == "skipped" and entry["attempts"] == MAX_VERIFY_ATTEMPTS and entry["earlier_damaged"] == ["articles"]
    # a new unexpected stop is a new reason to check: the count starts again
    _restart(tmp_path, monkeypatch, UNCLEAN)
    plan = verify.plan_boot(previous_end=UNCLEAN)
    assert plan["files"] == [(FILE_CORPUS, healthy, 0)] and plan["skipped"] == []


def test_a_held_file_whose_finding_was_cleared_is_not_held_any_more(tmp_path, healthy, files, monkeypatch):
    _held_by_the_cap(tmp_path, healthy, files, monkeypatch)
    verify.arm_at_boot()
    damage.retry_for_collection_start("t")  # the reported table reads clean (the file is healthy)
    _join_rechecks()
    assert not damage.registry.latched(FILE_CORPUS)
    _restart(tmp_path, monkeypatch, CLEAN)
    assert verify.plan_boot(previous_end=CLEAN) is None, "a held entry with no finding left kept the file planned"


def test_the_stopped_note_does_not_say_collection_re_reads_a_file_it_never_re_reads():
    """F2: the Wikipedia file is released by its lane's own start, so the note must not promise a re-read at "starting
    collection"; the damage sentence above it says how to try again."""
    assert "Starting collection" not in damage.FRAME_CHECK_STOPPED
    assert "reads clean again" in damage.FRAME_CHECK_STOPPED and "the note above" in damage.FRAME_CHECK_STOPPED
    base = json.loads((ROOT / "src/static/locales/en.json").read_text(encoding="utf-8"))
    assert damage.FRAME_CHECK_STOPPED in base


@pytest.mark.parametrize("key", [FILE_WIKI, FILE_LAW])
def test_the_lane_files_are_held_at_the_cap_say_so_and_are_released_the_way_their_lane_releases_them(
    tmp_path, healthy, files, monkeypatch, key
):
    """F4: the cap hold, the note and the re-read for the Wikipedia and law files (the corpus was the only file tested)."""
    _held_by_the_cap(tmp_path, healthy, files, monkeypatch, key=key)
    assert verify.plan_boot(previous_end=CLEAN)["skipped"][0]["file"] == key
    assert verify.arm_at_boot() is False
    assert damage.registry.latched(key), "the cap released a lane file"
    assert _file_state(key)["check_tables"] == ["articles"]
    own_frame = damage.FRAME_WIKI if key == FILE_WIKI else damage.FRAME_LAW
    notes = damage.registry.notes()
    assert any(n["file"] == key and n["frame"] == own_frame for n in notes), notes
    assert [n["vars"] for n in notes if n["file"] == key and n["frame"] == damage.FRAME_CHECK_STOPPED] == [{"tries": MAX_VERIFY_ATTEMPTS}]
    damage.retry_for_collection_start("t")
    _join_rechecks()
    if key == FILE_WIKI:
        assert damage.registry.latched(key), "a start of collection released the Wikipedia file, which has its own start"
        assert len([n for n in damage.registry.notes() if n["frame"] == damage.FRAME_CHECK_STOPPED]) == 1
        damage.registry.retry(reason="the Wikipedia lane was started", files=(FILE_WIKI,))  # the lane's own start re-reads
        _join_rechecks()
    assert not damage.registry.latched(key), "the reported table read clean and the lane file stayed paused"
    assert not [n for n in damage.registry.notes() if n["file"] == key and n["frame"] == damage.FRAME_CHECK_STOPPED]


def test_a_shadow_table_only_finding_is_scoped_as_the_search_index_even_when_it_is_only_carried(tmp_path, healthy, files, monkeypatch):
    """F4: the scope is decided over every table the latch names, carried ones included (a carried finding alone has no
    tables of its own, and ``all([])`` is true)."""
    _held_by_the_cap(tmp_path, healthy, files, monkeypatch, tables=("article_fts_data",))
    verify.arm_at_boot()
    assert _file_state()["scope"] == damage.SCOPE_SEARCH_INDEX
    assert any(n["frame"] == damage.FRAME_SEARCH_INDEX for n in damage.registry.notes())
    _held_by_the_cap(tmp_path, healthy, files, monkeypatch, tables=("article_fts_data", "articles"))
    verify.arm_at_boot()
    assert _file_state()["scope"] == damage.SCOPE_DATA, "a data table beside a shadow table was scoped as the index only"


def test_the_note_needs_the_cap_itself_an_unexaminable_file_under_it_is_held_without_one(tmp_path, files, healthy, monkeypatch):
    """F4: the hold carries the attempts it found; a note says "after N starts" only when the cap was the reason."""

    class Unexaminable(type(Path())):
        def is_file(self, **kw):
            raise OSError(5, "Input/output error")

    for attempts, expect_note in ((MAX_VERIFY_ATTEMPTS - 1, False), (MAX_VERIFY_ATTEMPTS, True)):
        _held_by_the_cap(tmp_path, healthy, files, monkeypatch, attempts=attempts)
        files[FILE_CORPUS] = Unexaminable(healthy)
        assert verify.plan_boot(previous_end=CLEAN)["skipped"][0]["attempts"] == attempts
        assert verify.arm_at_boot() is False
        assert damage.registry.latched(FILE_CORPUS), "a file that could not be examined was released"
        assert bool(_stopped_notes()) is expect_note, (attempts, damage.registry.notes())


def test_the_stopped_note_is_not_said_when_the_pause_is_switched_off(tmp_path, healthy, files, monkeypatch):
    _held_by_the_cap(tmp_path, healthy, files, monkeypatch)
    verify.arm_at_boot()
    assert len(_stopped_notes()) == 1
    monkeypatch.setenv("OO_DAMAGE_GUARD", "0")
    notes = damage.registry.notes()
    assert not _stopped_notes() and any(n["frame"] == damage.FRAME_PAUSE_OFF for n in notes), notes


def test_the_stopped_note_is_set_in_the_latchs_own_block_so_a_release_in_between_cannot_leave_it_behind(
    tmp_path, healthy, files, monkeypatch
):
    """F7: a second lock block after the latch let a retry land between them, leaving the note on an unlatched file for the
    next latch to inherit."""
    reg = _new_process(tmp_path, monkeypatch)
    real = reg._apply_incident

    def latch_then_release(*a, **kw):
        out = real(*a, **kw)
        reg.retry(reason="the file was replaced", files=(FILE_CORPUS,), file_replaced=True)  # lands right after the latch
        return out

    monkeypatch.setattr(reg, "_apply_incident", latch_then_release)
    reg.verification_file_held(FILE_CORPUS, path=healthy, attempts=MAX_VERIFY_ATTEMPTS, reason="r", tables=["articles"])
    monkeypatch.setattr(reg, "_apply_incident", real)
    assert not reg.latched(FILE_CORPUS) and "check_stopped_after" not in _file_state()
    reg._note_verified_damage(FILE_CORPUS, ["articles"], path=healthy, at="2026-10-06T03:00:00+00:00")
    assert reg.latched(FILE_CORPUS) and not _stopped_notes(), "a later latch inherited a sentence about a check it never saw"
    # and with no release the note is there, beside the latch it belongs to
    reg._reset_for_tests()
    reg.verification_file_held(FILE_CORPUS, path=healthy, attempts=MAX_VERIFY_ATTEMPTS, reason="r", tables=["articles"])
    assert reg.latched(FILE_CORPUS) and len(_stopped_notes()) == 1
    reg.verification_file_held(FILE_CORPUS, path=healthy, attempts=1, reason="r", tables=["articles"])
    assert len(_stopped_notes()) == 1, "a hold below the cap took the note away"


def test_a_file_released_because_it_is_gone_loses_the_stopped_note_and_a_later_latch_does_not_inherit_it(
    tmp_path, healthy, files, monkeypatch
):
    _held_by_the_cap(tmp_path, healthy, files, monkeypatch)
    verify.arm_at_boot()
    assert len(_stopped_notes()) == 1
    healthy.unlink()  # nothing to read: a start releases the latch as a plain retry does
    assert damage.retry_for_collection_start("t") == [FILE_CORPUS]
    assert not damage.registry.latched(FILE_CORPUS) and not _stopped_notes()
    damage.registry._note_verified_damage(FILE_CORPUS, ["articles"], path=healthy, at="2026-10-06T03:00:00+00:00")
    assert damage.registry.latched(FILE_CORPUS) and not _stopped_notes(), "a later latch inherited the note of the one that was released"


def test_a_held_file_whose_re_read_was_overtaken_by_a_failed_read_keeps_its_latch_and_loses_the_stopped_note(
    tmp_path, healthy, files, monkeypatch
):
    """F4: the reported part read clean, so "the pause ends only when it reads clean" is no longer what holds the file; a failed
    read of the app's own is, and the next start releases that latch the E1 way."""
    _held_by_the_cap(tmp_path, healthy, files, monkeypatch)
    verify.arm_at_boot()
    assert len(_stopped_notes()) == 1
    gate, reached = threading.Event(), threading.Event()
    real = verify.check_table

    def slow(p, t, **kw):
        reached.set()
        assert gate.wait(30)
        return real(p, t, **kw)

    monkeypatch.setattr(verify, "check_table", slow)
    damage.retry_for_collection_start("first")
    assert reached.wait(30)
    try:
        damage.registry.note(FILE_CORPUS, _driver_corrupt())
    finally:
        gate.set()
    _join_rechecks()
    assert damage.registry.latched(FILE_CORPUS), "a clean re-read released a file that failed a read after it began"
    assert not _stopped_notes(), "the note kept saying the pause waits for the reported part"


def test_an_unexaminable_file_whose_check_was_due_keeps_it_owed_and_one_that_was_not_due_records_nothing(
    tmp_path, files, healthy, monkeypatch
):
    """F6: an I/O error from ``stat`` on a file with no earlier finding recorded nothing, so after an unexpected stop the
    owed check was forgotten once the session ended clean."""

    class Unexaminable(type(Path())):
        def is_file(self, **kw):
            raise OSError(5, "Input/output error")

    files[FILE_CORPUS] = Unexaminable(healthy)
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    assert verify.arm_at_boot() is False and not damage.registry.verifying()
    owed = damage.registry.state(detail=True)["verification"][FILE_CORPUS]
    assert owed["state"] == "owed" and owed["trigger"] == verify.TRIGGER_UNCLEAN_END and owed["attempts"] == 0, owed
    assert not damage.registry.latched(FILE_CORPUS), "nothing was found, so nothing is latched"
    assert _record(tmp_path)["verification"][FILE_CORPUS]["state"] == "owed"
    # the next session ends clean and can examine the file: the check that was due is still due
    _restart(tmp_path, monkeypatch, CLEAN)
    files[FILE_CORPUS] = healthy
    plan = verify.plan_boot(previous_end=CLEAN)
    assert plan["trigger"] == verify.TRIGGER_UNFINISHED and plan["files"] == [(FILE_CORPUS, healthy, 0)]
    # a clean end with nothing due writes nothing about a file that cannot be examined
    other = tmp_path / "other"
    other.mkdir()
    _new_process(other, monkeypatch)
    files[FILE_CORPUS] = Unexaminable(healthy)
    monkeypatch.setattr(damage, "_previous_end", lambda: CLEAN)
    assert verify.arm_at_boot() is False
    assert FILE_CORPUS not in damage.registry.state(detail=True)["verification"]


def test_an_unexaminable_file_whose_earlier_check_was_left_unfinished_keeps_that_checks_reason_and_its_attempts(
    tmp_path, healthy, files, monkeypatch
):
    """F6, the mutation run's two gaps: a CLEAN end after a check that was left running, on a file that cannot be examined now,
    owes the check for the reason it had and with the attempts it had used, not as a fresh unexpected stop with none spent (that
    would give a check that keeps dying its three tries again at every start the file cannot be read)."""

    class Unexaminable(type(Path())):
        def is_file(self, **kw):
            raise OSError(5, "Input/output error")

    (tmp_path / "database-damage.json").write_text(
        json.dumps(
            {
                "schema": damage.SCHEMA,
                "files": {},
                "incidents": [],
                "verification": {
                    FILE_CORPUS: {
                        "file": FILE_CORPUS, "process": "another-process", "state": "running", "attempts": 2,
                        "trigger": verify.TRIGGER_DAMAGE_FOUND,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    files[FILE_CORPUS] = Unexaminable(healthy)
    _new_process(tmp_path, monkeypatch)
    monkeypatch.setattr(damage, "_previous_end", lambda: CLEAN)
    assert verify.arm_at_boot() is False and not damage.registry.verifying()
    owed = damage.registry.state(detail=True)["verification"][FILE_CORPUS]
    assert owed["state"] == "owed" and owed["trigger"] == verify.TRIGGER_DAMAGE_FOUND and owed["attempts"] == 2, owed


def test_the_virtual_table_check_tests_run_in_ci():
    """F8: the tests that need SQLite's own FTS5 integrity check (3.44) skip silently on an older library, and a skip is how a
    check that never ran looks green. CI must have a library that runs them."""
    if os.getenv("CI"):
        assert sqlite3.sqlite_version_info >= (3, 44), (
            f"CI's SQLite is {sqlite3.sqlite_version}: the full-text index's integrity check tests are skipped on it"
        )
