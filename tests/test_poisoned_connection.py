"""One damaged page must not leave a pooled connection answering ``MemoryError`` to everything after it (E1).

MEASURED on a real encrypted store (SQLCipher): after the first read of a page that fails its check
(``SQLITE_CORRUPT``, "database disk image is malformed"), EVERY later page read on that connection raises
``MemoryError`` with no message, healthy tables included; ``rollback``, ``commit``, ``shrink_memory`` and a second
``PRAGMA key`` do not clear it, only a new connection does. A pooled connection goes back to the pool in that
state, so one request that touches a damaged page leaves a connection that fails every later request with the text
of a real out-of-memory until the process restarts, and the log reads as if memory had run out. The damage observer
marks a SQLCipher code-11 error as a disconnect for that one connection. What is pinned, on REAL encrypted stores:

  * the canary: without the observer the poison is there (if SQLCipher stops doing this, the fix is moot and this
    test says so);
  * with it, the next read on the pool is answered, the error that reaches the caller is still the corruption
    error, the latch and the incident record are as before;
  * only the connection that read the page is replaced (the rest of the pool is the same objects), and a
    repeated bad read costs one reconnect each, never a growing pool;
  * a session in a transaction on the discarded connection must roll back to go on: its flushed writes are
    gone, its commit raises ``PendingRollbackError`` and never persists a part of the transaction;
  * the FIRST error is not always code 11: the last overflow page of a long value fails silently and the
    poison arrives on the NEXT statement as an empty ``MemoryError``, which is discarded too and is never
    latched or recorded (a real out-of-memory raises the same);
  * only SQLCipher's code 11, and an empty ``MemoryError`` on a SQLCipher connection, are reclassified: a
    ``MemoryError`` with a message, a wrong-key error (26), a plain-SQLite corruption error and a context whose
    connection is already closed are not;
  * a statement on the DRIVER's own cursor over a pooled connection raises past the engine's observer, so each
    such site goes through ``damage.guard_raw_driver`` (the country-code scan, the incremental vacuum and the
    WAL checkpoint): the connection is discarded and the file is named, and the error is still the caller's.
"""
from __future__ import annotations

import random
import sqlite3
import types
from pathlib import Path

import pytest

pytest.importorskip("sqlcipher3")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.exc import DBAPIError, PendingRollbackError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import QueuePool  # noqa: E402
from sqlcipher3 import dbapi2 as sqc  # noqa: E402

from src.database import damage  # noqa: E402
from src.database.connect import connect  # noqa: E402
from src.database.damage import FILE_CORPUS  # noqa: E402

_KEY = "poisoned connection test key"
_PAGE = 16384
_BAD_RANGE = "SELECT id, v FROM big WHERE id BETWEEN :lo AND :hi"
#: What a failed read raises. The app's engines use the stdlib SQLite dialect over a SQLCipher ``creator``, so
#: SQLAlchemy does not recognise the driver's exception class and lets it through UNWRAPPED (``handle_error`` still
#: sees it); a driver SQLAlchemy knows would arrive wrapped. Both are accepted.
_DB_ERRORS = (DBAPIError, sqc.DatabaseError)


def _build(path: Path, *, incremental: bool = False) -> list[int]:
    """An encrypted store with a small table and a wide one; one page of the wide one is overwritten. Returns the
    ids of ``big``. ``incremental`` makes it an ``auto_vacuum=INCREMENTAL`` store, the mode the incremental vacuum
    works on."""
    con = connect(path, key=_KEY, create_encrypted=True, check_same_thread=False)
    con.execute("CREATE TABLE small (a INTEGER)")
    con.execute("INSERT INTO small VALUES (1), (2), (3)")
    con.commit()
    if incremental:
        con.execute("PRAGMA auto_vacuum=2")
        con.execute("VACUUM")
    con.execute("CREATE TABLE big (id INTEGER PRIMARY KEY, v BLOB)")
    rng = random.Random(4)
    con.executemany("INSERT INTO big (v) VALUES (?)", [(rng.randbytes(3000),) for _ in range(900)])
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    pages = path.stat().st_size // _PAGE
    bad = pages // 2 + 3  # well inside ``big`` (the small table sits at the start of the file)
    with open(path, "r+b") as f:
        f.seek((bad - 1) * _PAGE)
        f.write(random.Random(bad).randbytes(_PAGE))
    return list(range(1, 901))


