"""
Database engine, session lifecycle, and FastAPI dependency.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Design (single local user, loopback-only, SQLite default):
  * NO side effects at import. The engine is created lazily; tables are created
    only by an explicit ``init_db()`` call from the application lifespan. Importing
    this module (or ``models``) must never create a database file or spawn a thread.
  * SQLite runs in WAL mode with a busy timeout and foreign keys enforced, so the
    single-writer + concurrent-reader pattern (API reading while the scraper writes)
    behaves correctly instead of throwing "database is locked".
  * Sessions are acquired per-request / per-operation via ``get_db`` (FastAPI
    ``Depends``) or the ``session_scope`` context manager -- never one global
    Session shared across threads.

A PostgreSQL ``DATABASE_URL`` is honoured for future server deployments; the
SQLite-specific PRAGMAs are simply skipped for non-SQLite engines.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as SASession
from sqlalchemy.orm import sessionmaker

# --------------------------------------------------------------------------- #
# Paths & URL
# --------------------------------------------------------------------------- #
# Repo root: src/database/session.py -> parents[2]. On a real deployment the data
# directory lives under the persistent AppVM /home; here it is repo-local.
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("OO_DATA_DIR", REPO_ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'open_omniscience.db'}")
_IS_SQLITE = DATABASE_URL.startswith("sqlite")


def _build_engine() -> Engine:
    """Create the SQLAlchemy engine with backend-appropriate settings."""
    if _IS_SQLITE:
        # check_same_thread=False is safe here because sessions are request/operation
        # scoped (see module docstring), not shared globally across threads.
        return create_engine(
            DATABASE_URL,
            future=True,
            connect_args={"check_same_thread": False, "timeout": 30},
        )
    # PostgreSQL / other: modest pool suitable for a single-user server.
    return create_engine(
        DATABASE_URL,
        future=True,
        pool_pre_ping=True,
        pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
        pool_recycle=3600,
    )


engine: Engine = _build_engine()


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    """Apply WAL + safety/concurrency PRAGMAs to every new SQLite connection."""
    if not _IS_SQLITE:
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")  # ms; wait instead of erroring
        cursor.execute("PRAGMA synchronous=NORMAL")  # safe with WAL, much faster
    finally:
        cursor.close()


# Session factory. Explicit commits/flushes for predictable transaction control.
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)

# Back-compat alias: a lot of existing code does ``from ...models import Session``.
Session = SessionLocal


def init_db() -> None:
    """
    Create all tables. Call this ONCE explicitly (app lifespan / installer / tests).

    Imported lazily to avoid a circular import (models imports this module).
    """
    from src.database.models import Base  # local import breaks the cycle

    Base.metadata.create_all(engine)

    # Build the full-text search index (SQLite FTS5). No-op on other backends.
    from src.database.fts import ensure_fts

    ensure_fts(engine)


def get_session() -> SASession:
    """Return a new session. Caller is responsible for closing it.

    Prefer ``session_scope()`` or the ``get_db`` dependency, which close for you.
    """
    return SessionLocal()


def close_session(session: SASession) -> None:
    """Close a session, swallowing errors (best-effort cleanup)."""
    try:
        session.close()
    except Exception:
        pass


@contextmanager
def session_scope() -> Iterator[SASession]:
    """Transactional scope: commit on success, rollback on error, always close."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[SASession]:
    """FastAPI dependency. Yields a session and guarantees it is closed.

    Usage:
        @app.get("/x")
        def handler(db: Session = Depends(get_db)): ...
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def dispose_engine() -> None:
    """Dispose the engine's connection pool (call on app shutdown)."""
    engine.dispose()
