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

import logging
import random
import time
from collections.abc import Callable

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Defaults: 5 attempts with backoff 0.2, 0.4, 0.8, 1.6 s (+jitter) on top of the
# connection's own 30 s busy_timeout -- generous enough to ride out a long
# collection pass's writer hold, bounded enough never to hang a request.
DEFAULT_ATTEMPTS = 5
DEFAULT_BASE_DELAY_S = 0.2
DEFAULT_MAX_DELAY_S = 4.0


def is_locked_error(exc: BaseException) -> bool:
    """True iff ``exc`` is an SQLite 'database is locked'/'busy' OperationalError.

    Narrow on purpose: only lock contention is retryable. A schema error, a
    constraint violation, or a disk-full must surface immediately, never loop.
    """
    if not isinstance(exc, OperationalError):
        return False
    msg = str(exc).lower()
    return "database is locked" in msg or "database is busy" in msg


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
    last_exc: OperationalError | None = None
    for attempt in range(attempts):
        try:
            return work()
        except OperationalError as exc:
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
