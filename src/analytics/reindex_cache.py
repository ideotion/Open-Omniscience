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
import weakref
from collections.abc import Iterator
from typing import Any

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


class _EngineHooks:
    """The two pool listeners of ONE engine, registered once and left in place (removing a listener from inside a checkin dispatch
    mutates the list being iterated), plus what they need: which threads are inside a block, and which connections they grew."""

    def __init__(self, engine) -> None:
        self.lock = threading.Lock()
        self.growers: dict[int, list[int]] = {}  # thread ident -> [MiB, nesting depth]
        self.saved: dict[Any, int] = {}  # connection RECORD -> the cache_size it had (it outlives an invalidated DBAPI object)
        self.warned = False
        from sqlalchemy import event

        event.listen(engine, "checkout", self._on_checkout)
        event.listen(engine, "checkin", self._on_checkin)

    def grow(self, dbapi_conn, record, mb: int) -> None:
        try:
            current = int(_pragma(dbapi_conn, "PRAGMA cache_size")[0][0])
            wanted = -mb * 1024  # negative = KiB
            if current < 0 and current <= wanted:  # only grow, and only compare like with like
                return
            with self.lock:
                self.saved[record] = current
            _pragma(dbapi_conn, f"PRAGMA cache_size={wanted}")
        except Exception as exc:  # noqa: BLE001
            with self.lock:
                self.saved.pop(record, None)
            if not self.warned:
                self.warned = True
                _LOG.warning("could not enlarge the re-index page cache: %s", type(exc).__name__)

    def _on_checkout(self, dbapi_conn, record, _proxy) -> None:
        entry = self.growers.get(threading.get_ident())
        if entry is not None:
            self.grow(dbapi_conn, record, entry[0])

    def _on_checkin(self, dbapi_conn, record) -> None:
        with self.lock:
            old = self.saved.pop(record, None)
        if old is not None and dbapi_conn is not None:  # None = invalidated: the connection is gone, nothing to restore
            with contextlib.suppress(Exception):
                _pragma(dbapi_conn, f"PRAGMA cache_size={old}")


_HOOKS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_HOOKS_LOCK = threading.Lock()


def _hooks_for(engine) -> _EngineHooks:
    with _HOOKS_LOCK:
        hooks = _HOOKS.get(engine)
        if hooks is None:
            hooks = _HOOKS[engine] = _EngineHooks(engine)
        return hooks


@contextlib.contextmanager
def bulk_page_cache(session, size_mb: int | None = None) -> Iterator[int]:
    """Enlarge the page cache of every connection THIS THREAD checks out of ``session``'s engine while the block runs.

    Yields the MiB applied (0 = nothing, the block runs exactly as before). Never raises for a cache problem: a connection that
    refuses the PRAGMA keeps the cache it had, and the failure is logged once.

    A grown connection is put back as it was when the POOL takes it back, not when the block ends: the block may end (or raise)
    while the session still holds one, and reaching into the session then would check out a connection nobody asked for."""
    try:
        mb = reindex_cache_mb() if size_mb is None else size_mb
        me = threading.get_ident()
        bind = session.get_bind()
        engine = getattr(bind, "engine", bind)  # a session bound to a Connection resolves to that connection's engine
        if mb <= 0 or engine.dialect.name != "sqlite":
            yield 0
            return
        hooks = _hooks_for(engine)
    except Exception:  # noqa: BLE001 - no bind, a test double, an unlistenable target: nothing to tune
        yield 0
        return

    with hooks.lock:
        entry = hooks.growers.setdefault(me, [mb, 0])
        entry[1] += 1
    try:
        # A session already inside a transaction holds a connection checked out before the block: grow that one now. (Never ask a
        # session with no transaction for a connection: that would check one out for nothing.)
        if session.in_transaction():
            with contextlib.suppress(Exception):
                fairy = session.connection().connection
                hooks.grow(fairy.dbapi_connection, fairy._connection_record, mb)
        yield mb
    finally:
        with hooks.lock:
            entry[1] -= 1
            if entry[1] <= 0:
                hooks.growers.pop(me, None)
