"""``release_idle_connection`` declines a write the session's own markers cannot see -- and still releases a read (WAL / disk, 2026-10-16).

The helper ends a session's READ transaction so its pooled connection goes back. It declines on the session's own markers
(``new`` / ``dirty`` / ``deleted``, a flush, an ORM bulk statement, the write gate's flag, a savepoint). A write that goes ROUND the ORM
-- ``session.connection().execute(...)``, a Core or textual statement on that connection, the DBAPI cursor -- sets none of them, and the
rollback that frees the connection discards the write without a sound (measured by the deep read of the read-chunking change: both
writes lost). ``src/database/query.py`` patched that for its own path; the collector's ``fetch_release`` and the all-diagnostics build
called the bare helper. The helper now asks the DRIVER: the rows its connection has changed (``total_changes``) when the transaction began,
recorded by a ``Session`` ``after_begin`` listener, against the count at the release.

The row count does not move for a schema change or a PRAGMA that writes the header, and under an explicit BEGIN the rollback undoes both,
so a ``before_cursor_execute`` listener also flags, on the connection, any statement that is not a plain read
(``src/database/statement_kind.py``) and the helper declines on the flag.

WHY NOT SQLITE'S ``in_transaction``, which is what ``query.py`` used: it is True for an explicit BEGIN (the ``read_snapshot`` recipe, and
the pin ``tests/test_all_diag_read_release.py`` models and the all-diagnostics build gives back between members) exactly as it is for a
write. The controls below pin both halves: every shape of unseen write and every schema change is declined and survives, and nothing that
only reads, pins a snapshot or wrote on an EARLIER transaction of the same pooled connection is declined.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from src.database import session as session_module
from src.database.session import (
    _CHANGES_BASELINE,
    _NON_READ_STATEMENT,
    _driver_rows_changed,
    release_idle_connection,
)

_META = sa.MetaData()
_NOTE = sa.Table(
    "note",
    _META,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("body", sa.String, nullable=False, default=""),
)
_SPARE = sa.Table("spare", _META, sa.Column("id", sa.Integer, primary_key=True))


def _engine(path, *, explicit_begin: bool, pool_size: int = 2):
    """A WAL file behind a small QueuePool. ``explicit_begin`` is the ``read_snapshot`` recipe: pysqlite out of its legacy mode and a real
    BEGIN when a SQLAlchemy transaction starts."""
    engine = sa.create_engine(
        f"sqlite:///{path}", future=True, poolclass=QueuePool, pool_size=pool_size, max_overflow=0,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi, _record):  # pragma: no cover - event
        if explicit_begin:
            dbapi.isolation_level = None
        cursor = dbapi.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    if explicit_begin:

        @event.listens_for(engine, "begin")
        def _begin(conn):  # pragma: no cover - event
            conn.exec_driver_sql("BEGIN")

    _META.create_all(engine)
    return engine


@pytest.fixture(params=["legacy", "explicit-begin"])
def world(request, tmp_path):
    engine = _engine(tmp_path / "corpus.db", explicit_begin=request.param == "explicit-begin")
    with engine.begin() as conn:
        conn.execute(sa.insert(_NOTE).values(body="seed"))
    factory = sessionmaker(bind=engine, class_=Session, autoflush=False, future=True)
    yield engine, factory
    engine.dispose()


def _bodies(engine) -> list[str]:
    with engine.connect() as conn:
        return sorted(row[0] for row in conn.execute(sa.select(_NOTE.c.body)))


def _blind(session) -> None:
    """The fixture reached the state the helper's own markers cannot see: this is what makes a test below able to fail."""
    assert not (session.new or session.dirty or session.deleted)
    assert not session.info.get("_oo_txn_wrote"), "the session's own write marker saw it"
    assert not session.info.get(session_module._WRITE_GATE_SESSION_FLAG), "the write gate's marker saw it"


