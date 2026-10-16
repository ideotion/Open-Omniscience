"""``release_idle_connection`` and the three edges of "the connection the transaction holds" (WAL / disk, 2026-10-16, the independent read of PR 1418).

  * DEAD: after a read of a damaged page the damage observer invalidates the connection under the session's transaction. The session
    cannot run another statement until it is rolled back, and what ran on that connection went with it, so the release must ROLL BACK
    (it first declined, because reading the dead connection's ``info`` raised, and every later reader of the session -- the
    all-diagnostics build's next member -- got ``PendingRollbackError``).
  * NO CONNECTION: a transaction that has not met a connection holds nothing; asking the session for its connection checks one out
    (a physical connect, a key derivation on the encrypted store) only to roll it back.
  * JOINED: a ``Session(bind=connection)`` over a connection that already had a transaction with writes on it took its baseline after
    those writes, and the release found "nothing changed" and rolled them back.

The dead-connection controls need a REAL SQLCipher store with a really damaged page and live in ``tests/test_release_after_damage.py``.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest
import sqlalchemy as sa
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from src.database import session as session_module
from src.database.session import _CONNECTION_BEGAN_AT, release_idle_connection
from tests.test_release_declines_unseen_writes import _NOTE, _bodies, _engine

# --------------------------------------------------------------------------- #
#  no connection yet
# --------------------------------------------------------------------------- #


def _checkouts(engine) -> list[int]:
    seen: list[int] = []

    @event.listens_for(engine, "checkout")
    def _count(dbapi, record, proxy):  # pragma: no cover - event
        seen.append(1)

    return seen


def test_a_transaction_that_has_met_no_connection_is_declined_without_checking_one_out(tmp_path):
    engine = _engine(tmp_path / "corpus.db", explicit_begin=False)
    try:
        factory = sessionmaker(bind=engine, class_=Session, autoflush=False, future=True)
        session = factory()
        try:
            session.begin()  # a transaction, and no statement yet: no connection
            assert session.in_transaction()
            seen = _checkouts(engine)
            assert release_idle_connection(session) is False, "nothing was held, so nothing was handed back"
            assert seen == [], "the release asked the pool for a connection only to roll it back"
            assert engine.pool.checkedout() == 0
        finally:
            session.close()
    finally:
        engine.dispose()


def test_after_the_first_statement_the_same_session_is_released_as_before(tmp_path):
    engine = _engine(tmp_path / "corpus.db", explicit_begin=False)
    try:
        factory = sessionmaker(bind=engine, class_=Session, autoflush=False, future=True)
        session = factory()
        try:
            session.begin()
            assert release_idle_connection(session) is False
            session.execute(sa.select(_NOTE.c.id)).all()
            assert engine.pool.checkedout() == 1
            assert release_idle_connection(session) is True and engine.pool.checkedout() == 0
        finally:
            session.close()
    finally:
        engine.dispose()


# --------------------------------------------------------------------------- #
#  a Session joined to a connection that already has a transaction
# --------------------------------------------------------------------------- #
@pytest.fixture(params=["legacy", "explicit-begin"])
def joined_world(request, tmp_path):
    engine = _engine(tmp_path / "corpus.db", explicit_begin=request.param == "explicit-begin")
    with engine.begin() as conn:
        conn.execute(sa.insert(_NOTE).values(body="seed"))
    yield engine
    engine.dispose()


JOINED_WRITES = {
    "an insert": (lambda c: c.execute(sa.insert(_NOTE).values(body="outer")), ["outer", "seed"], None),
    "an update": (lambda c: c.execute(sa.update(_NOTE).values(body="changed")), ["changed"], None),
    "a schema change": (lambda c: c.exec_driver_sql("CREATE TABLE joined_extra (id INTEGER)"), ["seed"], "joined_extra"),
    # The one shape SQLAlchemy's statement events do not see, so only the COUNT taken at the connection's own beginning can decline it.
    "the DBAPI cursor": (lambda c: c.connection.cursor().execute("INSERT INTO note (body) VALUES ('outer')"), ["outer", "seed"], None),
}


@pytest.mark.parametrize("shape", sorted(JOINED_WRITES))
def test_writes_made_on_the_connection_before_the_session_joined_it_are_declined_and_survive(joined_world, shape):
    engine = joined_world
    write, expected, table = JOINED_WRITES[shape]
    with engine.connect() as conn:
        outer = conn.begin()
        write(conn)
        session = Session(bind=conn, autoflush=False, future=True)
        try:
            session.execute(sa.select(_NOTE.c.id)).all()  # the Session begins here, AFTER the writes
            assert not (session.new or session.dirty or session.deleted)
            assert release_idle_connection(session) is False, "a write made before the session joined was released"
        finally:
            session.close()
        outer.commit()
    assert _bodies(engine) == expected
    if table:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT name FROM sqlite_master WHERE name = :n"), {"n": table}).scalar() == table, "the schema change was rolled back"


def test_a_session_joined_to_a_connection_with_no_writes_on_it_is_released(joined_world):
    """The control the declines above need: the baseline is the connection's, and with nothing written the release still returns the read."""
    engine = joined_world
    with engine.connect() as conn:
        outer = conn.begin()
        conn.execute(sa.select(_NOTE.c.id)).all()
        session = Session(bind=conn, autoflush=False, future=True)
        try:
            session.execute(sa.select(_NOTE.c.id)).all()
            assert release_idle_connection(session) is True
        finally:
            session.close()
        if outer.is_active:
            outer.rollback()


