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
    assert plan and plan["trigger"] == verify.TRIGGER_UNFINISHED and plan["files"][0][2] == 1


def test_the_shutdown_stops_the_check():
    src = _main_source()
    shutdown = src[src.index("# Stop the scheduler thread cleanly if it is running"):]
    assert "_verify.stop()" in shutdown.split("dispose_engine()")[0], "a quit mid-check must ask the check to end"


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
    from tests.test_database_damage import _engaged_guard  # noqa: PLC0415 - the one engaged-guard builder

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


def _main_source() -> str:
    return (ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")


def test_the_startup_arms_before_the_thread_exists_and_withdraws_when_it_cannot_start():
    """Anchored to the source (a test that reads ``app.routes`` or boots the app is flaky; this is the order)."""
    src = _main_source()
    arm = src.index("verify.arm_at_boot()")
    start = src.index('name="oo-boot-sequence"')
    disarm = src.index("verify.disarm()")
    assert arm < start < disarm, "the check must be armed before the sequence thread starts, and withdrawn if it cannot"
    block = src[src.rindex('if os.getenv("OO_NO_SCHEDULER", "0") != "1":', 0, arm) : arm]
    assert "threading" in block, "the arming sits in the scheduler-enabled block (tests and headless runs skip it)"


def test_the_module_names_no_write_statement():
    """The module never names a write statement: reading is the whole of what it does."""
    src = (ROOT / "src" / "database" / "verify.py").read_text(encoding="utf-8")
    code = re.sub(r'"""(?:.|\n)*?"""', "", src)
    for word in ("INSERT", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "VACUUM", "REINDEX", "journal_mode", "wal_checkpoint"):
        assert word not in code, f"verify.py names {word!r}"
    assert "query_only=ON" in code


def test_every_check_string_is_in_the_twelve_locales_translated():
    keys = [damage.FRAME_VERIFYING, sg.FRAME_OVERRIDE_VERIFYING, "Paused: checking the data files after an unexpected stop"]
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
