"""
Behavioral tests for the database session layer (Action Plan Phase 1.1).

These pin three properties:
  1. Importing the models/session modules has NO side effects -- no DB file is
     created, no background thread is started. (Regression guard for P0-11/B8.)
  2. init_db() creates the schema, and SQLite runs in WAL mode with foreign keys.
  3. A session acquired the way the app acquires one (the get_db dependency /
     session_scope) can write and read a row and is closed afterwards.
"""

from __future__ import annotations

import subprocess
import sys

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import sessionmaker

from src.database import session as session_module
from src.database.models import Article, Base, Source


def _fresh_engine(tmp_path):
    """An isolated engine on a temp SQLite file, with the same PRAGMAs as prod."""
    db = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{db}", future=True, connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _rec):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    return engine


def test_import_has_no_side_effects(tmp_path):
    """Importing models must not create a DB file or spawn a monitoring thread."""
    # Audit finding 2026-07-17: the temp dir used to be created INSIDE the subprocess
    # via tempfile.mkdtemp() -- its path never left the subprocess, so neither it nor
    # the parent test could ever clean it up (a leak per test run). Create it in the
    # PARENT via pytest's own tmp_path fixture (auto-cleaned on pytest's retention
    # policy) and pass the path INTO the subprocess instead.
    data_dir = str(tmp_path)
    code = (
        "import os, threading, sys;"
        f"os.environ['OO_DATA_DIR'] = {data_dir!r};"
        "n0 = threading.active_count();"
        "import src.database.models as m;"
        "n1 = threading.active_count();"
        "db = os.path.join(os.environ['OO_DATA_DIR'], 'open_omniscience.db');"
        "sys.exit(0 if (n0 == n1 and not os.path.exists(db)) else 1)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True)
    assert result.returncode == 0, (
        "importing models had a side effect (thread started or DB file created):\n"
        f"{result.stdout.decode()}{result.stderr.decode()}"
    )


def test_init_db_enables_wal_and_foreign_keys():
    """The real engine should run SQLite in WAL with FK enforcement after init_db."""
    session_module.init_db()
    insp = inspect(session_module.engine)
    assert "articles" in insp.get_table_names()
    from sqlalchemy import text

    with session_module.engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar().lower() == "wal"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_session_write_read_roundtrip(tmp_path):
    """A scoped session writes and reads a row, then is closed cleanly."""
    engine = _fresh_engine(tmp_path)
    TestSession = sessionmaker(bind=engine, future=True)

    # write
    with TestSession() as s:
        src = Source(name="Example News", domain="example.com")
        s.add(src)
        s.flush()  # assign src.id
        art = Article(
            url="https://example.com/a",
            canonical_url="https://example.com/a",
            source_id=src.id,
            content="hello world",
            hash="0" * 64,
        )
        s.add(art)
        s.commit()

    # read back in a separate session
    with TestSession() as s:
        rows = s.query(Article).all()
        assert len(rows) == 1
        assert rows[0].content == "hello world"
        assert rows[0].canonical_url == "https://example.com/a"


def test_get_db_dependency_yields_and_closes():
    """get_db yields exactly one usable session and closes it on generator exit."""
    gen = session_module.get_db()
    db = next(gen)
    assert db.is_active
    # exhausting the generator triggers the finally: close
    closed = False
    try:
        next(gen)
    except StopIteration:
        closed = True
    assert closed
