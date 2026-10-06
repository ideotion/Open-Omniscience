"""An exception's text, with the database passphrase taken out, for records that are shown or saved.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHERE IT RUNS: the places in the analytics code that keep an engine's failure text in a status
the interface reads or a diagnostics member (the write-rate reading, the re-index job's error,
the keyword cleanup's skip record in ``store.py``, the re-index backlog's reason in ``merge.py``).
Those sites also log the cleaned text with ``%s`` and never with ``exc_info``: the root error
handler writes a traceback's last lines to a file that rides the diagnostics bundle, and a
traceback ends with the engine's own words. The
engine's own words can carry the statement it failed on (SQLAlchemy puts ``[SQL: ...]`` in an
exception's text). No statement there is built from the passphrase and the key is applied through
the driver, not through SQLAlchemy, so this is the net beneath that, at the place the text is made.

The passphrase is taken out of the WHOLE text and any cut is made afterwards (a cut that fell inside
the passphrase would leave the part it kept, which a scrub of the cut text cannot see). It fails
CLOSED: when the text could not be checked, a marker naming the exception class stands in for it.
Exact match through :func:`src.monitoring.secret_scrub.scrub_text`, the shared helper.

WHAT IT DOES NOT COVER: a key handed to ``connect(key=...)`` in a restore or a backup, which is
not held in this process and so is not a needle here. Only :func:`engine_text` is meant to be
called from outside: the private reader below answers ``None`` when it could not check, and a
caller that wrote ``without(text) or text`` would fail OPEN.
"""

from __future__ import annotations

import os


def _without_the_passphrase(text: str) -> str | None:
    """``text`` with the passphrase this process holds, and the one in its environment, taken out;
    ``None`` when that could not be done (the caller then withholds the text)."""
    try:
        from src.database.connect import get_passphrase
        from src.monitoring.secret_scrub import scrub_text

        for needle in dict.fromkeys(filter(None, (get_passphrase(), os.environ.get("OO_DB_PASSPHRASE")))):
            text = scrub_text(text, needle)
    except Exception:  # noqa: BLE001 - failing CLOSED: the caller withholds what it could not scrub
        return None
    return text


def engine_text(exc: BaseException, limit: int | None = None) -> str:
    """``str(exc)`` with the passphrase out of the whole text, then cut to ``limit`` characters."""
    try:
        text = str(exc)
    except Exception:  # noqa: BLE001
        return f"<{type(exc).__name__}: unrenderable>"
    clean = _without_the_passphrase(text)
    if clean is None:
        return f"<{type(exc).__name__}: text withheld, it could not be checked for the passphrase>"
    return clean if limit is None else clean[:limit]
