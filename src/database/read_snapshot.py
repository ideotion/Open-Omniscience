"""
A read-only WAL snapshot session for heavy exports (field finding C).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why this exists:
  The heavy keyword-diagnostics export scans ``keyword_mentions`` twice over a
  field-scale corpus — each in-range page a SQLCipher decrypt — and the field log
  measured it running SLOWER on a second run *because it was contending with the live
  scrape* (run1 29.6 s → run2 65.2 s). A read never takes the single-writer gate (WAL
  lets a reader pass a writer), so it does not *block* the collector; but on the shared
  engine it competes for a pooled connection for the whole multi-minute scan and rides
  the same connection lifecycle a WAL checkpoint can churn.

What this gives the export:
  A DEDICATED read-only connection on its OWN ``NullPool`` engine (never a shared-pool
  slot held for minutes), opened through the ONE :func:`src.database.connect.connect`
  factory (so SQLCipher is handled identically), with:

  * ``PRAGMA query_only=ON`` — a hard belt: this connection can NEVER issue a write, so
    the export can never take the write gate or stall a writer, by construction;
  * one held read transaction across the whole streamed response — WAL pins a single
    consistent snapshot for the export's duration (its two big scans agree), and the
    reader is isolated from concurrent commits.

  The engine is ``NullPool`` so each export's connection is opened fresh and CLOSED at
  the end (a re-derived SQLCipher key per export is a negligible cost against a
  multi-second scan) — it never leaves a ``query_only`` connection in the shared pool.

Non-SQLite backends fall back to the main engine (PostgreSQL MVCC gives read isolation).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import Depends
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as SASession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from src.database.session import get_db

_LOG = logging.getLogger(__name__)

# One read engine per DB URL (production has exactly one; tests may point at a temp DB).
_engines: dict[str, Engine] = {}
_factories: dict[str, sessionmaker] = {}


def _build_read_engine(url: str) -> Engine:
    if not url.startswith("sqlite"):
        # Non-SQLite: reuse the main engine (server backends have their own MVCC).
        from src.database.session import engine

        return engine

    db_path = url.removeprefix("sqlite:///")

    def _creator():
        from src.database.connect import connect

        return connect(db_path, check_same_thread=False, timeout=30)

    eng = create_engine(url, future=True, creator=_creator, poolclass=NullPool)

    @event.listens_for(eng, "connect")
    def _read_pragmas(dbapi_connection, _record) -> None:  # noqa: ANN001
        # Take pysqlite OUT of its legacy implicit-transaction mode so SQLAlchemy fully
        # controls transactions (the documented recipe below). Without this, pysqlite
        # runs SELECTs in autocommit — each read sees the latest commit, so a two-scan
        # export would NOT get one consistent WAL snapshot.
        try:
            dbapi_connection.isolation_level = None
        except Exception:  # noqa: BLE001 - non-pysqlite driver: leave as-is
            pass
        cur = dbapi_connection.cursor()
        try:
            cur.execute("PRAGMA busy_timeout=30000")
            # Hard guarantee: nothing on this connection can write (so it can never
            # take the write gate nor block the collector). Reversible per-connection,
            # and the connection is discarded on close (NullPool) so it never pollutes
            # a shared pool.
            cur.execute("PRAGMA query_only=ON")
        finally:
            cur.close()

    @event.listens_for(eng, "begin")
    def _explicit_begin(conn) -> None:  # noqa: ANN001
        # With the driver in autocommit (above), emit a real BEGIN when SQLAlchemy's
        # transaction starts, so a single DEFERRED read transaction is held across the
        # whole export: the WAL snapshot pins at the first read and every later scan sees
        # the SAME consistent view (the export's two keyword_mentions passes agree, and a
        # racing write can neither corrupt nor stall the scan).
        conn.exec_driver_sql("BEGIN")

    return eng


def _factory(url: str | None = None) -> sessionmaker:
    if url is None:
        from src.database.session import DATABASE_URL

        url = DATABASE_URL
    if url not in _factories:
        _engines[url] = _build_read_engine(url)
        _factories[url] = sessionmaker(
            bind=_engines[url], autocommit=False, autoflush=False, future=True
        )
    return _factories[url]


@contextmanager
def read_snapshot_session(url: str | None = None) -> Iterator[SASession]:
    """A read-only, ``query_only`` session holding one WAL snapshot; always closed.

    ``url`` overrides the corpus DB (tests point at a temp file); default = the live
    corpus (:data:`src.database.session.DATABASE_URL`).
    """
    session = _factory(url)()
    try:
        yield session
    finally:
        session.close()


def read_only_db(db: SASession = Depends(get_db)) -> Iterator[SASession]:
    """FastAPI dependency: a read-only WAL-snapshot session for a pure-read handler.

    It COMPOSES ``get_db`` so it transparently inherits any test dependency override
    (a test that overrides ``get_db`` with its own engine is served that engine, so the
    read-snapshot never breaks such tests). Only when it sees the real production engine
    does it swap to the dedicated ``query_only`` NullPool read engine — freeing the shared
    pool connection immediately and running the export on an isolated WAL snapshot. The
    session (and its snapshot) lives until FastAPI closes the dependency AFTER the streamed
    response is fully sent.
    """
    from src.database.session import engine as main_engine

    bind = db.get_bind()
    if bind is not main_engine or getattr(bind.dialect, "name", "") != "sqlite":
        # A test override, or a non-SQLite backend: use the injected session as-is.
        yield db
        return

    # Production: release the shared-pool connection we won't use, and run the export on
    # a dedicated read-only snapshot connection instead.
    db.close()
    session = _factory()()
    try:
        yield session
    finally:
        session.close()


def dispose_read_engines() -> None:
    """Dispose all read engines (app shutdown / test teardown)."""
    for eng in _engines.values():
        try:
            eng.dispose()
        except Exception:  # noqa: BLE001 - cleanup must never raise
            _LOG.debug("read engine dispose failed", exc_info=True)
    _engines.clear()
    _factories.clear()
