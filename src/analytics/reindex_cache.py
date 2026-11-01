"""A bigger SQLite page cache for the connection a bulk re-index writes through.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY: a re-index whose rows change rewrites ~80 mention rows per article through the mention table's ten or so indexes. On an
encrypted store each index page that is not in SQLite's own cache is read back and DECRYPTED. Measured (SQLCipher, 100,000 articles,
2.9 GB, 1,000 articles re-indexed, older-engine case, warm OS cache, one run each): 64 MiB cache 40.4 s of mention write, 1,024 MiB
12.8 s (3.2x), wall 99 s -> 78 s (1.27x). The commit got slower (11 s -> 21 s, the dirty pages are written together), which is why the
whole gain is 1.27x and not 3.2x. Limits are in /mnt/project-files/reindex-lane/step1-sqlcipher-100k-2026-11-01.md.

WHY NOT THE POOL: the per-connection default is 64 MiB because the pool's worst case is 72 connections (memory_budget, 4.6 GB on a
16 GB machine). The bigger cache therefore applies to the connections the CALLING THREAD checks out for the duration of one
re-index, and is put back when each is returned to the pool. Other threads' checkouts are never touched.

HOW MUCH: 1/16 of RAM, at most 1,024 MiB, and nothing at all below 4 GiB of RAM or when the RAM cannot be measured (an unmeasured
machine keeps today's behaviour). ``OO_REINDEX_CACHE_MB`` overrides (0 switches it off); an unreadable value falls back to the
default and never to "off". A size not above the cache the connection already has is never applied: this only ever grows it.
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
from collections.abc import Iterator

_LOG = logging.getLogger(__name__)

#: Never above this, whatever the RAM (a measured gain at 1,024 MiB; nothing larger was tried).
MAX_CACHE_MB = 1024
#: Below this much RAM nothing is applied.
MIN_RAM_MB = 4096


def reindex_cache_mb() -> int:
    """The cache in MiB a bulk re-index should use; 0 = leave the connection as it is."""
    raw = os.getenv("OO_REINDEX_CACHE_MB", "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            pass  # a typo must not switch it off; fall through to the default
    from src.config.memory_budget import total_ram_mb

    ram = total_ram_mb()
    if ram is None or ram < MIN_RAM_MB:
        return 0
    return int(min(MAX_CACHE_MB, ram // 16))


def _pragma(dbapi_conn, sql: str):
    cur = dbapi_conn.cursor()
    try:
        cur.execute(sql)
        return cur.fetchall()
    finally:
        cur.close()


@contextlib.contextmanager
def bulk_page_cache(session, size_mb: int | None = None) -> Iterator[int]:
    """Enlarge the page cache of every connection THIS THREAD checks out of ``session``'s engine while the block runs.

    Yields the MiB applied (0 = nothing, the block runs exactly as before). Never raises for a cache problem: a connection that
    refuses the PRAGMA keeps the cache it had, and the failure is logged once."""
    mb = reindex_cache_mb() if size_mb is None else size_mb
    try:
        engine = session.get_bind()
        if mb <= 0 or engine.dialect.name != "sqlite":
            yield 0
            return
        from sqlalchemy import event
    except Exception:  # noqa: BLE001 - no bind (a test double) means nothing to tune
        yield 0
        return

    me = threading.get_ident()
    saved: dict[int, int] = {}  # id(dbapi connection) -> the cache_size it had, in the PRAGMA's own unit
    warned = False

    def _grow(dbapi_conn) -> None:
        nonlocal warned
        try:
            current = int(_pragma(dbapi_conn, "PRAGMA cache_size")[0][0])
            wanted = -mb * 1024  # negative = KiB
            # pages (positive) or KiB (negative): only grow, and only when we can compare like with like
            if current < 0 and current <= wanted:
                return
            saved[id(dbapi_conn)] = current
            _pragma(dbapi_conn, f"PRAGMA cache_size={wanted}")
        except Exception as exc:  # noqa: BLE001
            if not warned:
                warned = True
                _LOG.warning("could not enlarge the re-index page cache: %s", type(exc).__name__)

    def _restore(dbapi_conn) -> None:
        old = saved.pop(id(dbapi_conn), None)
        if old is not None:
            with contextlib.suppress(Exception):
                _pragma(dbapi_conn, f"PRAGMA cache_size={old}")

    def _on_checkout(dbapi_conn, _record, _proxy) -> None:
        if threading.get_ident() == me:
            _grow(dbapi_conn)

    def _on_checkin(dbapi_conn, _record) -> None:
        _restore(dbapi_conn)  # whichever thread returns it: a connection we grew goes back as it was

    event.listen(engine, "checkout", _on_checkout)
    event.listen(engine, "checkin", _on_checkin)
    try:
        # The session may already hold a connection (it is mid-transaction): grow that one now.
        with contextlib.suppress(Exception):
            held = session.connection().connection.dbapi_connection
            if held is not None:
                _grow(held)
        yield mb
    finally:
        event.remove(engine, "checkout", _on_checkout)
        event.remove(engine, "checkin", _on_checkin)
        # The session's own connection is still checked out and the checkin listener is gone: put it back by hand.
        with contextlib.suppress(Exception):
            held = session.connection().connection.dbapi_connection
            if held is not None:
                _restore(held)