def test_the_connection_records_its_count_when_its_transaction_begins_and_forgets_the_last_flag(tmp_path):
    engine = _engine(tmp_path / "corpus.db", explicit_begin=False)
    try:
        with engine.connect() as conn:
            conn.execute(sa.insert(_NOTE).values(body="a"))
            conn.exec_driver_sql("CREATE TABLE flagged (id INTEGER)")
            assert conn.info.get(session_module._NON_READ_STATEMENT) is True
            conn.commit()
            first = conn.info[_CONNECTION_BEGAN_AT]
            conn.execute(sa.select(_NOTE.c.id)).all()  # a new transaction on the same pooled connection
            assert conn.info[_CONNECTION_BEGAN_AT] >= first + 1, "the new transaction did not take a new count"
            assert not conn.info.get(session_module._NON_READ_STATEMENT), "the last transaction's flag outlived it"
    finally:
        engine.dispose()


def test_a_savepoint_is_not_a_connection_transaction_so_it_moves_neither_the_count_nor_the_flag(tmp_path):
    engine = _engine(tmp_path / "corpus.db", explicit_begin=False)
    try:
        with engine.connect() as conn:
            conn.execute(sa.insert(_NOTE).values(body="a"))
            began = conn.info[_CONNECTION_BEGAN_AT]
            conn.exec_driver_sql("CREATE TABLE flagged (id INTEGER)")
            with conn.begin_nested():
                conn.execute(sa.select(_NOTE.c.id)).all()
            assert conn.info[_CONNECTION_BEGAN_AT] == began
            assert conn.info.get(session_module._NON_READ_STATEMENT) is True
    finally:
        engine.dispose()


def test_a_live_connection_that_wrote_is_still_declined_next_to_the_dead_one(tmp_path):
    """The dead-connection branch must be reached by an INVALIDATED connection only: a live one that wrote round the ORM stays declined."""
    engine = _engine(tmp_path / "corpus.db", explicit_begin=False)
    try:
        session = Session(engine, autoflush=False, future=True)
        try:
            session.execute(sa.select(_NOTE.c.id)).all()
            session.connection().execute(sa.insert(_NOTE).values(body="x"))
            assert session.connection().invalidated is False
            assert release_idle_connection(session) is False
            session.commit()
        finally:
            session.close()
        assert _bodies(engine) == ["x"]
    finally:
        engine.dispose()


# --------------------------------------------------------------------------- #
#  the source
# --------------------------------------------------------------------------- #
def test_the_release_still_has_one_rollback_and_reads_the_dead_connection_before_it():
    tree = ast.parse(textwrap.dedent(inspect.getsource(release_idle_connection)))
    rollbacks = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "rollback"]
    assert len(rollbacks) == 1
    invalidated = [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value == "invalidated"]
    assert invalidated and invalidated[0].lineno < rollbacks[0].lineno


def test_the_connection_begin_listener_is_registered_on_the_engine_class():
    assert event.contains(Engine, "begin", session_module._note_connection_transaction_start)
    assert not issubclass(QueuePool, Engine)