#: Each shape of write that goes round the ORM, with what the committed table must say afterwards.
UNSEEN_WRITES = {
    "text() on the session's connection": (lambda s: s.connection().execute(sa.text("INSERT INTO note (body) VALUES ('new')")), ["new", "seed"]),
    "a Core insert on the session's connection": (lambda s: s.connection().execute(sa.insert(_NOTE).values(body="new")), ["new", "seed"]),
    "driver SQL on the session's connection": (lambda s: s.connection().exec_driver_sql("INSERT INTO note (body) VALUES ('new')"), ["new", "seed"]),
    "an executemany on the session's connection": (
        lambda s: s.connection().execute(sa.insert(_NOTE), [{"body": "new"}, {"body": "newer"}]),
        ["new", "newer", "seed"],
    ),
    "an update on the session's connection": (lambda s: s.connection().execute(sa.update(_NOTE).values(body="changed")), ["changed"]),
    "a delete on the session's connection": (lambda s: s.connection().execute(sa.delete(_NOTE)), []),
    "the DBAPI cursor itself": (lambda s: s.connection().connection.cursor().execute("INSERT INTO note (body) VALUES ('new')"), ["new", "seed"]),
    # ``statement_kind.is_plain_read`` calls a statement that BEGINS with WITH a read, as it must (``WITH ... SELECT`` is the common form);
    # these two are writes, and only the driver's count of changed rows catches them.
    "a WITH ... INSERT": (
        lambda s: s.connection().execute(sa.text("WITH x AS (SELECT 'cte' AS b) INSERT INTO note (body) SELECT b FROM x")),
        ["cte", "seed"],
    ),
    "a WITH ... DELETE": (
        lambda s: s.connection().execute(sa.text("WITH x AS (SELECT 1 AS one) DELETE FROM note WHERE EXISTS (SELECT 1 FROM x)")),
        [],
    ),
}


@pytest.mark.parametrize("shape", sorted(UNSEEN_WRITES))
def test_a_write_round_the_orm_is_declined_and_survives_the_commit(world, shape):
    """The load-bearing half is the SURVIVAL: a version that released anyway still returns, and only the table says what became of the write."""
    engine, factory = world
    write, expected = UNSEEN_WRITES[shape]
    session = factory()
    try:
        session.execute(sa.select(_NOTE.c.id)).all()  # a read first: the helper is asked about a session that has read, then written
        write(session)
        _blind(session)
        released = release_idle_connection(session)
        assert engine.pool.checkedout() == 1, "a declined release keeps the connection"
        session.commit()
        assert _bodies(engine) == expected, "the write was discarded"
        assert released is False, "a session that wrote was released"
    finally:
        session.close()


def test_a_session_that_wrote_with_no_read_before_it_is_declined_too(world):
    """The transaction begins at the first statement, which here is the write: its baseline is taken before it."""
    engine, factory = world
    session = factory()
    try:
        session.connection().execute(sa.insert(_NOTE).values(body="first"))
        _blind(session)
        released = release_idle_connection(session)
        session.commit()
        assert _bodies(engine) == ["first", "seed"] and released is False
    finally:
        session.close()


def test_session_execute_of_a_textual_write_is_declined_whatever_marker_sees_it(world):
    engine, factory = world
    session = factory()
    try:
        session.execute(sa.text("INSERT INTO note (body) VALUES ('text')"))
        released = release_idle_connection(session)
        session.commit()
        assert _bodies(engine) == ["seed", "text"] and released is False
    finally:
        session.close()


# --------------------------------------------------------------------------- #
#  what must still be released: the controls that fail a check that declines everything
# --------------------------------------------------------------------------- #
def test_a_session_that_only_read_is_released(world):
    engine, factory = world
    session = factory()
    try:
        session.execute(sa.select(_NOTE.c.id)).all()
        assert engine.pool.checkedout() == 1
        assert release_idle_connection(session) is True
        assert engine.pool.checkedout() == 0, "the connection did not go back"
    finally:
        session.close()


def test_an_update_that_changed_no_row_is_declined_too_because_the_statement_could_have_written(world):
    """The statement listener flags anything that is not a plain read, so an UPDATE that matched nothing declines like one that matched a
    row. Stated as a cost, not a bug: nothing was lost either way, and the connection is kept until the caller's own commit."""
    engine, factory = world
    session = factory()
    try:
        session.connection().execute(sa.update(_NOTE).where(_NOTE.c.id == -1).values(body="nobody"))
        assert release_idle_connection(session) is False
        assert engine.pool.checkedout() == 1
        session.commit()
        assert engine.pool.checkedout() == 0
    finally:
        session.close()


