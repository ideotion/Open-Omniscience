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
  * a session in a transaction on the discarded connection rolls back and works again;
  * only code 11 from SQLCipher is reclassified: a ``MemoryError``, a wrong-key error (26) and a plain-SQLite
    corruption error are not.
"""
from __future__ import annotations

import random
import sqlite3
import types
from pathlib import Path

import pytest

pytest.importorskip("sqlcipher3")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.exc import DBAPIError  # noqa: E402
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


def _build(path: Path) -> list[int]:
    """An encrypted store with a small table and a wide one; one page of the wide one is overwritten. Returns the
    ids of ``big``."""
    con = connect(path, key=_KEY, create_encrypted=True, check_same_thread=False)
    con.execute("CREATE TABLE small (a INTEGER)")
    con.execute("INSERT INTO small VALUES (1), (2), (3)")
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


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "corpus.db"
    _build(path)
    return path


def _engine(path: Path, *, observed: bool, pool_size: int = 3):
    opened: list[object] = []

    def creator():
        conn = connect(path, key=_KEY, check_same_thread=False)
        opened.append(conn)
        return conn

    eng = create_engine("sqlite://", creator=creator, poolclass=QueuePool, pool_size=pool_size, max_overflow=0)
    if observed:
        damage.attach(eng, FILE_CORPUS)
    return eng, opened


def _first_bad_range(eng) -> tuple[int, int]:
    """The first range of 100 ids whose read raises corruption (a damaged leaf is invisible to a count)."""
    for lo in range(1, 901, 100):
        try:
            with eng.connect() as c:
                c.execute(text(_BAD_RANGE), {"lo": lo, "hi": lo + 99}).fetchall()
        except _DB_ERRORS as exc:
            assert damage.is_corruption(exc), exc
            return lo, lo + 99
    pytest.fail("no range of the wide table failed: the overwrite missed it")


def _healthy_read(eng) -> int:
    with eng.connect() as c:
        return c.execute(text("SELECT count(*) FROM small")).scalar_one()


@pytest.fixture
def registry(tmp_path):
    damage.registry._reset_for_tests(path_fn=lambda: tmp_path / "database-damage.json")
    return damage.registry


def test_canary_without_the_observer_the_pooled_connection_is_poisoned(store):
    """The driver fact the fix answers. If this stops failing, SQLCipher stopped poisoning and the fix is moot."""
    eng, _opened = _engine(store, observed=False, pool_size=1)
    lo, hi = _first_bad_range(eng)
    assert (lo, hi) is not None
    with pytest.raises(MemoryError):
        _healthy_read(eng)
    with pytest.raises(MemoryError):
        _healthy_read(eng)  # and it stays poisoned: the same pooled connection comes back every time


def test_with_the_observer_the_next_read_is_answered_and_the_error_is_still_the_corruption_error(store, registry):
    eng, _opened = _engine(store, observed=True, pool_size=1)
    try:
        with eng.connect() as c:
            lo = None
            for start in range(1, 901, 100):
                try:
                    c.execute(text(_BAD_RANGE), {"lo": start, "hi": start + 99}).fetchall()
                except _DB_ERRORS as exc:
                    lo = start
                    assert damage.is_corruption(exc), "the error that reaches the caller is no longer the corruption error"
                    break
        assert lo is not None
        assert _healthy_read(eng) == 3
        assert _healthy_read(eng) == 3
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
        assert len(opened) == 3
        before = {id(o) for o in opened}
        _first_bad_range(eng)
        for _ in range(6):
            assert _healthy_read(eng) == 3
        assert len(opened) == 4, f"{len(opened)} connections were opened for one bad read: the whole pool was replaced"
        assert len({id(o) for o in opened} & before) == 3, "a healthy pooled connection was replaced"
    finally:
        eng.dispose()


def test_a_repeated_bad_read_costs_one_reconnect_each_and_the_pool_does_not_grow(store, registry):
    eng, opened = _engine(store, observed=True, pool_size=2)
    try:
        for _ in range(5):
            _first_bad_range(eng)
            assert _healthy_read(eng) == 3
        # one per bad range found at the start of a scan, at most one per failed read, never a growing pool
        assert eng.pool.checkedout() == 0
        assert len(opened) <= 2 + 5 * 2
    finally:
        eng.dispose()


def test_a_session_that_was_in_a_transaction_on_the_discarded_connection_rolls_back_and_works_again(store, registry):
    eng, _opened = _engine(store, observed=True, pool_size=1)
    try:
        with Session(eng) as s:
            assert s.execute(text("SELECT count(*) FROM small")).scalar_one() == 3
            failed = False
            for start in range(1, 901, 100):
                try:
                    s.execute(text(_BAD_RANGE), {"lo": start, "hi": start + 99}).fetchall()
                except _DB_ERRORS:
                    failed = True
                    break
            assert failed
            s.rollback()
            assert s.execute(text("SELECT count(*) FROM small")).scalar_one() == 3
    finally:
        eng.dispose()


def _ctx(exc: BaseException):
    return types.SimpleNamespace(original_exception=exc, is_disconnect=False, invalidate_pool_on_disconnect=True)


def test_only_code_11_from_the_sqlcipher_driver_is_reclassified(store, tmp_path):
    # a real code-11 error from SQLCipher: reclassified, for this one connection only
    con = connect(store, key=_KEY, check_same_thread=False)
    real: BaseException | None = None
    for start in range(1, 901, 100):
        try:
            con.execute(_BAD_RANGE.replace(":lo", str(start)).replace(":hi", str(start + 99))).fetchall()
        except sqc.DatabaseError as exc:
            real = exc
            break
    con.close()
    assert real is not None and getattr(real, "sqlite_errorcode", None) == 11
    ctx = _ctx(real)
    assert damage.discard_poisoned_connection(ctx) is True
    assert ctx.is_disconnect is True and ctx.invalidate_pool_on_disconnect is False

    # a real out-of-memory (or the poison's own text) is never a reason to reconnect
    for other in (MemoryError(), MemoryError("out of memory"), RuntimeError("database disk image is malformed")):
        ctx = _ctx(other)
        assert damage.discard_poisoned_connection(ctx) is False
        assert ctx.is_disconnect is False and ctx.invalidate_pool_on_disconnect is True

    # a wrong key (SQLITE_NOTADB, 26) is a real SQLCipher error and is not corruption
    wrong = None
    try:
        c = sqc.connect(str(store))
        c.execute("PRAGMA key = 'not the key'")
        c.execute("SELECT count(*) FROM sqlite_master").fetchall()
    except sqc.DatabaseError as exc:
        wrong = exc
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
    ctx = _ctx(err)
    assert damage.discard_poisoned_connection(ctx) is False and ctx.is_disconnect is False


def test_a_context_that_is_not_what_it_expects_never_raises():
    assert damage.discard_poisoned_connection(types.SimpleNamespace()) is False
    assert damage.discard_poisoned_connection(None) is False