_LONG = random.Random(7).randbytes(120_000)  # a value of about eight pages: its tail is an overflow chain


def _build_overflow(path: Path, damaged: str) -> int:
    """An encrypted store whose ``ov`` table holds ONE row, a value longer than seven pages, so that the file's
    last page is the last page of that value's overflow chain. ``damaged`` names which page of the chain is
    overwritten: ``"last"``, ``"middle"`` or ``"first"``. Returns the page number overwritten."""
    con = connect(path, key=_KEY, create_encrypted=True, check_same_thread=False)
    con.execute("CREATE TABLE small (a INTEGER)")
    con.execute("INSERT INTO small VALUES (1), (2), (3)")
    con.execute("CREATE TABLE ov (id INTEGER PRIMARY KEY, v BLOB)")
    con.execute("INSERT INTO ov (id, v) VALUES (1, ?)", (_LONG,))
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    pages = path.stat().st_size // _PAGE
    target = {"last": pages, "middle": pages - 3, "first": pages - 7}[damaged]
    with open(path, "r+b") as f:
        f.seek((target - 1) * _PAGE)
        f.write(random.Random(target).randbytes(_PAGE))
    return target


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "corpus.db"
    _build(path)
    return path


def _read_bad_range(executor) -> BaseException:
    """Read ranges of ``big`` through ``executor`` (a Connection, a Session or anything with ``execute(text)``)
    until one raises corruption; return that error. A damaged leaf is invisible to a count."""
    for lo in range(1, 901, 100):
        try:
            executor.execute(text(_BAD_RANGE), {"lo": lo, "hi": lo + 99}).fetchall()
        except _DB_ERRORS as exc:
            assert damage.is_corruption(exc), exc
            return exc
    pytest.fail("no range of the wide table failed: the overwrite missed it")


class _FaultyCursor:
    """A cursor whose statement matching ``trigger`` first reads a damaged page on the REAL connection, so the
    real driver raises its real code-11 error and the real connection is really poisoned."""

    def __init__(self, owner, cursor, trigger):
        self._owner, self._cursor, self._trigger = owner, cursor, trigger

    def execute(self, sql, *args, **kwargs):
        if self._trigger in str(sql):
            for lo in range(1, 901, 100):
                self._owner.real.execute(_BAD_RANGE.replace(":lo", str(lo)).replace(":hi", str(lo + 99))).fetchall()
            raise AssertionError("the damaged page was not read")
        return self._cursor.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _FaultyConnection:
    """A SQLCipher connection that fails a chosen driver statement the way a damaged page does."""

    def __init__(self, real, trigger):
        self.real, self._trigger = real, trigger

    def cursor(self, *args, **kwargs):
        return _FaultyCursor(self, self.real.cursor(*args, **kwargs), self._trigger)

    def __getattr__(self, name):
        return getattr(self.real, name)


def _engine(path: Path, *, observed: bool, pool_size: int = 3, faulty: str | None = None, url: bool = False):
    """A pool of ``pool_size`` over the encrypted store; ``opened`` lists every driver connection it ever made.
    ``faulty`` wraps each connection so that a driver statement containing that text hits the damaged page;
    ``url`` gives the engine the file's own URL (its records then name the file)."""
    opened: list[object] = []

    def creator():
        conn = connect(path, key=_KEY, check_same_thread=False)
        if faulty:
            conn = _FaultyConnection(conn, faulty)
        opened.append(conn)
        return conn

    eng = create_engine(
        f"sqlite:///{path}" if url else "sqlite://",
        creator=creator,
        poolclass=QueuePool,
        pool_size=pool_size,
        max_overflow=0,
    )
    if observed:
        damage.attach(eng, FILE_CORPUS)
    return eng, opened


