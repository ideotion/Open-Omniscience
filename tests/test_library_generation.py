"""A save that waits out the repair must not land in the file the repair set aside (the deep read of E3, B1).

``dispose_engine()`` closes a pool's IDLE connections; a connection a request has checked out stays open on the OLD inode, and
in WAL mode SQLite does not notice that the name now points elsewhere. Measured by the read: the save waited, reported ok, and
the row was in the damaged file (``<stem>.damaged-*``, which R129 removes thirty days later) while the library read as if it
had never happened. ``library_generation`` stamps every connection of the corpus engine and refuses a statement on a stale one.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from src.database import library_generation as gen


def _store(path: Path) -> None:
    import sqlite3

    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
    con.execute("INSERT INTO notes (body) VALUES ('before')")
    con.commit()
    con.close()


def _bodies(path: Path) -> list[str]:
    import sqlite3

    con = sqlite3.connect(path)
    try:
        return [r[0] for r in con.execute("SELECT body FROM notes ORDER BY id")]
    finally:
        con.close()


@pytest.fixture()
def world(tmp_path):
    live = tmp_path / "live.db"
    _store(live)
    engine = create_engine(f"sqlite:///{live}")
    gen.attach(engine)
    yield tmp_path, live, engine
    engine.dispose()


def _switch(tmp_path: Path, live: Path) -> Path:
    """What the repair's swap does to the names: a second name for the old file, the new file under the live name."""
    new = tmp_path / "new.db"
    _store(new)
    kept = tmp_path / "live.damaged-20261006T000000Z.db"
    os.link(live, kept)
    for suffix in ("-wal", "-shm"):  # the log goes with the file it belongs to; the live names are cleared before the replace
        old = Path(str(live) + suffix)
        if old.exists():
            if suffix == "-wal":
                os.link(old, Path(str(kept) + suffix))
            old.unlink()
    os.replace(new, live)
    return kept


def test_without_the_guard_a_save_through_a_checked_out_connection_lands_in_the_kept_file(tmp_path):
    """The defect, reproduced: the evidence that the guard below is what stops it."""
    live = tmp_path / "live.db"
    _store(live)
    engine = create_engine(f"sqlite:///{live}")  # no guard
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT count(*) FROM notes")).scalar()
            kept = _switch(tmp_path, live)
            engine.dispose()  # what dispose_engine() does: the checked-out connection stays
            conn.execute(text("INSERT INTO notes (body) VALUES ('saved during the repair')"))
            conn.commit()
        assert "saved during the repair" in _bodies(kept), "the defect did not reproduce: the test proves nothing"
        assert "saved during the repair" not in _bodies(live)
    finally:
        engine.dispose()


def test_a_checked_out_connection_from_before_the_switch_is_refused_and_the_save_lands_nowhere(world):
    tmp_path, live, engine = world
    with engine.connect() as conn:
        conn.execute(text("SELECT count(*) FROM notes")).scalar()
        kept = _switch(tmp_path, live)
        engine.dispose()
        gen.bump()
        with pytest.raises(gen.StaleLibraryError):
            conn.execute(text("INSERT INTO notes (body) VALUES ('saved during the repair')"))
    assert "saved during the repair" not in _bodies(kept) and "saved during the repair" not in _bodies(live)
    # the connection is gone for good, and a new one reads the NEW file and writes to it
    with engine.begin() as fresh:
        fresh.execute(text("INSERT INTO notes (body) VALUES ('saved after')"))
    assert _bodies(live) == ["before", "saved after"] and _bodies(kept) == ["before"]


def test_a_read_on_a_stale_connection_is_refused_too_and_a_connection_made_after_the_bump_is_not(world):
    tmp_path, live, engine = world
    with engine.connect() as conn:
        conn.execute(text("SELECT 1")).scalar()
        _switch(tmp_path, live)
        engine.dispose()
        gen.bump()
        with pytest.raises(gen.StaleLibraryError):
            conn.execute(text("SELECT count(*) FROM notes"))
    with engine.connect() as fresh:
        assert fresh.execute(text("SELECT count(*) FROM notes")).scalar() == 1
        assert fresh.execute(text("SELECT count(*) FROM notes")).scalar() == 1


def test_the_stale_connection_never_returns_to_the_pool(world):
    tmp_path, live, engine = world
    conn = engine.connect()
    conn.execute(text("SELECT 1")).scalar()
    _switch(tmp_path, live)
    gen.bump()  # the pool was not disposed here: its idle connections would be stale too
    with pytest.raises(gen.StaleLibraryError):
        conn.execute(text("SELECT 1"))
    conn.close()
    with engine.connect() as again:
        assert again.execute(text("SELECT count(*) FROM notes")).scalar() == 1, "a stale connection was handed out again"


def test_the_session_engine_is_stamped_and_the_swap_bumps_the_counter():
    src = Path("src/database/session.py").read_text(encoding="utf-8")
    assert "_library_generation.attach(engine)" in src, "the corpus engine's connections are not stamped"
    repair_src = Path("src/database/repair.py").read_text(encoding="utf-8")
    swap = repair_src[repair_src.index("def _swap("):repair_src.index("def _identity(")]
    assert swap.index("_replace_live_corpus(finished, target)") < swap.index("library_generation.bump()") < swap.index("init_db()"), (
        "the counter must move AFTER the replace (a connection made before it opens the old file) and BEFORE the engine is used again"
    )