def test_writes_committed_on_an_earlier_transaction_of_the_same_pooled_connection_do_not_decline_a_later_read(tmp_path):
    """The baseline is the count when THIS transaction began, not zero: a connection that has written a thousand rows in its life is not 'written'."""
    engine = _engine(tmp_path / "corpus.db", explicit_begin=False, pool_size=1)
    factory = sessionmaker(bind=engine, class_=Session, autoflush=False, future=True)
    try:
        first = factory()
        first.connection().execute(sa.insert(_NOTE).values(body="earlier"))
        first.commit()
        first_driver = first.connection().connection.dbapi_connection
        first.close()
        second = factory()
        try:
            second.execute(sa.select(_NOTE.c.id)).all()
            assert second.connection().connection.dbapi_connection is first_driver, "the control needs the SAME physical connection"
            assert _driver_rows_changed(second.connection()) >= 1, "the control needs a connection that has written"
            assert release_idle_connection(second) is True
            assert engine.pool.checkedout() == 0
        finally:
            second.close()
    finally:
        engine.dispose()


def test_a_released_session_starts_a_new_baseline_and_a_committed_write_does_not_haunt_the_next_transaction(world):
    engine, factory = world
    session = factory()
    try:
        session.execute(sa.select(_NOTE.c.id)).all()
        assert release_idle_connection(session) is True
        assert _CHANGES_BASELINE not in session.info, "the baseline outlived its transaction"
        session.connection().execute(sa.insert(_NOTE).values(body="w"))
        assert release_idle_connection(session) is False
        session.commit()
        assert _CHANGES_BASELINE not in session.info
        session.execute(sa.select(_NOTE.c.id)).all()
        assert len(session.info[_CHANGES_BASELINE]) == 1, "a new transaction records its own baseline"
        assert release_idle_connection(session) is True, "the earlier committed write declined a transaction that only read"
        assert _bodies(engine) == ["seed", "w"]
    finally:
        session.close()


def test_a_finished_savepoint_does_not_erase_the_baseline_of_the_transaction_around_it(world):
    """A savepoint has a parent: its end must not clear what the root transaction recorded (the over-decline half of the clearing rule)."""
    engine, factory = world
    session = factory()
    try:
        session.execute(sa.select(_NOTE.c.id)).all()
        nested = session.begin_nested()
        session.execute(sa.select(_NOTE.c.id)).all()
        nested.commit()
        assert not session.in_nested_transaction()
        assert len(session.info[_CHANGES_BASELINE]) == 1, "the savepoint's end cleared the root transaction's baseline"
        assert release_idle_connection(session) is True
    finally:
        session.close()


def test_an_explicit_begin_that_only_read_is_still_given_back(tmp_path):
    """The pin the all-diagnostics build gives back between members: SQLite's own in_transaction is True here, a write would be too."""
    engine = _engine(tmp_path / "corpus.db", explicit_begin=True)
    factory = sessionmaker(bind=engine, class_=Session, autoflush=False, future=True)
    try:
        session = factory()
        try:
            session.execute(sa.select(_NOTE.c.id)).all()
            assert session.connection().connection.dbapi_connection.in_transaction is True, "the control needs an explicit BEGIN open"
            assert release_idle_connection(session) is True
            assert engine.pool.checkedout() == 0
        finally:
            session.close()
    finally:
        engine.dispose()


# --------------------------------------------------------------------------- #
#  a schema change or a header PRAGMA moves no row count: the statement listener flags it
# --------------------------------------------------------------------------- #
def _tables(engine) -> list[str]:
    return sorted(sa.inspect(engine).get_table_names())


def _columns(engine, table: str) -> list[str]:
    return [c["name"] for c in sa.inspect(engine).get_columns(table)]


def _user_version(engine) -> int:
    with engine.connect() as conn:
        return conn.exec_driver_sql("PRAGMA user_version").scalar()


