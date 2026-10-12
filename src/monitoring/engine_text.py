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
:func:`src.monitoring.secret_scrub.exception_text` with the class left off (the sites name it
beside the text, or in the record's own field): every passphrase this process holds (the
session's, ``OO_DB_PASSPHRASE``, ``OO_KEY_PASSPHRASE``) is taken out of the WHOLE text in every
shape the code and its drivers write it in (as typed, SQL-quoted, ``repr``, JSON, the ``repr``
of its bytes, each carried up to three times), and any cut is made AFTERWARDS (a cut that fell
inside the passphrase would keep the part it kept, which a scrub of the cut text cannot see). It
fails CLOSED: a text that could not be checked, a passphrase too short to take out of a text, or
a ``UnicodeError`` (whose words name the character and its offset) is the exception's class
and none of its words. Only :func:`engine_text` is meant to be called from outside.

THE IMPORT IS INSIDE THE FUNCTION, on purpose: this module is loaded by an index pass, and the
index engine's stamp (``src/analytics/engine_identity.py``) lists every module a pass loads. The
scrub is needed only on a failure, so it is loaded only then and the stamp stays as it was.

WHAT IT DOES NOT COVER: a key handed to ``connect(key=...)`` in a restore or a backup, which is
not held in this process and so is not a needle here (those routes hand it to the scrub).
"""

from __future__ import annotations


def engine_text(exc: BaseException, limit: int | None = None) -> str:
    """The words of ``exc`` with every held passphrase out of the whole text, then cut to ``limit``."""
    try:
        from src.monitoring.secret_scrub import exception_text

        return exception_text(exc, limit=limit, typed=False)
    except Exception:  # noqa: BLE001 - the scrub could not be loaded: the class is all that is written
        return f"<{type(exc).__name__}: text withheld, it could not be checked for the passphrase>"
