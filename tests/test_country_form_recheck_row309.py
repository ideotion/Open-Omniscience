"""Row 309 (R788): a running app whose pool was empty while the country migration ran does not write the old form after it.

The migration takes the file only while no connection is open on it, so an app process that is alive with an EMPTY pool
(after a restore, repair, rebuild, unlock or panic disposed it) does not stop it. Measured on main before this row: that
process kept its cached "alpha-2, no journal", its next write put ``de`` beside ``FRA`` under an alpha-3 marker (a resume
then refused: "says alpha-3 but still holds alpha-2 values"), and after an interrupted run its write changed a row count so
the resume could never finish, leaving only the safety copy. A new physical connection now re-reads both rows through
itself (``country_form.recheck_on_new_connection``). Each case runs in a process of its own because the engine is bound to
the data folder when ``src.database.session`` is imported; the key reaches it through the environment, never argv.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from src.database import connect as connect_mod

ROOT = Path(__file__).resolve().parents[1]
_TEST_KEY = "row309-throwaway-test-key"  # a scratch store's own key, handed over by environment only
_LEGS = [
    pytest.param("plain", id="plaintext"),
    pytest.param(
        "enc",
        id="encrypted",
        marks=pytest.mark.skipif(not connect_mod.have_driver(), reason="sqlcipher3 not installed"),
    ),
]

# The app process: boots on a pre-0.5 store (no marker = alpha-2), writes once so its cache holds the form, empties its
# pool and stays alive; a migration runs in another process; then the app writes again. Prints one JSON line.
_APP = textwrap.dedent(
    """
    import json, os, sqlite3, subprocess, sys
    key = os.environ.get("ROW309_KEY")
    from src.database import connect as C
    if key:
        C.set_passphrase(key)
    from src.database.session import DB_FILE, SessionLocal, dispose_engine, engine, init_db
    from src.database.models import Base, Source
    from src.database.country_form import KEY, JOURNAL_KEY, store_form
    Base.metadata.create_all(engine)  # the tables, and no marker: a store from before 0.5
    with engine.begin() as c:
        c.exec_driver_sql("DELETE FROM app_state WHERE key = ?", (KEY,))
    init_db()
    with SessionLocal() as s:
        s.add(Source(name="a", domain="a.example", rss_url="http://a.example/rss", country="fr"))
        s.commit()
    before = store_form()
    dispose_engine()  # the pool holds nothing now; the process lives on
    child = (
        "import os, sys\\n"
        "from pathlib import Path\\n"
        "from src.database import connect as C\\n"
        "k = os.environ.get('ROW309_KEY')\\n"
        "C.set_passphrase(k) if k else None\\n"
        "from src.backup import country_migration as cm\\n"
        "stop = (lambda: True) if sys.argv[2] == 'interrupt' else None\\n"
        "r = cm.migrate(Path(sys.argv[1]), backup_dir=Path(sys.argv[1]).parent / 'bk', should_stop=stop)\\n"
        "print(r.state)\\n"
    )
    mig = subprocess.run([sys.executable, "-c", child, DB_FILE, sys.argv[1]], env=os.environ, capture_output=True,
                         text=True, timeout=240)
    wrote = refused = None
    try:
        with SessionLocal() as s:
            s.add(Source(name="b", domain="b.example", rss_url="http://b.example/rss", country="de"))
            s.commit()
        wrote = True
    except Exception as exc:
        refused = type(getattr(exc, "orig", None) or exc).__name__
    dispose_engine()
    # A plain read, through the corpus engine and through the read-snapshot engine: neither asks for the form first.
    reads = {}
    from sqlalchemy import text
    from src.database.read_snapshot import dispose_read_engines, read_snapshot_session
    def _engine_read():
        with engine.connect() as c:
            return c.exec_driver_sql("SELECT count(*) FROM sources").fetchone()[0]
    def _snapshot_read():
        with read_snapshot_session() as s:
            return s.execute(text("SELECT count(*) FROM sources")).scalar()
    for name, run in (("engine", _engine_read), ("snapshot", _snapshot_read)):
        try:
            reads[name] = run()
        except Exception as exc:
            reads[name] = type(getattr(exc, "orig", None) or exc).__name__
    dispose_engine()
    dispose_read_engines()
    resume = subprocess.run([sys.executable, "-c", child, DB_FILE, "resume"], env=os.environ, capture_output=True,
                            text=True, timeout=240)
    con = C.connect(DB_FILE, check_same_thread=False)
    try:
        rows = con.execute("SELECT name, country FROM sources ORDER BY name").fetchall()
        marker = con.execute("SELECT value FROM app_state WHERE key = ?", (KEY,)).fetchone()
        journal = con.execute("SELECT value FROM app_state WHERE key = ?", (JOURNAL_KEY,)).fetchone()
    finally:
        con.close()
    print(json.dumps({
        "encrypted": C.is_encrypted_file(DB_FILE), "before": before,
        "migration": mig.stdout.strip().splitlines()[-1:] or [mig.stderr.strip()[-300:]],
        "wrote": wrote, "refused": refused, "reads": reads,
        "resume": resume.stdout.strip().splitlines()[-1:] or [resume.stderr.strip()[-300:]],
        "rows": rows, "marker": json.loads(marker[0])["form"] if marker else None,
        "journal": json.loads(journal[0]).get("state") if journal else None,
    }))
    """
)


def _run(tmp_path: Path, leg: str, variant: str) -> dict:
    env = {**os.environ, "PYTHONPATH": str(ROOT), "OO_DATA_DIR": str(tmp_path), "OO_NO_SCHEDULER": "1"}
    for name in ("ROW309_KEY", "OO_DB_PASSPHRASE", "DATABASE_URL"):
        env.pop(name, None)
    if leg == "enc":
        env.pop("OO_DB_PLAINTEXT", None)
        env["ROW309_KEY"] = _TEST_KEY
    else:
        env["OO_DB_PLAINTEXT"] = "1"
    done = subprocess.run(
        [sys.executable, "-c", _APP, variant], cwd=ROOT, env=env, capture_output=True, text=True, timeout=600
    )
    assert done.returncode == 0, done.stderr[-2000:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["encrypted"] is (leg == "enc"), out
    assert out["before"] == "alpha2", out
    return out


@pytest.mark.parametrize("leg", _LEGS)
def test_after_a_migration_it_did_not_see_the_app_writes_the_new_form(tmp_path, leg):
    out = _run(tmp_path, leg, "done")
    assert out["migration"] == ["done"], out
    assert out["wrote"] is True, out
    # One form only: the row written after the run is alpha-3 like the one the run converted.
    assert [tuple(r) for r in out["rows"]] == [("a", "FRA"), ("b", "DEU")], out
    assert out["marker"] == "alpha3", out
    assert out["resume"] == ["already-done"], out
    assert out["reads"] == {"engine": 2, "snapshot": 2}, out


@pytest.mark.parametrize("leg", _LEGS)
def test_after_an_interrupted_run_the_app_refuses_and_the_resume_finishes(tmp_path, leg):
    out = _run(tmp_path, leg, "interrupt")
    assert out["migration"] == ["interrupted"], out
    assert out["wrote"] is None and out["refused"] == "MigrationUnfinished", out
    # A read is refused too, on both engines, before it runs: the store holds both forms (R788).
    assert out["reads"] == {"engine": "MigrationUnfinished", "snapshot": "MigrationUnfinished"}, out
    # The resume is not forced onto the safety copy: it finishes, and the store holds one form.
    assert out["resume"] == ["done"], out
    assert [tuple(r) for r in out["rows"]] == [("a", "FRA")], out
    assert out["marker"] == "alpha3" and out["journal"] == "done", out


# The wrong-key run: an encrypted store with a -wal a crash left, and migrate() run under another passphrase.
_WRONG_KEY = textwrap.dedent(
    """
    import json, os, sys
    from pathlib import Path
    from src.database import connect as C
    from src.backup import country_migration as cm
    db = Path(sys.argv[1]); wal = Path(str(db) + "-wal")
    before = wal.stat().st_size
    C.set_passphrase(os.environ["ROW309_WRONG"])
    try:
        cm.migrate(db, backup_dir=db.parent / "bk")
        raised = None
    except Exception as exc:
        raised = type(exc).__name__
    print(json.dumps({"before": before, "after": wal.stat().st_size if wal.exists() else None, "raised": raised}))
    """
)
_CRASH = textwrap.dedent(
    """
    import os, sys
    from src.database.connect import connect
    c = connect(sys.argv[1], key=os.environ["ROW309_KEY"], check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA wal_autocheckpoint=0")
    for i in range(20):
        c.execute("INSERT INTO t VALUES (?)", (100 + i,))
    c.commit()
    os._exit(0)  # no close, no checkpoint: the rows live only in the -wal
    """
)


@pytest.mark.skipif(not connect_mod.have_driver(), reason="sqlcipher3 not installed")
def test_a_wrong_passphrase_changes_no_file_not_even_the_wal(tmp_path):
    db = tmp_path / "s.db"
    con = connect_mod.connect(db, key=_TEST_KEY, create_encrypted=True, check_same_thread=False)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE t(x)")
        con.commit()
    finally:
        con.close()
    env = {**os.environ, "PYTHONPATH": str(ROOT), "ROW309_KEY": _TEST_KEY, "ROW309_WRONG": "row309-not-the-key"}
    for name in ("OO_DB_PLAINTEXT", "OO_DB_PASSPHRASE"):
        env.pop(name, None)
    subprocess.run([sys.executable, "-c", _CRASH, str(db)], cwd=ROOT, env=env, check=True, timeout=120)
    main_bytes = db.read_bytes()
    done = subprocess.run(
        [sys.executable, "-c", _WRONG_KEY, str(db)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=240
    )
    assert done.returncode == 0, done.stderr[-2000:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["raised"] == "WrongPassphraseError", out
    assert out["before"] > 0 and out["after"] == out["before"], f"the refused run folded or removed the -wal: {out}"
    assert db.read_bytes() == main_bytes, "the refused run changed the store file"
    con = connect_mod.connect(db, key=_TEST_KEY, check_same_thread=False)
    try:
        assert con.execute("SELECT count(*) FROM t").fetchone()[0] == 20
    finally:
        con.close()


@pytest.mark.parametrize("held_by", ["locked", "store-held"])
def test_a_start_under_a_held_store_names_the_holder_not_a_damaged_journal(tmp_path, monkeypatch, held_by):
    import sqlite3

    from src.config import kv_store
    from src.database import country_form as cf

    def _held(*_a, **_k):
        if held_by == "locked":
            raise sqlite3.OperationalError("database is locked")
        raise connect_mod.StoreHeldError("in use")

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 's.db'}")
    monkeypatch.setattr(kv_store, "_read_value", _held)
    kv_store.kv_invalidate()
    try:
        with pytest.raises(cf.StoreFormUnreadable) as caught:
            cf.refuse_if_unfinished()
        text = str(caught.value)
        assert "in use by another program" in text and "migrate-countries" in text, text
        assert "could not be read (" not in text, text
    finally:
        kv_store.kv_invalidate()


def test_a_journal_that_fails_otherwise_still_says_it_could_not_be_read(tmp_path, monkeypatch):
    import sqlite3

    from src.config import kv_store
    from src.database import country_form as cf

    def _damaged(*_a, **_k):
        raise sqlite3.DatabaseError("file is not a database")

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 's.db'}")
    monkeypatch.setattr(kv_store, "_read_value", _damaged)
    kv_store.kv_invalidate()
    try:
        with pytest.raises(cf.StoreFormUnreadable) as caught:
            cf.refuse_if_unfinished()
        assert "could not be read (KvReadError)" in str(caught.value)
        assert "in use by another program" not in str(caught.value)
    finally:
        kv_store.kv_invalidate()


def test_a_new_connection_on_an_unfinished_store_is_refused_and_closed(tmp_path):
    """The connect listener itself: a journal that names a cut run refuses the connection and closes it; one that names a
    finished run, or none, lets it through (R788, row 309)."""
    import sqlite3

    from src.config import kv_store
    from src.database import country_form as cf

    db = tmp_path / "s.db"
    con = sqlite3.connect(db)
    try:
        con.execute("CREATE TABLE app_state (key TEXT PRIMARY KEY, value TEXT)")
        con.commit()
        cf.recheck_on_new_connection(con)  # no journal: through
        for state, refused in (("done", False), ("running", True), ("interrupted", True)):
            con.execute(
                "INSERT OR REPLACE INTO app_state VALUES (?, ?)",
                (cf.JOURNAL_KEY, json.dumps({"state": state, "backup": {"path": "/b/copy.db"}})),
            )
            con.commit()
            if not refused:
                cf.recheck_on_new_connection(con)
                continue
            probe = sqlite3.connect(db)
            with pytest.raises(cf.MigrationUnfinished) as caught:
                cf.recheck_on_new_connection(probe)
            assert state in str(caught.value) and "/b/copy.db" in str(caught.value)
            with pytest.raises(sqlite3.ProgrammingError):
                probe.execute("SELECT 1")  # closed
        # A journal row that is there and is not a JSON object: unreadable is not "no run".
        con.execute("INSERT OR REPLACE INTO app_state VALUES (?, ?)", (cf.JOURNAL_KEY, "{not json"))
        con.commit()
        probe = sqlite3.connect(db)
        with pytest.raises(cf.StoreFormUnreadable) as caught:
            cf.recheck_on_new_connection(probe)
        assert not isinstance(caught.value, cf.MigrationUnfinished)
        with pytest.raises(sqlite3.ProgrammingError):
            probe.execute("SELECT 1")
    finally:
        con.close()
        kv_store.kv_invalidate()


def test_rows_that_cannot_be_read_refuse_the_connection_except_on_a_store_with_no_app_state_yet(tmp_path):
    import sqlite3

    from src.config import kv_store
    from src.database import country_form as cf

    fresh = sqlite3.connect(tmp_path / "new.db")
    try:
        cf.recheck_on_new_connection(fresh)  # no app_state table yet: a new file has no run
        fresh.execute("SELECT 1")
    finally:
        fresh.close()

    class _Failing:
        def __init__(self, exc):
            self.exc, self.closed = exc, False

        def cursor(self):
            raise self.exc

        def close(self):
            self.closed = True

    from src.database import damage

    damage.registry._reset_for_tests(path_fn=lambda: tmp_path / "database-damage.json")
    try:
        held = _Failing(sqlite3.OperationalError("database is locked"))
        with pytest.raises(cf.StoreFormUnreadable) as caught:
            cf.recheck_on_new_connection(held)
        assert held.closed and "in use by another program" in str(caught.value)
        other = _Failing(sqlite3.OperationalError("disk I/O error"))
        with pytest.raises(cf.StoreFormUnreadable) as caught:
            cf.recheck_on_new_connection(other)
        assert other.closed and "(OperationalError)" in str(caught.value) and "I/O" not in str(caught.value)
        # A corruption answer is refused AND recorded: a refusal in a connect event never reaches the engine's observer.
        assert not damage.registry.latched(damage.FILE_CORPUS)
        damaged = _Failing(sqlite3.DatabaseError("database disk image is malformed"))
        with pytest.raises(cf.StoreFormUnreadable) as caught:
            cf.recheck_on_new_connection(damaged)
        assert damaged.closed and "damaged" in str(caught.value) and "malformed" not in str(caught.value)
        assert damage.registry.latched(damage.FILE_CORPUS), "the corruption was not recorded"
    finally:
        damage.registry._reset_for_tests()
        kv_store.kv_invalidate()


def test_a_committing_restore_refuses_a_half_migrated_store_read_from_the_file(tmp_path, monkeypatch):
    """The restore merges through raw connections the connect-time refusal never sees, and takes the form from the marker
    alone; it asks the journal itself, before preparing and again at the working copy (R788). It reads the FILE: a cache
    that still says "no journal" from before a run this process did not see does not answer for it."""
    import inspect
    import sqlite3

    from src.backup import merge
    from src.config import kv_store
    from src.database import country_form as cf

    db = tmp_path / "s.db"
    con = sqlite3.connect(db)
    try:
        con.execute("CREATE TABLE app_state (key TEXT PRIMARY KEY, value TEXT)")
        con.commit()
    finally:
        con.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    kv_store.kv_invalidate()
    try:
        merge.refuse_half_migrated_store()  # no journal: a restore goes ahead
        assert kv_store.kv_get_json_checked(cf.JOURNAL_KEY) is None  # cached as "no journal"
        con = sqlite3.connect(db)
        try:
            con.execute(
                "INSERT INTO app_state VALUES (?, ?)",
                (cf.JOURNAL_KEY, json.dumps({"state": "interrupted", "backup": {"path": "/b/copy.db"}})),
            )
            con.commit()
        finally:
            con.close()
        with pytest.raises(merge.HalfMigratedStoreRefused) as caught:
            merge.refuse_half_migrated_store()
        assert isinstance(caught.value, merge.RestoreRefused)
        assert "interrupted" in str(caught.value) and "/b/copy.db" in str(caught.value)
    finally:
        kv_store.kv_invalidate()
    body = inspect.getsource(merge.run_restore)
    assert body.count("refuse_half_migrated_store()") == 2, "asked before preparing and again at the working copy"


def test_a_wrong_key_is_raised_by_the_read_only_check_and_only_read_only_failures_pass_on(tmp_path, monkeypatch):
    """``_check_key_read_only`` passes on only a failure of read-only opening itself (also when an encrypted open reports
    it as ``WrongPassphraseError`` chained from the driver's error); a held store is refused as ``AppStillRunning``; a
    wrong key or a damaged file is raised before any read-write open."""
    import sqlite3

    from src.backup import country_migration as cm

    def _fails(exc):
        def _connect(*_a, **_k):
            raise exc

        return _connect

    def _chained(outer, cause):
        outer.__cause__ = cause
        return outer

    cases = (
        (connect_mod.StoreHeldError("in use"), cm.AppStillRunning),
        (sqlite3.OperationalError("unable to open database file"), None),
        (sqlite3.OperationalError("attempt to write a readonly database"), None),
        (_chained(connect_mod.WrongPassphraseError("no"), sqlite3.OperationalError("attempt to write a readonly database")), None),
        (_chained(connect_mod.WrongPassphraseError("no"), sqlite3.DatabaseError("file is not a database")), connect_mod.WrongPassphraseError),
        (connect_mod.WrongPassphraseError("no"), connect_mod.WrongPassphraseError),
        (sqlite3.DatabaseError("file is not a database"), sqlite3.DatabaseError),
    )
    for exc, raised in cases:
        monkeypatch.setattr(connect_mod, "connect", _fails(exc))
        if raised is None:
            cm._check_key_read_only(tmp_path / "s.db")
        else:
            with pytest.raises(raised):
                cm._check_key_read_only(tmp_path / "s.db")


def test_the_held_message_names_the_wait_and_claims_nothing_about_writes():
    from src.database import country_form as cf

    text = cf.held_message()
    assert "30 seconds" in text and "migrate-countries" in text
    assert "nothing was written" not in text and "second copy of the app" not in text


def test_a_recheck_that_finds_the_cache_right_still_moves_the_key_version(tmp_path, monkeypatch):
    """A read of the key that began before the recheck may have read the file as it was before a migration: it must not
    store it. The key's version moves on every recheck, equal values included, so such a read is never cached; the
    global epoch and other keys are left alone, so a recheck on every new connection costs other reads nothing."""
    from src.config import kv_store

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 's.db'}")
    kv_store.kv_invalidate()
    try:
        path = kv_store._db_path()
        with kv_store._lock:
            kv_store._cache[(path, "k")] = '{"a": 1}'
            kv_store._cache[(path, "other")] = '{"b": 1}'
        epoch, ver = kv_store._epoch, kv_store._wver.get((path, "k"), 0)
        assert kv_store.kv_forget_if_changed("k", '{"a": 1}') is False
        assert kv_store._wver[(path, "k")] > ver and kv_store._epoch == epoch
        assert (path, "k") in kv_store._cache
        assert kv_store.kv_forget_if_changed("k", '{"a": 2}') is True
        assert (path, "k") not in kv_store._cache and (path, "other") in kv_store._cache
    finally:
        kv_store.kv_invalidate()