#: Each schema change or header write, sent on the session's connection, with a reader of what the database must say once it is committed.
UNSEEN_SCHEMA_CHANGES = {
    "CREATE TABLE": (lambda s: s.connection().execute(sa.text("CREATE TABLE extra (id INTEGER)")), lambda e: "extra" in _tables(e)),
    "CREATE TABLE through the driver": (
        lambda s: s.connection().exec_driver_sql("CREATE TABLE extra (id INTEGER)"),
        lambda e: "extra" in _tables(e),
    ),
    "DROP TABLE": (lambda s: s.connection().execute(sa.text("DROP TABLE spare")), lambda e: "spare" not in _tables(e)),
    "ALTER TABLE": (lambda s: s.connection().execute(sa.text("ALTER TABLE note ADD COLUMN added TEXT")), lambda e: "added" in _columns(e, "note")),
    "CREATE INDEX": (
        lambda s: s.connection().execute(sa.text("CREATE INDEX note_body ON note (body)")),
        lambda e: "note_body" in [i["name"] for i in sa.inspect(e).get_indexes("note")],
    ),
    "PRAGMA user_version = 7": (lambda s: s.connection().exec_driver_sql("PRAGMA user_version = 7"), lambda e: _user_version(e) == 7),
    "PRAGMA user_version(8)": (lambda s: s.connection().exec_driver_sql("PRAGMA user_version(8)"), lambda e: _user_version(e) == 8),
}


@pytest.mark.parametrize("shape", sorted(UNSEEN_SCHEMA_CHANGES))
def test_a_schema_change_through_the_sessions_connection_is_declined_and_survives_the_commit(world, shape):
    """The survival is the load-bearing half, and it can only fail under the explicit BEGIN, where the rollback undoes the change."""
    engine, factory = world
    change, committed = UNSEEN_SCHEMA_CHANGES[shape]
    session = factory()
    try:
        session.execute(sa.select(_NOTE.c.id)).all()
        change(session)
        _blind(session)
        released = release_idle_connection(session)
        assert engine.pool.checkedout() == 1, "a declined release keeps the connection"
        session.commit()
        assert committed(engine), "the schema change was discarded"
        assert released is False, "a session that changed the schema was released"
    finally:
        session.close()


def test_a_create_table_through_the_sessions_connection_is_declined(world):
    """The relay's named case, stated alone: ``CREATE TABLE`` through ``session.connection()`` must be declined."""
    engine, factory = world
    session = factory()
    try:
        session.connection().execute(sa.text("CREATE TABLE extra (id INTEGER)"))
        assert session.connection().info.get(_NON_READ_STATEMENT) is True, "the statement listener did not flag it"
        assert release_idle_connection(session) is False
    finally:
        session.close()


#: What a release must still give back: each is a plain read in a form SQLAlchemy or the diagnostics send.
STILL_RELEASED = {
    "SELECT": "SELECT id FROM note",
    "a CTE": "WITH ids AS (SELECT id FROM note) SELECT id FROM ids",
    "EXPLAIN QUERY PLAN": "EXPLAIN QUERY PLAN SELECT id FROM note",
    "PRAGMA page_count": "PRAGMA page_count",
    "PRAGMA user_version (read)": "PRAGMA user_version",
    "PRAGMA table_info": "PRAGMA table_info(note)",
    "PRAGMA index_list": "PRAGMA index_list(note)",
    "PRAGMA main.freelist_count": "PRAGMA main.freelist_count",
    "lower case and indented": "   select id from note",
}


@pytest.mark.parametrize("name", sorted(STILL_RELEASED))
def test_a_plain_read_in_any_of_its_forms_is_still_released(world, name):
    engine, factory = world
    session = factory()
    try:
        session.connection().exec_driver_sql(STILL_RELEASED[name]).fetchall()
        assert not session.connection().info.get(_NON_READ_STATEMENT), "a plain read was flagged"
        assert release_idle_connection(session) is True
        assert engine.pool.checkedout() == 0
    finally:
        session.close()


