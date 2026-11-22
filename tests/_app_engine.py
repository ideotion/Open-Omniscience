"""A test's own SQLite engine, opened the way the app opens its store (row 285).

A test that builds its engine with a bare ``create_engine`` gets SQLite's defaults, so ``foreign_keys`` is OFF and an
``ON DELETE CASCADE`` never fires: a delete the app cascades leaves child rows behind in the test, and a test that
asserts on what remains is then checking a database the app never runs. ``app_sqlite_engine`` attaches the app's own
connect listener (``src.database.session._sqlite_pragmas``: WAL, foreign keys, busy timeout, cache and journal ceiling)
to a file of the test's own, never the app's live store."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

# The busy timeout the app's connect listener sets (src.database.session._sqlite_pragmas). Pinned against the app by
# tests/test_bare_test_engines_ratchet.py, so the two cannot drift.
APP_BUSY_TIMEOUT_MS = 30000


def app_sqlite_engine(
    path: Path | str = ":memory:", *, busy_timeout_ms: int = APP_BUSY_TIMEOUT_MS, **kwargs: Any
) -> Engine:
    """An engine on ``path`` (a file of the test's own, or ``":memory:"``) with the app's connection pragmas.

    Keyword arguments go to ``create_engine`` unchanged (``poolclass``, ``connect_args``, ``creator`` ...), so a test
    converted from a bare ``create_engine`` keeps its pool and connection settings (row 288).

    ``busy_timeout_ms`` is the one pragma a test may change, and only by naming it: a test that provokes a busy
    database on purpose passes a short value, and every other app pragma still applies unchanged."""
    from src.database import session as app_session

    url = "sqlite://" if str(path) == ":memory:" else f"sqlite:///{path}"
    kwargs.setdefault("future", True)
    engine = create_engine(url, **kwargs)
    event.listen(engine, "connect", app_session._sqlite_pragmas)
    if busy_timeout_ms != APP_BUSY_TIMEOUT_MS:
        timeout = int(busy_timeout_ms)

        def _busy_timeout(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute(f"PRAGMA busy_timeout={timeout}")
            finally:
                cursor.close()

        event.listen(engine, "connect", _busy_timeout)
    return engine
