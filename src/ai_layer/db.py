"""
The AI layer's database: a SEPARATE encrypted store, parallel to the main corpus.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ruling 2026-06-17 (CLAUDE.md — "LLM SCOPE — STRICT PHYSICAL SEPARATION"):
AI-derived analytics live in their OWN database file, never the main corpus (the
only AI writes to main are summaries/translations in ``article_analyses``). This
module owns that second store:

  * a SEPARATE SQLAlchemy engine bound to ``data_dir()/ai_layer.db`` (env
    ``OO_AI_DB_PATH`` overrides — tests point it at a temp file);
  * opened through the ONE connection factory (:func:`src.database.connect.connect`),
    so it is SQLCipher-encrypted under the SAME passphrase as the main store — there
    is no second key surface (a locked boot has no key, so the AI store stays locked
    too, exactly like the corpus);
  * its OWN single-writer gate — a fresh :class:`WriterGate`, NOT the main store's
    process-wide singleton. The AI file has its own SQLite write lock, so serialising
    AI writes through the MAIN gate would needlessly block corpus writes. AI writes
    are batch jobs; this gate only keeps two of them from colliding on the AI file;
  * created LAZILY on first use (:func:`init_ai_db`) — no empty encrypted file
    appears for users who never run an AI feature, and there is zero boot-path change.

The store is NEVER ``ATTACH``-ed to the main connection (the physical separation is
the guarantee): cross-database references are plain integers resolved in app code.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as SASession
from sqlalchemy.orm import sessionmaker

from src.database.writer import WriterGate, gate_enabled

_LOG = logging.getLogger("ai_layer.db")

# A DEDICATED write gate for the AI store (its own SQLite write lock — see the module
# docstring). Distinct from the main store's process-wide singleton, so AI batch jobs
# never block corpus writes and vice versa.
ai_write_gate = WriterGate()
_AI_SESSION_FLAG = "_oo_ai_write_gate_held"

_lock = threading.Lock()
_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None
_gate_registered = False


def ai_db_path() -> Path:
    """The AI store's file path. ``OO_AI_DB_PATH`` overrides the default location
    under the data dir (tests point it at a throwaway file)."""
    override = os.environ.get("OO_AI_DB_PATH")
    if override:
        return Path(override)
    from src.paths import data_dir

    return data_dir() / "ai_layer.db"


def _build_engine() -> Engine:
    path = ai_db_path()
    url = f"sqlite:///{path}"

    def _creator():
        # The ONE factory: opens the file per its real at-rest state (SQLCipher +
        # the process passphrase when encrypted, stdlib sqlite3 when plaintext, and
        # DatabaseLockedError while an encrypted store still awaits its passphrase).
        from src.database.connect import connect

        return connect(path, check_same_thread=False, timeout=30)

    eng = create_engine(url, future=True, creator=_creator)

    @event.listens_for(eng, "connect")
    def _ai_pragmas(dbapi_connection, _record) -> None:  # noqa: ANN001
        cur = dbapi_connection.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("PRAGMA synchronous=NORMAL")
            # mmap for PLAINTEXT only: SQLCipher pages can't be mapped through the
            # codec (every page passes the decrypt), so mmap there would be theatre.
            if "sqlcipher" not in type(dbapi_connection).__module__:
                cur.execute("PRAGMA mmap_size=134217728")  # 128 MiB
        finally:
            cur.close()

    return eng


def _ensure() -> sessionmaker:
    """Build (once) the engine + session factory and wire the AI write gate."""
    global _engine, _SessionLocal
    with _lock:
        if _SessionLocal is None:
            _engine = _build_engine()
            _SessionLocal = sessionmaker(
                bind=_engine, autocommit=False, autoflush=False, future=True
            )
            _register_ai_write_gate(_SessionLocal)
        return _SessionLocal


def get_engine() -> Engine:
    _ensure()
    assert _engine is not None
    return _engine


def init_ai_db() -> None:
    """Create the AI store's tables (idempotent). Call on first AI-feature use.

    Requires the store unlocked (the passphrase), exactly like the main DB — the
    ``connect()`` factory raises ``DatabaseLockedError`` if it is still locked.
    """
    from src.ai_layer.models import AiBase

    AiBase.metadata.create_all(get_engine())


def get_session() -> SASession:
    """A new AI-layer session. Prefer :func:`ai_session_scope` / :func:`get_ai_db`."""
    return _ensure()()


@contextmanager
def ai_session_scope() -> Iterator[SASession]:
    """Transactional scope on the AI store: commit on success, rollback on error,
    always close (and release the AI write gate)."""
    session = _ensure()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        _release_ai_gate_if_held(session)


def get_ai_db() -> Iterator[SASession]:
    """FastAPI dependency yielding an AI-layer session, closed afterwards."""
    session = _ensure()()
    try:
        yield session
    finally:
        session.close()
        _release_ai_gate_if_held(session)


def dispose_ai_engine() -> None:
    """Dispose the AI engine's pool (best-effort; safe if never built)."""
    global _engine
    if _engine is not None:
        _engine.dispose()


# --------------------------------------------------------------------------- #
#  The AI store's own single-writer gate (bound to ``ai_write_gate``)
# --------------------------------------------------------------------------- #
# This mirrors src/database/writer.py's session-event wiring but binds to a SEPARATE
# gate instance, so the two stores serialise independently (different files, different
# write locks). SQLite-only and honoring the same OO_WRITE_GATE escape hatch.


def _register_ai_write_gate(session_factory) -> None:
    global _gate_registered
    if _gate_registered:
        return
    if not gate_enabled():
        _gate_registered = True
        return
    event.listen(session_factory, "before_flush", _ai_before_flush)
    event.listen(session_factory, "do_orm_execute", _ai_orm_execute)
    event.listen(session_factory, "after_transaction_end", _ai_after_txn_end)
    _gate_registered = True


def _ai_before_flush(session, _flush_context, _instances) -> None:
    if not session.info.get(_AI_SESSION_FLAG):
        ai_write_gate.acquire()
        session.info[_AI_SESSION_FLAG] = True


def _ai_orm_execute(orm_execute_state) -> None:
    # Take the write window only for DML writes — reads never gate (WAL).
    if not (
        orm_execute_state.is_insert
        or orm_execute_state.is_update
        or orm_execute_state.is_delete
    ):
        return
    session = orm_execute_state.session
    if not session.info.get(_AI_SESSION_FLAG):
        ai_write_gate.acquire()
        session.info[_AI_SESSION_FLAG] = True


def _ai_after_txn_end(session, transaction) -> None:
    # Only the OUTERMOST transaction's end releases (savepoints have a parent).
    if transaction.parent is None and session.info.pop(_AI_SESSION_FLAG, False):
        ai_write_gate.release()


def _release_ai_gate_if_held(session) -> None:
    """Safety net: release the AI gate if a closed session still holds it."""
    if session.info.pop(_AI_SESSION_FLAG, False):
        ai_write_gate.release()


def _reset_for_tests() -> None:
    """Test-only: drop the cached engine/session factory so a fresh ``OO_AI_DB_PATH``
    takes effect and the gate re-registers on the new factory. Never in production."""
    global _engine, _SessionLocal, _gate_registered
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _SessionLocal = None
        _gate_registered = False
