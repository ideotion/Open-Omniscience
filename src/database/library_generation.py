"""WHICH FILE the library's name pointed at when a connection was made (the repair's swap, E3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. The repair puts a new file under the library's name and keeps the damaged one under a second name
(``repair._swap``). ``dispose_engine()`` closes the pool's IDLE connections; a connection a request has CHECKED OUT stays
open on the OLD inode, and in WAL mode SQLite does not notice that its file has moved (the check that does, "the database
file has been moved", runs only for rollback-journal databases). The deep read of E3 ran it: a form loads, waits on the
write gate for the whole repair, then saves, and the save commits into the damaged file (now ``<stem>.damaged-*``, which
R129 removes thirty days later) with no error, while the library reads as if the save never happened.

WHAT IT DOES. A counter, :func:`bump` after the swap puts the new file in place, and a stamp on every connection the corpus
engine makes (:func:`attach`): a statement on a connection made under an older generation raises
:class:`StaleLibraryError` BEFORE it runs, and the connection is invalidated so the pool never hands it out again. A save
that was waiting out the repair therefore FAILS LOUDLY and is made again on the new file, instead of landing in a file
nobody reads. It reads, never writes: the cost is one dict read and one integer comparison per statement.

WHAT IT DOES NOT COVER. Connections the app opens for itself and does not take from this engine's pool (a backup's raw
drivers, the read-snapshot engine's short-lived read connections) are not stamped; they are opened for one piece of work
and closed, and a read from the old file by one of them cannot lose a write.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

_LOG = logging.getLogger(__name__)

_KEY = "oo_library_generation"
_LOCK = threading.Lock()
_GENERATION = 0


class StaleLibraryError(RuntimeError):
    """A statement was about to run on a connection to a library file that has since been replaced (a repair switched to a new
    file). The statement did not run; the work is to be done again."""


def current() -> int:
    return _GENERATION


def bump() -> int:
    """The library's name now points at a different file: every connection made before this call is stale."""
    global _GENERATION
    with _LOCK:
        _GENERATION += 1
        return _GENERATION


def attach(engine: Any) -> None:
    """Stamp the connections of ``engine`` and refuse statements on stale ones. One call per engine."""
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _stamp(_dbapi_connection, connection_record) -> None:  # noqa: ANN001 - SQLAlchemy's pool record
        connection_record.info[_KEY] = _GENERATION

    @event.listens_for(engine, "before_cursor_execute")
    def _refuse_stale(conn, _cursor, _statement, _parameters, _context, _executemany) -> None:  # noqa: ANN001
        stamp = conn.connection.info.get(_KEY)
        if stamp is not None and stamp != _GENERATION:
            try:
                conn.invalidate()  # never returns to the pool: its file is not the library any more
            except Exception:  # noqa: BLE001 - the refusal below is what matters
                _LOG.debug("library generation: could not invalidate a stale connection (it is refused anyway)")
            raise StaleLibraryError(
                "the library file was replaced by a repair while this was open, so the statement was not run; do it again"
            )
