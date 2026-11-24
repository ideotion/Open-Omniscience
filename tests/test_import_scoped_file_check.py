"""R827 R7(a) (row 408) with R830's stop rules: an import's INTERMEDIATE checkpoint checks only the tables the
merge wrote, the run's final activation checks the whole file, and an activation that was checked only in part is
recorded until a read-only whole-file check of the live corpus passes.

What these tests pin:
- the write recorder sees row writes per table, counts trigger DDL as the schema, and makes the set unknown for
  table or index DDL (unknown = the whole file is checked);
- ``verify_file`` scopes only when asked AND the set is known, and the scope takes the FK children of a written
  parent (a deleted parent leaves rows dangling in a table nobody wrote);
- the record is written before a scoped swap and cleared by a passing whole-file check; a failed check keeps it
  and names the run's safety net; a check that could not run keeps it and is not a verdict;
- the snapshot pruners never remove the safety net the record names;
- the queue runs the owed check at its end, a Stop included, and never ends a failed or unfinished check as
  "done" or "stopped"; a start with a record runs it once.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def data(tmp_path, monkeypatch):
    import src.backup.merge as merge

    monkeypatch.setattr(merge, "data_dir", lambda: tmp_path)
    return tmp_path


def _schema(path: Path) -> Path:
    con = sqlite3.connect(path)
    con.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE sources (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE articles (id INTEGER PRIMARY KEY, source_id INT REFERENCES sources(id), body TEXT);
        CREATE INDEX ix_articles_source ON articles(source_id);
        CREATE TABLE notes (id INTEGER PRIMARY KEY, txt TEXT);
        INSERT INTO sources (id, name) VALUES (1, 'a'), (2, 'b');
        INSERT INTO articles (source_id, body) VALUES (1, 'x'), (2, 'y');
        """
    )
    con.commit()
    con.close()
    return path


def _open_watched(path: Path):
    from src.database.connect import connect

    return connect(path, check_same_thread=False)


# --------------------------------------------------------------------------- the write recorder