def _first_bad_range(eng) -> None:
    """One read of the damaged table on a connection of ``eng``, which raises corruption."""
    with eng.connect() as c:
        _read_bad_range(c)


def _healthy_read(eng) -> int:
    with eng.connect() as c:
        return c.execute(text("SELECT count(*) FROM small")).scalar_one()


@pytest.fixture
def registry(tmp_path):
    damage.registry._reset_for_tests(path_fn=lambda: tmp_path / "database-damage.json")
    return damage.registry


def test_canary_without_the_observer_the_pooled_connection_is_poisoned(store):
    """The driver fact the fix answers. If this stops failing, SQLCipher stopped poisoning and the fix is moot."""
    eng, opened = _engine(store, observed=False, pool_size=1)
    _first_bad_range(eng)
    with pytest.raises(MemoryError):
        _healthy_read(eng)
    with pytest.raises(MemoryError):
        _healthy_read(eng)  # and it stays poisoned: the same pooled connection comes back every time
    assert len(opened) == 1, "a new connection was opened: the pool did not hand the poisoned one back"


def test_with_the_observer_the_next_read_is_answered_and_the_error_is_still_the_corruption_error(store, registry):
    eng, opened = _engine(store, observed=True, pool_size=1)
    try:
        with eng.connect() as c:
            exc = _read_bad_range(c)
        assert damage.is_corruption(exc), "the error that reaches the caller is no longer the corruption error"
        assert _healthy_read(eng) == 3
        assert _healthy_read(eng) == 3
        assert len(opened) == 2, "the poisoned connection was not replaced by exactly one new one"
        # the latch and the incident are as before the change
        assert registry.latched(FILE_CORPUS), "the latch is no longer set by the corruption error"
        assert registry.state()["incident_count"] == 1, "one failed read is one incident"
    finally:
        eng.dispose()


def test_only_the_connection_that_read_the_page_is_replaced(store, registry):
    eng, opened = _engine(store, observed=True, pool_size=3)
    try:
        held = [eng.connect() for _ in range(3)]
        for c in held:
            c.close()
        originals = list(opened)
        assert len(originals) == 3
        _first_bad_range(eng)
        # hold all three at once: which DRIVER connections is the pool made of now?
        held = [eng.connect() for _ in range(3)]
        try:
            now = [h.connection.dbapi_connection for h in held]
            kept = [c for c in now if any(c is o for o in originals)]
            assert len(kept) == 2, f"{len(kept)} of 3 pooled connections are the originals: the whole pool was replaced"
            assert len(opened) == 4, f"{len(opened)} connections were opened for one bad read"
            for h in held:
                assert h.execute(text("SELECT count(*) FROM small")).scalar_one() == 3
        finally:
            for h in held:
                h.close()
    finally:
        eng.dispose()


def test_a_repeated_bad_read_costs_one_reconnect_each_and_the_pool_does_not_grow(store, registry):
    eng, opened = _engine(store, observed=True, pool_size=3)
    try:
        warm = [eng.connect() for _ in range(3)]  # three idle connections, so a pool-wide invalidation is visible
        for c in warm:
            c.close()
        assert len(opened) == 3
        for _ in range(5):
            _first_bad_range(eng)
            assert _healthy_read(eng) == 3
        for _ in range(3):  # cycle the pool, so every discarded slot has been opened again
            assert _healthy_read(eng) == 3
        assert eng.pool.checkedout() == 0
        # exactly one new connection per bad read: a pool-wide invalidation would add three each time
        assert len(opened) == 3 + 5, f"{len(opened)} connections opened for five bad reads"
    finally:
        eng.dispose()


