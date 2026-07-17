"""Resilient writes against transient SQLite ``database is locked`` contention.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The store is single-writer by design (one SQLite/SQLCipher file). WAL lets
readers pass a writer, but two *writers* still serialise, and a long collection
pass can hold the writer longer than ``PRAGMA busy_timeout`` (30 s) -- a
commodity/import write that loses the race then raises ``OperationalError:
database is locked`` and, historically, **discarded data it had already fetched
over the network** (field log 2026-06-13: copper/aluminum/nickel/zinc fetched OK
then failed to store).

This module is the immediate, surgical safety net: a unit-of-work retry that
absorbs the transient lock with exponential backoff + jitter. It is NOT a
substitute for the single-writer queue (the proper fix that removes the
contention entirely); it is the belt-and-braces so no fetched data is ever lost
to a lock in the meantime, and it stays useful afterwards for any direct writer.

The contract: the work callable must be **idempotent** -- on a locked error the
session is rolled back (which expunges pending objects), so the work is re-run
from scratch and must re-query whatever state it needs. ``import_points`` already
satisfies this (it recomputes the existing-dates set and adds only new rows).
"""

from __future__ import annotations

import functools
import logging
import random
import time
from collections.abc import Callable, Iterator

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_LOCKED_MSGS = ("database is locked", "database is busy")


@functools.lru_cache(maxsize=1)
def _db_operational_error_types() -> tuple[type, ...]:
    """The OperationalError classes a locked/busy write can surface as. ``sqlite3`` is stdlib
    (always present); ``sqlcipher3`` is the ENCRYPTED store's driver -- the field case where a
    RAW locked error is NOT wrapped as ``sqlalchemy.exc.OperationalError`` -- and may be absent
    in a core install (guarded). Cached: the imports are resolved once."""
    import sqlite3

    types: list[type] = [OperationalError, sqlite3.OperationalError]
    try:
        from sqlcipher3.dbapi2 import OperationalError as _SqlcipherOperationalError
        types.append(_SqlcipherOperationalError)
    except Exception:  # noqa: BLE001 - sqlcipher3 absent in a core install -> stdlib path only
        pass
    return tuple(types)


def _exc_chain(exc: BaseException) -> Iterator[BaseException]:
    """``exc`` and its wrapped ``__cause__``/``__context__`` (bounded, cycle-safe) -- a raw
    driver error is often the CAUSE/CONTEXT of a higher-level wrapper."""
    seen: set[int] = set()
    stack: list[BaseException | None] = [exc]
    while stack:
        e = stack.pop()
        if e is None or id(e) in seen:
            continue
        seen.add(id(e))
        yield e
        stack.append(e.__cause__)
        stack.append(e.__context__)

# Defaults: 5 attempts with backoff 0.2, 0.4, 0.8, 1.6 s (+jitter) on top of the
# connection's own 30 s busy_timeout -- generous enough to ride out a long
# collection pass's writer hold, bounded enough never to hang a request.
DEFAULT_ATTEMPTS = 5
DEFAULT_BASE_DELAY_S = 0.2
DEFAULT_MAX_DELAY_S = 4.0


def is_locked_error(exc: BaseException) -> bool:
    """True iff ``exc`` (or a wrapped cause/context) is an SQLite/SQLCipher 'database is
    locked'/'busy' condition.

    Narrow on purpose: only lock CONTENTION is retryable -- a schema error, a constraint
    violation, or a disk-full must surface immediately, never loop.

    THE ENCRYPTED-STORE FIX (field log 2026-07-14, 297 fetched articles left UNINDEXED): on a
    ``sqlcipher3`` store a locked write can surface as a RAW ``sqlite3``/``sqlcipher3``
    ``OperationalError`` that SQLAlchemy does NOT wrap as ``sqlalchemy.exc.OperationalError``,
    so the old ``isinstance(exc, OperationalError)`` returned ``False``, the backoff never
    engaged, and the ``ingest.batch`` redo path never fired -- the exact data loss this module
    exists to prevent. We now match the locked/busy MESSAGE on the DB-layer OperationalError
    classes (SQLAlchemy's + stdlib ``sqlite3`` + ``sqlcipher3``) across the cause/context chain.
    Still narrow BY CONSTRUCTION: the message is only honoured on an actual DB OperationalError
    class, so an ``IntegrityError`` (or any non-OperationalError that merely mentions the words)
    is never treated as locked -- it still takes the dedup/redo-per-row path, not the backoff.
    """
    types = _db_operational_error_types()
    for e in _exc_chain(exc):
        if isinstance(e, types) and any(m in str(e).lower() for m in _LOCKED_MSGS):
            return True
    return False