def test_row_writes_are_recorded_per_table_and_reads_are_not(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    from src.database.connect import unwatch_writes, watch_writes, watched_writes

    db = _schema(tmp_path / "w.db")
    assert watched_writes(db) is None  # not watched: unknown, so the whole file is checked
    watch_writes(db)
    try:
        con = _open_watched(db)
        con.execute("SELECT * FROM notes").fetchall()
        con.execute("UPDATE sources SET name = 'c' WHERE id = 1")
        con.execute("INSERT INTO articles (source_id, body) VALUES (1, 'z')")
        con.commit()
        con.close()
        assert watched_writes(db) == {"sources", "articles"}
    finally:
        unwatch_writes(db)
    assert watched_writes(db) is None


def test_trigger_ddl_is_the_schema_and_table_or_index_ddl_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    from src.database.connect import WRITE_SET_UNKNOWN, unwatch_writes, watch_writes, watched_writes

    db = _schema(tmp_path / "w.db")
    watch_writes(db)
    try:
        con = _open_watched(db)
        con.execute("CREATE TRIGGER t_ai AFTER INSERT ON notes BEGIN SELECT 1; END")
        con.commit()
        got = watched_writes(db)
        assert "sqlite_master" in got and WRITE_SET_UNKNOWN not in got
        con.execute("CREATE INDEX ix_notes ON notes(txt)")
        con.commit()
        con.close()
        assert WRITE_SET_UNKNOWN in watched_writes(db)
    finally:
        unwatch_writes(db)


def test_a_connection_to_another_file_records_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    from src.database.connect import unwatch_writes, watch_writes, watched_writes

    a, b = _schema(tmp_path / "a.db"), _schema(tmp_path / "b.db")
    watch_writes(a)
    try:
        con = _open_watched(b)
        con.execute("DELETE FROM notes")
        con.commit()
        con.close()
        assert watched_writes(a) == set()
    finally:
        unwatch_writes(a)


# --------------------------------------------------------------------------- the scoped file check


def test_scoped_check_covers_written_tables_and_fk_children(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    from src.backup.merge import verify_file

    db = _schema(tmp_path / "w.db")
    v = verify_file(db, write_set={"sources"}, full=False)
    assert v["file_check"] == "scoped" and v["file_ok"]
    # sources quick-checked; sources and its FK child articles fk-checked; notes untouched
    assert v["file_check_tables"] == {"quick_check": 1, "foreign_key_check": 2}


def test_a_deleted_parent_is_caught_in_the_child_the_merge_never_wrote(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    from src.backup.merge import verify_file

    db = _schema(tmp_path / "w.db")
    con = sqlite3.connect(db)
    con.execute("DELETE FROM sources WHERE id = 2")  # foreign_keys off here: articles row 2 now dangles
    con.commit()
    con.close()
    v = verify_file(db, write_set={"sources"}, full=False)
    assert v["file_check"] == "scoped"
    assert v["foreign_key_violations"] == 1 and not v["file_ok"]


@pytest.mark.parametrize(
    ("write_set", "full"),
    [({"sources"}, True), (None, False), ({"sources", "*"}, False), ({"gone_table"}, False)],
)
def test_the_whole_file_is_checked_unless_the_scope_is_known_and_asked_for(tmp_path, monkeypatch, write_set, full):
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    from src.backup.merge import verify_file

    v = verify_file(_schema(tmp_path / "w.db"), write_set=write_set, full=full)
    assert v["file_check"] == "full" and v["file_ok"]


# --------------------------------------------------------------------------- the record and the live check


def test_the_record_keeps_the_runs_first_safety_net(data):
    from src.backup.merge import _note_unverified_activation, unverified_activation

    _note_unverified_activation(data / "pre-restore-20261124T100000Z.db")
    _note_unverified_activation(data / "pre-restore-20261124T110000Z.db")
    got = unverified_activation()
    assert Path(got["safety_net"]).name == "pre-restore-20261124T100000Z.db"
    # written through the shared atomic writer under its lock: no temp is left beside it
    assert sorted(p.name for p in data.iterdir() if p.name.startswith("import-unverified-activation") and ".tmp" in p.name) == []
    assert (data / "import-unverified-activation.json").is_file()


def _live(monkeypatch, path: Path):
    import src.backup.sqlite_backup as sb

    monkeypatch.setattr(sb, "live_db_path", lambda: path)


def test_a_passing_live_check_clears_the_record(data, monkeypatch):
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    from src.backup.merge import _note_unverified_activation, check_live_after_scoped_activation, unverified_activation

    _live(monkeypatch, _schema(data / "live.db"))
    assert check_live_after_scoped_activation() == {"state": "none"}
    _note_unverified_activation(data / "pre-restore-20261124T100000Z.db")
    assert check_live_after_scoped_activation() == {"state": "ok"}
    assert unverified_activation() is None


def test_a_failing_live_check_keeps_the_record_and_names_the_net(data, monkeypatch):
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    from src.backup.merge import _note_unverified_activation, check_live_after_scoped_activation, unverified_activation

    live = _schema(data / "live.db")
    con = sqlite3.connect(live)
    con.execute("DELETE FROM sources WHERE id = 2")
    con.commit()
    con.close()
    _live(monkeypatch, live)
    net = data / "pre-restore-20261124T100000Z.db"
    _note_unverified_activation(net)
    got = check_live_after_scoped_activation()
    assert got == {"state": "failed", "safety_net": str(net)}
    assert unverified_activation()["failed_at"]


def test_a_check_that_cannot_open_the_corpus_is_not_a_verdict(data, monkeypatch):
    from src.backup.merge import _note_unverified_activation, check_live_after_scoped_activation, unverified_activation

    _live(monkeypatch, data / "missing" / "live.db")
    _note_unverified_activation(None)
    got = check_live_after_scoped_activation()
    assert got["state"] == "unchecked"
    assert unverified_activation() is not None  # still owed: the next start runs it


def test_the_pruners_keep_the_net_an_owed_check_names(data, monkeypatch):
    import src.backup.merge as merge

    names = [f"pre-restore-2026010{i}T000000Z.db" for i in range(1, 6)]
    for n in names:
        (data / n).write_bytes(b"x")
    merge._note_unverified_activation(data / names[0])
    merge._prune_snapshots(keep=1)
    assert (data / names[0]).exists()
    merge.prune_pre_restore_snapshots_by_age(0)
    assert (data / names[0]).exists()
    assert not (data / names[1]).exists()


# --------------------------------------------------------------------------- the queue


def _queue(tmp_path, monkeypatch, outcome):
    import src.backup.merge as merge
    from src.backup import import_queue

    monkeypatch.setattr(merge, "unverified_activation", lambda: {"safety_net": "/d/pre-restore-x.db"})
    monkeypatch.setattr(merge, "check_live_after_scoped_activation", lambda **_k: dict(outcome))
    return import_queue.ImportQueueManager(state_path=tmp_path / "q.json")


def test_the_queue_end_check_turns_a_stopped_run_into_an_error(tmp_path, monkeypatch):
    mgr = _queue(tmp_path, monkeypatch, {"state": "failed", "safety_net": "/d/pre-restore-x.db"})
    got = mgr._check_owed_corpus()
    assert got == {"state": "failed", "safety_net": "pre-restore-x.db"}  # a file name, never the folder
    assert mgr.status()["corpus_check"] == got
    saved = json.loads((tmp_path / "q.json").read_text(encoding="utf-8"))
    assert saved["corpus_check"] == got


def test_a_start_with_a_record_runs_the_check_once_and_never_says_done(tmp_path, monkeypatch):
    mgr = _queue(tmp_path, monkeypatch, {"state": "unchecked", "reason": "not-finished"})
    mgr._state = "done"
    mgr.check_owed_at_start()
    st = mgr.status()
    assert st["state"] == "error" and st["corpus_check"]["state"] == "unchecked"


def test_nothing_owed_changes_nothing(tmp_path, monkeypatch):
    import src.backup.merge as merge
    from src.backup import import_queue

    monkeypatch.setattr(merge, "unverified_activation", lambda: None)
    mgr = import_queue.ImportQueueManager(state_path=tmp_path / "q.json")
    assert mgr._check_owed_corpus() is None
    assert mgr.status()["corpus_check"] is None


def test_the_run_end_wiring_checks_before_tuning_and_outranks_a_stop():
    from tests.js_source_helper import python_function_source

    src = python_function_source((_ROOT / "src/backup/import_queue.py").read_text(encoding="utf-8"), "_drive")
    assert src.find("self._check_owed_corpus()") < src.find("self._tune_after_run()")
    assert 'self._state = "error" if owed_failed else' in src
    run = python_function_source((_ROOT / "src/backup/merge.py").read_text(encoding="utf-8"), "run_restore")
    assert "_note_unverified_activation(" in run and "_clear_unverified_activation()" in run
    assert run.find("_note_unverified_activation(") < run.find("_carry_and_swap(")
    assert "full=final_activation or not commit" in run


def test_only_an_activation_another_merge_follows_is_intermediate(tmp_path, monkeypatch):
    from src.backup import import_queue

    mgr = import_queue.ImportQueueManager(state_path=tmp_path / "q.json")
    corpus = {"kind": "corpus", "id": "a"}
    monkeypatch.setattr(mgr, "_another_item_will_merge", lambda idx: True)
    assert mgr._is_final_activation(0, corpus, hold=False) is False
    assert mgr._is_final_activation(0, corpus, hold=True) is True  # a held item swaps nothing
    assert mgr._is_final_activation(0, {"kind": "legacy"}, hold=False) is True
    monkeypatch.setattr(mgr, "_another_item_will_merge", lambda idx: False)
    assert mgr._is_final_activation(0, corpus, hold=False) is True

    def _boom(idx):
        raise RuntimeError("unreadable digest")

    monkeypatch.setattr(mgr, "_another_item_will_merge", _boom)
    assert mgr._is_final_activation(0, corpus, hold=False) is True  # doubt buys the whole-file check


# --------------------------------------------------------------------------- Plan 2026-11-24: prove every writer was recorded


def test_an_uninstrumented_second_connection_makes_the_check_whole(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    from src.backup.merge import verify_file
    from src.database.connect import WRITE_SET_UNKNOWN, unwatch_writes, watch_writes, watched_writes

    db = _schema(tmp_path / "w.db")
    watch_writes(db)
    try:
        con = _open_watched(db)
        con.execute("UPDATE sources SET name = 'c' WHERE id = 1")
        con.commit()
        con.close()
        assert watched_writes(db) == {"sources"}
        raw = sqlite3.connect(str(db))  # not through connect(): nothing records what it writes
        raw.execute("DELETE FROM notes")
        raw.commit()
        raw.close()
        got = watched_writes(db)
        assert WRITE_SET_UNKNOWN in got
        assert verify_file(db, write_set=got, full=False)["file_check"] == "full"
    finally:
        unwatch_writes(db)


def test_a_read_only_open_elsewhere_keeps_the_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    from src.database.connect import unwatch_writes, watch_writes, watched_writes

    db = _schema(tmp_path / "w.db")
    watch_writes(db)
    try:
        ro = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        ro.execute("SELECT count(*) FROM notes").fetchone()
        ro.close()
        assert watched_writes(db) == set()
    finally:
        unwatch_writes(db)


def test_another_process_holding_the_file_makes_the_set_unknown(tmp_path, monkeypatch):
    import subprocess
    import sys

    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    from src.database.connect import WRITE_SET_UNKNOWN, _another_process_holds, unwatch_writes, watch_writes, watched_writes

    db = _schema(tmp_path / "w.db")
    con = sqlite3.connect(db)
    con.execute("PRAGMA journal_mode=WAL")
    con.close()
    if _another_process_holds(db) is None:
        pytest.skip("no /proc/locks here: covered by the unknown case below")
    code = (
        "import sqlite3, sys, time\n"
        "c = sqlite3.connect(sys.argv[1]); c.execute('SELECT count(*) FROM notes').fetchone()\n"
        "print('open', flush=True); sys.stdin.readline()\n"
    )
    other = subprocess.Popen([sys.executable, "-c", code, str(db)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert other.stdout.readline().strip() == "open"
        watch_writes(db)
        assert WRITE_SET_UNKNOWN in watched_writes(db)
    finally:
        other.communicate("\n", timeout=30)
        unwatch_writes(db)


def test_a_system_where_holders_cannot_be_told_never_scopes(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    import src.database.connect as c

    db = _schema(tmp_path / "w.db")
    monkeypatch.setattr(c, "_another_process_holds", lambda _p: None)
    c.watch_writes(db)
    try:
        assert c.WRITE_SET_UNKNOWN in c.watched_writes(db)
    finally:
        c.unwatch_writes(db)


def test_the_proc_locks_reader_counts_only_other_processes_on_our_files():
    from src.database.connect import _foreign_lock_in

    raw = (
        "1: POSIX  ADVISORY  READ 100 fd:01:42 128 128\n"
        "2: POSIX  ADVISORY  WRITE 200 fd:01:99 0 EOF\n"
        "3: -> POSIX  ADVISORY  WRITE 300 fd:01:7 0 EOF\n"
        "garbage line\n"
    )
    ours = {(0xFD, 1, 42)}
    assert _foreign_lock_in(raw, ours, me=100) is False  # our own lock
    assert _foreign_lock_in(raw, ours, me=555) is True
    assert _foreign_lock_in(raw, {(0xFD, 1, 7)}, me=555) is True  # a blocked waiter is a holder-to-be
    assert _foreign_lock_in(raw, {(0xFD, 2, 42)}, me=555) is False


def test_only_reviewed_modules_can_open_a_database_through_sqlcipher3():
    """The standard driver's opens are seen by the audit hook; SQLCipher's driver raises no audit event, so a module that
    can open a file through it is a reviewed exception here (none of them opens an import's working copy)."""
    import ast

    reviewed = {
        "src/database/connect.py",  # the factory itself (recorded) and its copy helpers, which never open a working copy
        "src/database/verify.py",  # the start-up check reads the live corpus
        "src/monitoring/machine_record.py",  # an in-memory probe of the driver
        "src/monitoring/merge_diag.py",  # a diagnostic over a copy it makes itself
        "src/backup/lane_merge.py",  # an in-memory read of the compiled page size
    }
    found = set()
    for path in (_ROOT / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = {a.name for a in node.names}
                if node.module == "sqlcipher3.dbapi2" and not (names & {"connect", "Connection", "*"}):
                    continue  # exception classes only
                mods = [node.module]
            if any(m == "sqlcipher3" or m.startswith("sqlcipher3.") for m in mods):
                found.add(path.relative_to(_ROOT).as_posix())
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "attr", getattr(node.func, "id", "")) in ("import_module", "__import__")
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and str(node.args[0].value).startswith("sqlcipher3")
            ):
                found.add(path.relative_to(_ROOT).as_posix())  # an import by name is an import
    assert found <= reviewed, f"a new module can open a database through sqlcipher3 unrecorded: {sorted(found - reviewed)}"


def test_damage_found_by_the_owed_check_latches_the_corpus(data, monkeypatch):
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    import src.backup.merge as merge
    from src.database import damage

    live = _schema(data / "live.db")
    _live(monkeypatch, live)
    merge._note_unverified_activation(data / "pre-restore-20261124T100000Z.db")
    latched = []
    monkeypatch.setattr(merge, "_damaged_tables", lambda _p: ["articles"])
    monkeypatch.setattr(damage.registry, "note_import_check_damage", lambda key, tables, path=None: latched.append((key, tables)))

    class _Con:
        def execute(self, sql):
            class _R:
                def fetchone(self):
                    return ("*** in database main ***",)

                def fetchall(self):
                    return []

            return _R()

        def close(self):
            pass

        def interrupt(self):
            pass

    import src.database.connect as c

    monkeypatch.setattr(c, "connect", lambda *a, **k: _Con())
    assert merge.check_live_after_scoped_activation()["state"] == "failed"
    assert latched == [(damage.FILE_CORPUS, ["articles"])]


def test_rows_that_only_break_a_foreign_key_latch_nothing(data, monkeypatch):
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    import src.backup.merge as merge

    live = _schema(data / "live.db")
    con = sqlite3.connect(live)
    con.execute("DELETE FROM sources WHERE id = 2")
    con.commit()
    con.close()
    _live(monkeypatch, live)
    merge._note_unverified_activation(None)
    monkeypatch.setattr(merge, "_latch_live_damage", lambda _p: pytest.fail("a foreign-key break is not damage to the file"))
    assert merge.check_live_after_scoped_activation()["state"] == "failed"
