"""A test's own SQLite engine, opened the way the app opens its store (row 285).

A test that builds its engine with a bare ``create_engine`` gets SQLite's defaults, so ``foreign_keys`` is OFF and an
``ON DELETE CASCADE`` never fires: a delete the app cascades leaves child rows behind in the test, and a test that
asserts on what remains is then checking a database the app never runs. ``app_sqlite_engine`` attaches the app's own
connect listener (``src.database.session._sqlite_pragmas``: WAL, foreign keys, busy timeout, cache and journal ceiling)
to a file of the test's own, never the app's live store."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine


def app_sqlite_engine(path: Path | str) -> Engine:
    """An engine on ``path`` (a file of the test's own) with the app's connection pragmas."""
    from src.database import session as app_session

    engine = create_engine(f"sqlite:///{path}", future=True)
    event.listen(engine, "connect", app_session._sqlite_pragmas)
    return engine