def test_a_session_that_was_in_a_transaction_on_the_discarded_connection_rolls_back_and_works_again(store, registry):
    eng, _opened = _engine(store, observed=True, pool_size=1)
    try:
        with Session(eng) as s:
            assert s.execute(text("SELECT count(*) FROM small")).scalar_one() == 3
            _read_bad_range(s)
            s.rollback()
            assert s.execute(text("SELECT count(*) FROM small")).scalar_one() == 3
    finally:
        eng.dispose()


def test_a_session_that_flushed_before_the_bad_read_cannot_commit_and_loses_the_flush(store, registry):
    """The connection is CLOSED, not rolled back: what the session had flushed is gone with it, and its commit
    raises until it rolls back, so a part of a transaction is never persisted."""
    eng, _opened = _engine(store, observed=True, pool_size=1)
    try:
        with Session(eng) as s:
            s.execute(text("INSERT INTO small VALUES (99)"))
            assert s.execute(text("SELECT count(*) FROM small")).scalar_one() == 4  # flushed, not committed
            _read_bad_range(s)
            with pytest.raises(PendingRollbackError):
                s.execute(text("SELECT 1"))
            with pytest.raises(PendingRollbackError):
                s.commit()
            s.rollback()
            assert s.execute(text("SELECT count(*) FROM small WHERE a = 99")).scalar_one() == 0
            assert s.execute(text("SELECT count(*) FROM small")).scalar_one() == 3
        assert _healthy_read(eng) == 3
    finally:
        eng.dispose()


# -- the first error is not always code 11 (the overflow chain of a long value) ----------------------------------


@pytest.mark.parametrize("damaged", ["first", "middle"])
def test_a_damaged_first_or_middle_overflow_page_raises_code_11_on_that_read(tmp_path, damaged):
    path = tmp_path / "ov.db"
    _build_overflow(path, damaged)
    con = connect(path, key=_KEY, check_same_thread=False)
    try:
        with pytest.raises(sqc.DatabaseError) as info:
            con.execute("SELECT v FROM ov WHERE id = 1").fetchone()
        assert getattr(info.value, "sqlite_errorcode", None) == 11
        with pytest.raises(MemoryError):
            con.execute("SELECT count(*) FROM small").fetchall()  # and the poison follows
    finally:
        con.close()


def test_a_damaged_last_overflow_page_returns_the_wrong_tail_with_no_error_and_poisons_the_next_statement(tmp_path):
    """MEASURED. The premise 'every connection that reads a damaged page fails first with code 11' holds for a
    leaf and for the first and middle pages of an overflow chain, and NOT for its last page: the read returns the
    whole length with wrong bytes at the tail, and the connection answers an empty ``MemoryError`` to the next
    statement."""
    path = tmp_path / "ov.db"
    _build_overflow(path, "last")
    con = connect(path, key=_KEY, check_same_thread=False)
    try:
        value = con.execute("SELECT v FROM ov WHERE id = 1").fetchone()[0]
        assert len(value) == len(_LONG) and value != _LONG, "the read raised or returned the right bytes"
        with pytest.raises(MemoryError) as info:
            con.execute("SELECT count(*) FROM small").fetchall()
        assert type(info.value) is MemoryError and not str(info.value)
    finally:
        con.close()


def test_the_observer_discards_a_connection_that_answers_an_empty_memory_error_and_latches_nothing(tmp_path, registry):
    path = tmp_path / "ov.db"
    _build_overflow(path, "last")
    eng, opened = _engine(path, observed=True, pool_size=1)
    try:
        with eng.connect() as c:
            value = c.execute(text("SELECT v FROM ov WHERE id = 1")).scalar_one()
        assert value != _LONG  # the read that touched the page raised nothing
        with pytest.raises(MemoryError):
            _healthy_read(eng)  # the one statement that pays, and it is the caller's own error
        assert _healthy_read(eng) == 3, "the poisoned connection went back to the pool"
        assert len(opened) == 2
        # an empty MemoryError names no file: a real allocation failure raises the same
        assert not registry.latched(FILE_CORPUS)
        assert registry.state()["incident_count"] == 0
    finally:
        eng.dispose()