def test_the_flag_of_one_transaction_does_not_haunt_the_next_one_on_the_same_connection(tmp_path):
    engine = _engine(tmp_path / "corpus.db", explicit_begin=False, pool_size=1)
    factory = sessionmaker(bind=engine, class_=Session, autoflush=False, future=True)
    try:
        first = factory()
        first.connection().execute(sa.text("CREATE TABLE extra (id INTEGER)"))
        first_driver = first.connection().connection.dbapi_connection
        assert first.connection().info.get(_NON_READ_STATEMENT) is True
        first.commit()
        first.close()
        second = factory()
        try:
            second.execute(sa.select(_NOTE.c.id)).all()
            assert second.connection().connection.dbapi_connection is first_driver, "the control needs the SAME physical connection"
            assert not second.connection().info.get(_NON_READ_STATEMENT), "the earlier transaction's flag outlived it"
            assert release_idle_connection(second) is True
        finally:
            second.close()
    finally:
        engine.dispose()


def test_a_savepoint_that_begins_after_a_schema_change_does_not_clear_the_flag(world):
    """``after_begin`` fires for a savepoint too: it must neither reset the flag nor move the baseline of the transaction around it."""
    engine, factory = world
    session = factory()
    try:
        session.execute(sa.select(_NOTE.c.id)).all()
        session.connection().execute(sa.text("CREATE TABLE extra (id INTEGER)"))
        nested = session.begin_nested()
        session.execute(sa.select(_NOTE.c.id)).all()
        nested.commit()
        assert not session.in_nested_transaction()
        assert release_idle_connection(session) is False, "the savepoint's beginning cleared the flag"
        session.commit()
        assert "extra" in _tables(engine)
    finally:
        session.close()


def test_a_savepoint_that_begins_after_an_unseen_write_does_not_move_the_baseline(world):
    """Measured 2026-10-16 on the first version of this helper: the baseline was taken again when the savepoint began, with the write
    already in the count, so the release saw 'nothing changed' and the rollback discarded the row."""
    engine, factory = world
    session = factory()
    try:
        session.execute(sa.select(_NOTE.c.id)).all()
        (key,) = session.info[_CHANGES_BASELINE]
        at_begin = session.info[_CHANGES_BASELINE][key]
        session.connection().execute(sa.insert(_NOTE).values(body="unseen"))
        nested = session.begin_nested()
        session.execute(sa.select(_NOTE.c.id)).all()
        nested.commit()
        assert session.info[_CHANGES_BASELINE] == {key: at_begin}, "the savepoint's beginning moved the baseline"
        assert release_idle_connection(session) is False
        session.commit()
        assert _bodies(engine) == ["seed", "unseen"]
    finally:
        session.close()


# --------------------------------------------------------------------------- #
#  what the helper cannot say, it declines
# --------------------------------------------------------------------------- #
def test_a_count_the_driver_cannot_give_declines_the_release(world, monkeypatch):
    engine, factory = world
    session = factory()
    try:
        session.execute(sa.select(_NOTE.c.id)).all()
        monkeypatch.setattr(session_module, "_driver_rows_changed", lambda _connection: None)
        assert release_idle_connection(session) is False
        assert engine.pool.checkedout() == 1
        monkeypatch.undo()
        assert release_idle_connection(session) is True
    finally:
        session.close()


def test_a_transaction_with_no_recorded_start_declines_the_release(world):
    engine, factory = world
    session = factory()
    try:
        session.execute(sa.select(_NOTE.c.id)).all()
        del session.info[_CHANGES_BASELINE]
        assert release_idle_connection(session) is False
        assert engine.pool.checkedout() == 1
    finally:
        session.close()


def test_a_session_with_a_baseline_for_a_second_connection_declines_the_release(world):
    """A session bound to two connections: the helper can say nothing about the one it did not count."""
    engine, factory = world
    session = factory()
    try:
        session.execute(sa.select(_NOTE.c.id)).all()
        session.info[_CHANGES_BASELINE][12345] = 0
        assert release_idle_connection(session) is False
    finally:
        session.close()


def test_a_baseline_for_another_connection_declines_the_release(world):
    engine, factory = world
    session = factory()
    try:
        session.execute(sa.select(_NOTE.c.id)).all()
        (only,) = session.info[_CHANGES_BASELINE].values()
        session.info[_CHANGES_BASELINE] = {12345: only}
        assert release_idle_connection(session) is False
    finally:
        session.close()


class _NoCount:
    class connection:  # noqa: N801 - mirrors the SQLAlchemy attribute path
        class dbapi_connection:  # noqa: N801
            pass


class _OddCount:
    class connection:  # noqa: N801
        class dbapi_connection:  # noqa: N801
            total_changes = "3"