@functools.lru_cache(maxsize=1)
def _db_integrity_error_types() -> tuple[type, ...]:
    """The IntegrityError classes a UNIQUE/FK/NOT-NULL violation can surface as.

    Same cross-driver divergence as :func:`is_locked_error`: ``sqlcipher3`` (the
    ENCRYPTED store's driver -- the default) defines its OWN ``IntegrityError``
    class, not a subclass of stdlib ``sqlite3.IntegrityError`` or
    ``sqlalchemy.exc.IntegrityError``, so a narrow
    ``except sqlalchemy.exc.IntegrityError`` silently never matches on the
    encrypted store. This recurred independently in ``src/backup/merge.py``
    (``_db_integrity_error_types``, field bug 2026-07-16) and
    ``src/ingest/email.py`` (``_is_integrity_error``, 2026-07-17) before this
    shared, importable version was added — new call sites should use THIS one
    rather than writing a fifth copy. Guarded: sqlcipher3 may be absent in a
    core install; cached since the imports are resolved once.
    """
    import sqlite3

    from sqlalchemy.exc import IntegrityError

    types: list[type] = [IntegrityError, sqlite3.IntegrityError]
    try:
        from sqlcipher3.dbapi2 import IntegrityError as _SqlcipherIntegrityError

        types.append(_SqlcipherIntegrityError)
    except Exception:  # noqa: BLE001 - sqlcipher3 absent in a core install -> stdlib path only
        pass
    return tuple(types)


def is_integrity_error(exc: BaseException) -> bool:
    """True iff ``exc`` (or a wrapped cause/context) is a UNIQUE/FK/NOT-NULL/CHECK
    constraint violation, across the sqlalchemy/sqlite3/sqlcipher3 cross-driver
    divergence (see :func:`_db_integrity_error_types`). Unlike :func:`is_locked_error`
    no message substring check is needed: every member of this type tuple IS,
    by construction, a constraint violation.
    """
    types = _db_integrity_error_types()
    return any(isinstance(e, types) for e in _exc_chain(exc))


def run_write_with_retry[T](
    work: Callable[[], T],
    *,
    session: Session,
    attempts: int = DEFAULT_ATTEMPTS,
    base_delay_s: float = DEFAULT_BASE_DELAY_S,
    max_delay_s: float = DEFAULT_MAX_DELAY_S,
    label: str = "write",
) -> T:
    """Run ``work`` (a unit of work ending in ``session.commit()``), retrying on
    transient ``database is locked`` with exponential backoff + jitter.

    Re-raises immediately on any non-lock error and re-raises the last lock error
    if every attempt is exhausted. ``work`` MUST be idempotent (see module docs).
    """
    last_exc: BaseException | None = None
    for attempt in range(attempts):
        try:
            return work()
        # NB: catch broadly, then let is_locked_error be the PRECISE discriminator. On an
        # encrypted (sqlcipher3) store a locked write can surface as a RAW driver error that is
        # NOT a sqlalchemy.exc.OperationalError, so a narrow `except OperationalError` would let
        # it escape the retry entirely (the same data loss is_locked_error was just fixed for).
        # A non-lock error is re-raised immediately below, so behaviour for every other exception
        # is unchanged (it still propagates to the caller).
        except Exception as exc:  # noqa: BLE001 - is_locked_error gates it; non-locks re-raise
            if not is_locked_error(exc):
                raise
            last_exc = exc
            # Roll back so the failed transaction's pending objects are cleared
            # before the work re-runs from scratch on the next attempt.
            try:
                session.rollback()
            except Exception:  # noqa: BLE001 - rollback failure must not mask the lock
                logger.debug("rollback after locked %s failed; continuing to retry", label)
            if attempt == attempts - 1:
                break
            delay = min(max_delay_s, base_delay_s * (2**attempt)) + random.uniform(
                0, base_delay_s
            )
            logger.warning(
                "%s hit 'database is locked' (attempt %d/%d); retrying in %.2fs",
                label,
                attempt + 1,
                attempts,
                delay,
            )
            time.sleep(delay)
    assert last_exc is not None  # only reached after a locked error broke the loop
    logger.error("%s still locked after %d attempts; giving up", label, attempts)
    raise last_exc
