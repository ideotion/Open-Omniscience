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
        "wrote": wrote, "refused": refused,
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


@pytest.mark.parametrize("leg", _LEGS)
def test_after_an_interrupted_run_the_app_refuses_and_the_resume_finishes(tmp_path, leg):
    out = _run(tmp_path, leg, "interrupt")
    assert out["migration"] == ["interrupted"], out
    assert out["wrote"] is None and out["refused"] == "MigrationUnfinished", out
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
        assert "held by another program" in text and "migrate-countries" in text, text
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
        assert "held by another program" not in str(caught.value)
    finally:
        kv_store.kv_invalidate()