class _BoolCount:
    class connection:  # noqa: N801
        class dbapi_connection:  # noqa: N801
            total_changes = True


@pytest.mark.parametrize("connection", [_NoCount, _OddCount, _BoolCount, None, object()])
def test_a_count_that_is_not_an_integer_is_not_a_count(connection):
    assert _driver_rows_changed(connection) is None


def test_the_listener_that_takes_the_baseline_is_registered_on_every_session_and_the_one_that_clears_it_ends_with_the_root_transaction():
    assert event.contains(Session, "after_begin", session_module._note_rows_changed_at_begin)
    assert event.contains(Session, "after_transaction_end", session_module._clear_wrote)
    assert event.contains(Engine, "before_cursor_execute", session_module._note_statement_that_is_not_a_read)
    source = inspect.getsource(session_module._clear_wrote)
    assert source.index("transaction.parent is None") < source.index("_CHANGES_BASELINE"), "the baseline must be cleared with the ROOT transaction only"


# --------------------------------------------------------------------------- #
#  the driver the app encrypts with counts the same way
# --------------------------------------------------------------------------- #
def test_the_encrypted_driver_is_counted_too(tmp_path):
    sqlcipher = pytest.importorskip("sqlcipher3.dbapi2")
    path = tmp_path / "enc.db"

    def creator():
        conn = sqlcipher.connect(str(path), check_same_thread=False)
        conn.execute("PRAGMA key = 'a-test-key'")
        return conn

    engine = sa.create_engine("sqlite://", creator=creator, poolclass=QueuePool, pool_size=2, max_overflow=0, future=True)
    try:
        _META.create_all(engine)
        with engine.begin() as conn:
            conn.execute(sa.insert(_NOTE).values(body="seed"))
        factory = sessionmaker(bind=engine, class_=Session, autoflush=False, future=True)
        reader = factory()
        try:
            reader.execute(sa.select(_NOTE.c.id)).all()
            assert isinstance(_driver_rows_changed(reader.connection()), int), "the encrypted driver gave no count"
            assert release_idle_connection(reader) is True
        finally:
            reader.close()
        writer = factory()
        try:
            writer.execute(sa.select(_NOTE.c.id)).all()
            writer.connection().execute(sa.insert(_NOTE).values(body="enc"))
            assert release_idle_connection(writer) is False
            writer.commit()
        finally:
            writer.close()
        assert _bodies(engine) == ["enc", "seed"]
        schema = factory()
        try:
            schema.execute(sa.select(_NOTE.c.id)).all()
            schema.connection().execute(sa.text("CREATE TABLE extra (id INTEGER)"))
            assert release_idle_connection(schema) is False, "the statement listener did not flag a schema change on the encrypted driver"
            schema.commit()
        finally:
            schema.close()
        assert "extra" in _tables(engine)
    finally:
        engine.dispose()


# --------------------------------------------------------------------------- #
#  the source: the check is before the rollback it guards
# --------------------------------------------------------------------------- #
def test_the_rows_changed_check_is_made_before_the_rollback_it_guards():
    tree = ast.parse(textwrap.dedent(inspect.getsource(release_idle_connection)))
    rollback = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "rollback"]
    assert len(rollback) == 1, "the helper has exactly one rollback"
    reads = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_driver_rows_changed"
    ]
    baselines = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "_CHANGES_BASELINE"]
    flags = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "_NON_READ_STATEMENT"]
    assert reads and baselines, "the helper must read the driver's count and the baseline"
    assert flags, "the helper must read the flag the statement listener sets"
    assert all(n.lineno < rollback[0].lineno for n in [*reads, *baselines, *flags]), "the check must come before the rollback"
    assert any(
        isinstance(n, ast.Return) and flags[0].lineno < n.lineno < rollback[0].lineno for n in ast.walk(tree)
    ), "the flag must be able to decline: a `return` between it and the rollback"
    returns_before = [
        n for n in ast.walk(tree) if isinstance(n, ast.Return) and n.lineno < rollback[0].lineno and n.lineno > min(r.lineno for r in reads)
    ]
    assert returns_before, "the check must be able to decline: a `return` between it and the rollback"
