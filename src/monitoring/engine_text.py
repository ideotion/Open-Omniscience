"""An exception's text, with the database passphrase taken out, for records that are shown or saved.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHERE IT RUNS: the places in the analytics code that keep an engine's failure text in a status
the interface reads or a diagnostics member (the write-rate reading, the re-index job's error,
the keyword cleanup's skip record in ``store.py``, the re-index backlog's reason in ``merge.py``,
the stoplist recompute's record). Those sites also log the cleaned text with ``%s`` and never
with ``exc_info``: the root error handler writes a traceback's last lines to a file that rides
the diagnostics bundle, and a traceback ends with the engine's own words. Those words can carry
the statement the engine failed on (SQLAlchemy puts ``[SQL: ...]`` in an exception's text). No
statement there is built from the passphrase and the key is applied through the driver, not
through SQLAlchemy, so this is the net beneath that, at the place the text is made.

IT IS ONE CALL TO THE SHARED SCRUB. :func:`engine_text` is
:func:`src.monitoring.secret_scrub.exception_text` with the class left off by default (a record that has
its own field for the class), or written once in front (``typed=True``: ``Name: its words``, which is
what a log line and a skip record want; a site that wrote the class itself beside the call would print
it twice when the text is withheld, because the withheld answer is already ``Name: its text is withheld``): every passphrase this process holds (the
session's, ``OO_DB_PASSPHRASE``, ``OO_KEY_PASSPHRASE``) is taken out of the WHOLE text in every
shape the code and its drivers write it in (as typed, SQL-quoted, ``repr``, JSON, the ``repr``
of its bytes, each carried up to three times), and any cut is made AFTERWARDS (a cut that fell
inside the passphrase would keep the part it kept, which a scrub of the cut text cannot see). It
fails CLOSED: a text that could not be checked, a passphrase too short to take out of a text, or
a ``UnicodeError`` (whose words name the character and its offset) is the exception's class
and none of its words. Only :func:`engine_text` is meant to be called from outside.

THE IMPORT IS INSIDE THE FUNCTION, on purpose: this module is loaded by an index pass, and the closure
test of the index engine's identity (``tests/test_index_engine_stamp.py``) fails for any module a pass
loads that is neither an engine module nor listed in ``NOT_OUTPUT_AFFECTING``
(``src/analytics/engine_identity.py``). The scrub is needed only on a failure, so it is loaded only
then and that registry stays as it was (the stamp itself hashes only the engine modules).

WHAT IT DOES NOT COVER: a key handed to ``connect(key=...)`` in a restore or a backup, which is
not held in this process and so is not a needle here (those routes hand it to the scrub).
"""

from __future__ import annotations


def engine_text(exc: BaseException, limit: int | None = None, *, typed: bool = False) -> str:
    """The words of ``exc`` (``typed``: ``Name: the words``) with every held passphrase out of the whole text,
    then cut to ``limit``."""
    try:
        from src.monitoring.secret_scrub import record_text

        return record_text(exc, limit=limit, typed=typed)
    except Exception:  # noqa: BLE001 - the scrub could not be loaded: the class is all that is written
        out = f"<{type(exc).__name__}: text withheld, it could not be checked for the passphrase>"
        return out if limit is None else out[:limit]


def is_pool_timeout(exc: BaseException) -> bool:
    """``True`` when ``exc``, or any exception it chains, is SQLAlchemy's connection-pool timeout (``QueuePool limit ... connection
    timed out``). Judged by class, never by words, because the words of a driver error are not kept."""
    try:
        from sqlalchemy.exc import TimeoutError as PoolTimeout

        seen: set[int] = set()
        link: BaseException | None = exc
        while link is not None and id(link) not in seen:
            if isinstance(link, PoolTimeout):
                return True
            seen.add(id(link))
            link = link.__cause__ or link.__context__
    except Exception:  # noqa: BLE001 - a chain that cannot be read is not a timeout
        return False
    return False