# -- the rule itself, on real driver errors and on stand-ins ----------------------------------------------------


def _conn(dbapi=None, *, closed: bool = False):
    """What ``context.connection`` looks like to the rule: a SQLAlchemy Connection over a pooled one over the
    driver's."""
    return types.SimpleNamespace(
        closed=closed, invalidated=False, connection=types.SimpleNamespace(dbapi_connection=dbapi)
    )


_DEFAULT = object()


def _ctx(exc: BaseException, *, connection=_DEFAULT, dbapi=None):
    if connection is _DEFAULT:
        connection = _conn(dbapi)
    return types.SimpleNamespace(
        original_exception=exc, connection=connection, is_disconnect=False, invalidate_pool_on_disconnect=True
    )


def _real_code_11(store) -> sqc.DatabaseError:
    con = connect(store, key=_KEY, check_same_thread=False)
    try:
        for start in range(1, 901, 100):
            try:
                con.execute(_BAD_RANGE.replace(":lo", str(start)).replace(":hi", str(start + 99))).fetchall()
            except sqc.DatabaseError as exc:
                assert getattr(exc, "sqlite_errorcode", None) == 11
                return exc
    finally:
        con.close()
    pytest.fail("no range of the wide table failed")


def test_only_code_11_from_the_sqlcipher_driver_is_reclassified(store, tmp_path):
    # a real code-11 error from SQLCipher: reclassified, for this one connection only
    real = _real_code_11(store)
    ctx = _ctx(real)
    assert damage.discard_poisoned_connection(ctx) is True
    assert ctx.is_disconnect is True and ctx.invalidate_pool_on_disconnect is False

    # a MemoryError WITH a message is a real out-of-memory, whatever the connection is
    sqcon = sqc.connect(":memory:")
    try:
        for other in (MemoryError("out of memory"), RuntimeError("database disk image is malformed")):
            ctx = _ctx(other, dbapi=sqcon)
            assert damage.discard_poisoned_connection(ctx) is False
            assert ctx.is_disconnect is False and ctx.invalidate_pool_on_disconnect is True
    finally:
        sqcon.close()

    # a wrong key (SQLITE_NOTADB, 26) is a real SQLCipher error and is not corruption
    wrong = None
    c = sqc.connect(str(store))
    try:
        c.execute("PRAGMA key = 'not the key'")
        c.execute("SELECT count(*) FROM sqlite_master").fetchall()
    except sqc.DatabaseError as exc:
        wrong = exc
    finally:
        c.close()
    assert wrong is not None and getattr(wrong, "sqlite_errorcode", None) == 26
    ctx = _ctx(wrong)
    assert damage.discard_poisoned_connection(ctx) is False and ctx.is_disconnect is False

    # a plain-SQLite file's corruption does not poison its connection and is not reclassified
    plain = tmp_path / "plain.db"
    pc = sqlite3.connect(plain)
    pc.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v BLOB)")
    pc.executemany("INSERT INTO t (v) VALUES (?)", [(random.Random(i).randbytes(3000),) for i in range(900)])
    pc.commit()
    pc.close()
    size = plain.stat().st_size
    with open(plain, "r+b") as f:
        f.seek((size // 4096 // 2) * 4096)
        f.write(random.Random(1).randbytes(4096))
    pc = sqlite3.connect(plain)
    err = None
    for start in range(1, 901, 50):
        try:
            pc.execute("SELECT id, v FROM t WHERE id BETWEEN ? AND ?", (start, start + 49)).fetchall()
        except sqlite3.DatabaseError as exc:
            err = exc
            break
    pc.close()
    assert err is not None and damage.is_corruption(err)
    ctx = _ctx(err, dbapi=sqlite3.connect(":memory:"))
    assert damage.discard_poisoned_connection(ctx) is False and ctx.is_disconnect is False


def test_an_empty_memory_error_is_discarded_only_on_a_sqlcipher_connection():
    sqcon, plain = sqc.connect(":memory:"), sqlite3.connect(":memory:")
    try:
        ctx = _ctx(MemoryError(), dbapi=sqcon)
        assert damage.discard_poisoned_connection(ctx) is True
        assert ctx.is_disconnect is True and ctx.invalidate_pool_on_disconnect is False
        for dbapi in (plain, None):  # a plain SQLite connection is not poisoned; no connection, no evidence
            ctx = _ctx(MemoryError(), dbapi=dbapi)
            assert damage.discard_poisoned_connection(ctx) is False
            assert ctx.is_disconnect is False and ctx.invalidate_pool_on_disconnect is True
        # a subclass is a different error from the poison's own
        class Other(MemoryError):
            pass

        assert damage.discard_poisoned_connection(_ctx(Other(), dbapi=sqcon)) is False
    finally:
        sqcon.close()
        plain.close()


def test_a_closed_or_missing_connection_is_never_marked_a_disconnect(store):
    """SQLAlchemy's cleanup of a CLOSED connection marked as a disconnect fails an assertion that replaces the
    real error, so the rule says no: for a closed connection and for an error raised while connecting."""
    real = _real_code_11(store)
    sqcon = sqc.connect(":memory:")
    try:
        for exc in (real, MemoryError()):
            for connection in (_conn(sqcon, closed=True), None):
                ctx = _ctx(exc, connection=connection)
                assert damage.discard_poisoned_connection(ctx) is False
                assert ctx.is_disconnect is False and ctx.invalidate_pool_on_disconnect is True
    finally:
        sqcon.close()


def test_a_code_that_is_not_an_integer_is_not_code_11(store):
    """A driver error without an integer ``sqlite_errorcode`` is never matched on its text."""
    bare = sqc.DatabaseError("database disk image is malformed")
    assert not isinstance(getattr(bare, "sqlite_errorcode", None), int)
    assert damage.discard_poisoned_connection(_ctx(bare)) is False
    odd = sqc.DatabaseError("database disk image is malformed")
    odd.sqlite_errorcode = "11"
    assert damage.discard_poisoned_connection(_ctx(odd)) is False


def test_a_context_that_is_not_what_it_expects_never_raises(store):
    assert damage.discard_poisoned_connection(types.SimpleNamespace()) is False
    assert damage.discard_poisoned_connection(None) is False

    class Boom:  # reading the connection raises
        @property
        def connection(self):
            raise RuntimeError("boom")

    assert damage.discard_poisoned_connection(Boom()) is False

    real = _real_code_11(store)

    class Frozen:  # the flag cannot be set: the observer still never replaces the real error
        connection = _conn()
        original_exception = real

        def __setattr__(self, name, value):
            raise AttributeError(name)

    assert damage.discard_poisoned_connection(Frozen()) is False


# -- statements on the driver's own cursor: raised past the observer, so each site goes through the guard ---------


def test_canary_a_raw_cursor_statement_on_a_damaged_page_poisons_the_pool_past_the_observer(store, registry):
    """Why the guard exists: SQLAlchemy raises no ``handle_error`` for a statement run on the driver's cursor, so
    the observer sees nothing, the connection goes back to the pool poisoned and nothing latches."""
    eng, _opened = _engine(store, observed=True, pool_size=1)
    try:
        with eng.connect() as c:
            raw = c.connection.dbapi_connection
            with pytest.raises(sqc.DatabaseError):
                raw.execute(_BAD_RANGE.replace(":lo", "1").replace(":hi", "900")).fetchall()
        assert not registry.latched(FILE_CORPUS), "the observer saw a raw statement: this canary is out of date"
        with pytest.raises(MemoryError):
            _healthy_read(eng)
    finally:
        eng.dispose()


def _raw_bad_read(handle_connection) -> None:
    """A read of the damaged table on the driver's own connection behind ``handle_connection`` (a pooled one)."""
    for lo in range(1, 901, 100):
        handle_connection.execute(_BAD_RANGE.replace(":lo", str(lo)).replace(":hi", str(lo + 99))).fetchall()


def test_the_guard_discards_the_poisoned_connection_and_names_the_file_for_a_sqlalchemy_connection(store, registry):
    eng, opened = _engine(store, observed=True, pool_size=1, url=True)
    try:
        with eng.connect() as c:
            with pytest.raises(sqc.DatabaseError) as info, damage.guard_raw_driver(c):
                _raw_bad_read(c.connection.dbapi_connection)
            assert c.invalidated
            # an invalidated handle is never asked for its driver connection again: that would reconnect it
            assert damage.note_raw_driver_error(c, MemoryError()) is False
            assert len(opened) == 1
        assert damage.is_corruption(info.value), "the guard replaced the caller's error"
        assert registry.latched(FILE_CORPUS)
        assert registry.state()["incident_count"] == 1
        assert _healthy_read(eng) == 3, "the poisoned connection went back to the pool"
        assert len(opened) == 2
    finally:
        eng.dispose()


def test_the_guard_discards_the_poisoned_connection_for_a_pooled_connection(store, registry):
    eng, opened = _engine(store, observed=True, pool_size=1, url=True)
    try:
        raw = eng.raw_connection()
        try:
            with pytest.raises(sqc.DatabaseError), damage.guard_raw_driver(raw, engine=eng):
                _raw_bad_read(raw)
        finally:
            raw.close()
        assert registry.latched(FILE_CORPUS)
        assert _healthy_read(eng) == 3
        assert len(opened) == 2
    finally:
        eng.dispose()


def test_the_guard_files_the_error_against_the_file_the_engine_is_attached_for(store, registry, tmp_path):
    eng, _opened = _engine(store, observed=False, pool_size=1, url=True)
    damage.attach(eng, damage.FILE_LAW)
    try:
        with eng.connect() as c, pytest.raises(sqc.DatabaseError), damage.guard_raw_driver(c):
            _raw_bad_read(c.connection.dbapi_connection)
        assert registry.latched(damage.FILE_LAW) and not registry.latched(FILE_CORPUS)
    finally:
        eng.dispose()


def test_the_guard_names_no_file_for_an_engine_that_is_not_attached_but_still_discards(store, registry):
    eng, opened = _engine(store, observed=False, pool_size=1, url=True)
    try:
        with eng.connect() as c, pytest.raises(sqc.DatabaseError), damage.guard_raw_driver(c):
            _raw_bad_read(c.connection.dbapi_connection)
        assert not registry.latched(FILE_CORPUS), "a file was named that no engine was attached for"
        assert _healthy_read(eng) == 3 and len(opened) == 2
        # an explicit file key is the fallback
        with eng.connect() as c, pytest.raises(sqc.DatabaseError), damage.guard_raw_driver(c, file_key=FILE_CORPUS):
            _raw_bad_read(c.connection.dbapi_connection)
        assert registry.latched(FILE_CORPUS)
    finally:
        eng.dispose()


def test_the_guard_discards_on_an_empty_memory_error_and_latches_nothing(tmp_path, registry):
    path = tmp_path / "ov.db"
    _build_overflow(path, "last")
    eng, opened = _engine(path, observed=True, pool_size=1, url=True)
    try:
        with eng.connect() as c:
            raw = c.connection.dbapi_connection
            raw.execute("SELECT v FROM ov WHERE id = 1").fetchone()  # the silent read: poison for the next statement
            with pytest.raises(MemoryError), damage.guard_raw_driver(c):
                raw.execute("SELECT count(*) FROM small").fetchall()
            assert c.invalidated
        assert _healthy_read(eng) == 3
        assert len(opened) == 2
        assert not registry.latched(FILE_CORPUS) and registry.state()["incident_count"] == 0
    finally:
        eng.dispose()


def test_the_guard_leaves_every_other_error_alone(store, registry):
    eng, opened = _engine(store, observed=True, pool_size=1, url=True)
    try:
        with eng.connect() as c:
            boom = ValueError("not a database error")
            with pytest.raises(ValueError) as info, damage.guard_raw_driver(c):
                raise boom
            assert info.value is boom and not c.invalidated
            with pytest.raises(sqc.OperationalError), damage.guard_raw_driver(c):
                c.connection.dbapi_connection.execute("SELECT * FROM no_such_table")
            assert not c.invalidated
        assert _healthy_read(eng) == 3 and len(opened) == 1
        assert not registry.latched(FILE_CORPUS)
    finally:
        eng.dispose()


def test_the_guard_never_raises_itself(store):
    """Whatever the handle is, the caller's own error is what comes out."""
    real = _real_code_11(store)
    for handle in (None, object(), types.SimpleNamespace(invalidate=None), types.SimpleNamespace(invalidated=True)):
        with pytest.raises(sqc.DatabaseError) as info, damage.guard_raw_driver(handle):
            raise real
        assert info.value is real
    assert damage.note_raw_driver_error(None, None) is False


def test_the_country_code_scan_goes_through_the_guard(store, registry, monkeypatch):
    from src.backup import country_codes

    seen = {}

    def scan(con, *, schema="main"):
        seen["con"] = con
        _raw_bad_read(con)  # the pooled connection answers for the driver's cursor, as the real scan reads it
        raise AssertionError("the damaged page was not read")

    monkeypatch.setattr(country_codes, "scan_country_code_duplicates", scan)
    eng, opened = _engine(store, observed=True, pool_size=1, url=True)
    try:
        with Session(eng) as db:
            with pytest.raises(sqc.DatabaseError) as info:
                country_codes.scan_live_corpus(db)
            assert damage.is_corruption(info.value)
            db.rollback()
        assert registry.latched(FILE_CORPUS)
        assert _healthy_read(eng) == 3, "the scan left a poisoned connection in the pool"
        assert len(opened) == 2
    finally:
        eng.dispose()


def test_the_incremental_vacuum_goes_through_the_guard(tmp_path, registry, monkeypatch):
    from src.database.maintenance import maybe_incremental_vacuum

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    path = tmp_path / "corpus.db"
    _build(path, incremental=True)
    eng, opened = _engine(path, observed=True, pool_size=1, url=True, faulty="incremental_vacuum")
    try:
        report = maybe_incremental_vacuum(eng)
        assert report == {"skipped": "error"}, report
        assert registry.latched(FILE_CORPUS), "the incremental vacuum named no file for a damaged page"
        assert _healthy_read(eng) == 3, "the incremental vacuum left a poisoned connection in the pool"
        assert len(opened) == 2
    finally:
        eng.dispose()


def test_the_wal_checkpoint_goes_through_the_guard(store, registry):
    from src.scheduler import hygiene

    eng, opened = _engine(store, observed=True, pool_size=1, url=True, faulty="wal_checkpoint")
    try:
        errors: list[str] = []
        assert hygiene.checkpoint_wal(engine=eng, force=True, errors=errors) is None
        assert errors == ["DatabaseError"], errors
        assert registry.latched(FILE_CORPUS), "the checkpoint named no file for a damaged page"
        assert _healthy_read(eng) == 3, "the checkpoint left a poisoned connection in the pool"
        assert len(opened) == 2
    finally:
        eng.dispose()
