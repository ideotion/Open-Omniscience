"""A damaged page met by ONE section of the debug bundle must not turn every section after it into ``PendingRollbackError``.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

MEASURED, on a real SQLCipher store (``tests/test_poisoned_connection.py`` is the reference for the driver's side): the
read of a page that fails its check poisons the connection, the damage observer (``src/database/damage.py``) invalidates
that ONE connection, and the session that was reading keeps a transaction on a connection that is gone: EVERY later
statement of that session raises ``PendingRollbackError`` until the session is rolled back. The debug bundle runs ten
database sections one after the other on ONE shared snapshot session, so a section that caught its own error and went on
(or one that raised, and was recorded as an ``{error}``) would hand the dead transaction to the next, and the report would
say nothing about the healthy tables: the place the operator needs it to look.

What is pinned, each against a way the bundle could mislead:

  * on a REAL encrypted store the canary holds (the session IS dead until it is rolled back), and the helper
    brings it back to a read that is answered;
  * the helper rolls back ONLY a session whose connection was invalidated: a healthy session keeps its snapshot (a rollback
    ends the read transaction and the next statement is a snapshot of a LATER moment), a session with no transaction is left
    alone, and nothing it is handed can make it raise;
  * through the endpoint: a section that invalidates the connection and RAISES, and one that invalidates it and RETURNS,
    both leave the sections after them answered. Two of those sections (``storage_composition``, ``keyword_write_cost``) catch
    their own errors and report themselves unavailable with the engine's words as the reason, with no ``error`` key, so a test
    that only looks for ``error`` passes the bundle that lost them: the sections must read, and none may carry the dead
    transaction's words anywhere.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import PendingRollbackError
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from src.api.diagnostics.bundle import _roll_back_a_failed_read

_KEY = "damaged read test key"
_PAGE = 16384
_BAD_RANGE = "SELECT id, v FROM big WHERE id BETWEEN :lo AND :hi"


def _plain_session(tmp_path: Path) -> Session:
    eng = create_engine(f"sqlite:///{tmp_path / 'plain.db'}", poolclass=QueuePool, pool_size=2, max_overflow=0)
    with eng.begin() as c:
        c.execute(text("CREATE TABLE small (a INTEGER)"))
        c.execute(text("INSERT INTO small VALUES (1), (2), (3)"))
    return Session(eng)


# --------------------------------------------------------------------------- #
#  the helper
# --------------------------------------------------------------------------- #
def test_a_session_on_an_invalidated_connection_is_rolled_back_and_reads_again(tmp_path):
    db = _plain_session(tmp_path)
    try:
        assert db.execute(text("SELECT count(*) FROM small")).scalar_one() == 3
        db.connection().invalidate()  # what the damage observer does to the connection a damaged read poisoned
        with pytest.raises(PendingRollbackError):
            db.execute(text("SELECT count(*) FROM small"))
        assert _roll_back_a_failed_read(db) is True
        assert db.execute(text("SELECT count(*) FROM small")).scalar_one() == 3
        assert _roll_back_a_failed_read(db) is False, "the new transaction is healthy: nothing more to roll back"
    finally:
        db.close()
        db.get_bind().dispose()


def test_a_healthy_session_keeps_the_snapshot_it_has(tmp_path):
    """A rollback ends the read transaction, and the next statement opens a snapshot of a LATER moment: a section that failed
    for another reason (a Python error, a statement deadline) must leave the snapshot every later section reads."""
    db = _plain_session(tmp_path)
    writer = create_engine(f"sqlite:///{tmp_path / 'plain.db'}")
    try:
        assert db.execute(text("SELECT count(*) FROM small")).scalar_one() == 3
        with writer.begin() as c:
            c.execute(text("INSERT INTO small VALUES (4)"))
        assert _roll_back_a_failed_read(db) is False
        assert db.in_transaction(), "the healthy session's transaction was ended"
    finally:
        db.close()
        db.get_bind().dispose()
        writer.dispose()


def test_a_session_with_no_transaction_and_a_missing_session_are_left_alone(tmp_path):
    db = _plain_session(tmp_path)
    try:
        assert db.in_transaction() is False
        assert _roll_back_a_failed_read(db) is False
        assert _roll_back_a_failed_read(None) is False
    finally:
        db.close()
        db.get_bind().dispose()


def test_a_session_that_cannot_even_be_asked_about_its_connection_is_rolled_back_and_nothing_raises():
    class Odd:
        def in_transaction(self):
            return True

        def connection(self):
            raise RuntimeError("no connection to ask")

        rolled = 0

        def rollback(self):
            Odd.rolled += 1

    assert _roll_back_a_failed_read(Odd()) is True and Odd.rolled == 1

    class Broken(Odd):
        def rollback(self):
            raise RuntimeError("cannot roll back")

    assert _roll_back_a_failed_read(Broken()) is False, "a recovery that fails never costs the bundle its evidence"

    class Hostile:
        def in_transaction(self):
            raise RuntimeError("no")

    assert _roll_back_a_failed_read(Hostile()) is False


# --------------------------------------------------------------------------- #
#  a REAL damaged page of an encrypted store
# --------------------------------------------------------------------------- #
def _build_damaged_store(path: Path) -> None:
    pytest.importorskip("sqlcipher3")
    from src.database.connect import connect

    con = connect(path, key=_KEY, create_encrypted=True, check_same_thread=False)
    con.execute("CREATE TABLE small (a INTEGER)")
    con.execute("INSERT INTO small VALUES (1), (2), (3)")
    con.commit()
    con.execute("CREATE TABLE big (id INTEGER PRIMARY KEY, v BLOB)")
    rng = random.Random(4)
    con.executemany("INSERT INTO big (v) VALUES (?)", [(rng.randbytes(3000),) for _ in range(900)])
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    bad = (path.stat().st_size // _PAGE) // 2 + 3  # well inside ``big``; the small table sits at the start of the file
    with open(path, "r+b") as f:
        f.seek((bad - 1) * _PAGE)
        f.write(random.Random(bad).randbytes(_PAGE))


def test_a_real_damaged_page_leaves_the_session_dead_until_the_helper_rolls_it_back(tmp_path):
    pytest.importorskip("sqlcipher3")
    from src.database import damage
    from src.database.connect import connect
    from src.database.damage import FILE_CORPUS

    path = tmp_path / "corpus.db"
    _build_damaged_store(path)
    damage.registry._reset_for_tests(path_fn=lambda: tmp_path / "database-damage.json")
    eng = create_engine(
        "sqlite://",
        creator=lambda: connect(path, key=_KEY, check_same_thread=False),
        poolclass=QueuePool,
        pool_size=2,
        max_overflow=0,
    )
    damage.attach(eng, FILE_CORPUS)
    db = Session(eng)
    try:
        assert db.execute(text("SELECT count(*) FROM small")).scalar_one() == 3
        met = None
        for lo in range(1, 901, 100):
            try:
                db.execute(text(_BAD_RANGE), {"lo": lo, "hi": lo + 99}).fetchall()
            except Exception as exc:  # noqa: BLE001 - the section that catches its own error and goes on
                met = exc
                assert damage.is_corruption(exc), exc
                break
        assert met is not None, "no range of the wide table failed: the overwrite missed it"
        # the canary: the session is dead for the NEXT section, healthy tables included
        with pytest.raises(PendingRollbackError):
            db.execute(text("SELECT count(*) FROM small"))
        assert _roll_back_a_failed_read(db) is True
        assert db.execute(text("SELECT count(*) FROM small")).scalar_one() == 3, "the healthy table reads on a connection of its own"
    finally:
        db.close()
        eng.dispose()


# --------------------------------------------------------------------------- #
#  through the endpoint
# --------------------------------------------------------------------------- #
@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.monitoring.errorlog import install

    install()
    with TestClient(app) as c:
        yield c


def _bundle(client) -> dict:
    r = client.get("/api/diagnostics/debug-bundle")
    assert r.status_code == 200
    return r.json()["data"]


_DEAD = ("PendingRollbackError", "rolled back", "rollback() fully")


def _no_dead_transaction(data: dict) -> None:
    """No section tells the dead transaction, whether as an ``error`` or in the ``reason`` of a section that catches its own
    error and reports itself unavailable (``storage_composition`` and ``keyword_write_cost`` do, which is why the check reads the
    whole of each section and not only its ``error``)."""
    for name, section in data.items():
        blob = json.dumps(section, default=str)
        for word in _DEAD:
            assert word not in blob, (name, word)


@pytest.mark.parametrize("how", ["raises", "returns"])
def test_a_section_that_kills_its_connection_leaves_the_later_sections_answered(client, monkeypatch, how):
    import src.monitoring.integrity as integrity

    seen: dict = {}

    def kills_its_connection(db, *args, **kwargs):
        db.connection().invalidate()  # the observer's work on the connection a damaged read poisoned
        seen["killed"] = True
        if how == "raises":
            raise RuntimeError("database disk image is malformed")
        return {"caught_its_own_error": True}

    monkeypatch.setattr(integrity, "corpus_integrity", kills_its_connection)
    data = _bundle(client)
    assert seen.get("killed"), "the section was not run: the bundle no longer reads corpus_integrity from this module"
    _no_dead_transaction(data)
    # the sections after it READ (a healthy install's answer, not a section that went unavailable)
    assert data["storage_composition"].get("available") is True, data["storage_composition"]
    assert data["keyword_write_cost"].get("available") is True, data["keyword_write_cost"]
    assert data["corpus"] and "error" not in data["corpus"], data["corpus"]
    if how == "raises":
        assert "malformed" in data["corpus_integrity"]["error"]
    else:
        assert data["corpus_integrity"] == {"caught_its_own_error": True}
