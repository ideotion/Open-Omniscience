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

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as SASession
from sqlalchemy.orm import sessionmaker

# --------------------------------------------------------------------------- #
# Paths & URL
# --------------------------------------------------------------------------- #
# Data directory resolution is centralised in src.paths so a source checkout, an
# editable install under $HOME, and a wheel install into a read-only location all
# behave correctly (see that module's docstring). OO_DATA_DIR still wins.
from src.paths import data_dir, default_sqlite_url

DATA_DIR = data_dir()

DATABASE_URL = os.getenv("DATABASE_URL", default_sqlite_url())
_IS_SQLITE = DATABASE_URL.startswith("sqlite")


def _build_engine() -> Engine:
    """Create the SQLAlchemy engine with backend-appropriate settings."""
    if _IS_SQLITE:
        # Every connection comes from the ONE factory (src/database/connect.py),
        # which opens the file per its real at-rest state: SQLCipher + PRAGMA key
        # when encrypted (the ruled default), stdlib sqlite3 when plaintext, and
        # a loud DatabaseLockedError while an encrypted store awaits its
        # passphrase. The URL is kept so engine.url.database stays truthful.
        # check_same_thread=False is safe here because sessions are
        # request/operation scoped (see module docstring), not shared globally.
        db_path = DATABASE_URL.removeprefix("sqlite:///")

        def _creator():
            from src.database.connect import connect

            return connect(db_path, check_same_thread=False, timeout=30)

        # Pool sized for the bandwidth-governed collector: up to ~50 workers may
        # hold a session concurrently (reads; writes still serialise through the
        # single-writer gate), so the default QueuePool (5 + 10 overflow) would
        # block them. Overflow connections beyond pool_size are closed on return
        # (each re-open re-derives the SQLCipher key — a known, logged cost); the
        # governor's memory back-off keeps the number actually open in check.
        return create_engine(
            DATABASE_URL,
            future=True,
            creator=_creator,
            pool_size=int(os.getenv("OO_DB_POOL_SIZE", "8")),
            max_overflow=int(os.getenv("OO_DB_MAX_OVERFLOW", "64")),
            pool_timeout=float(os.getenv("OO_DB_POOL_TIMEOUT", "30")),
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
        # Trade RAM for CPU (maintainer field report 2026-06-12: 600 MB RAM idle
        # while 2 cores saturate). SQLite's default page cache is ~2 MB per
        # connection, so a 243 MB corpus is re-walked from cold pages on every
        # aggregation; 64 MB keeps the hot b-trees decoded. temp_store=MEMORY
        # moves GROUP BY / ORDER BY scratch trees off disk. Both matter MORE
        # under SQLCipher, where every page re-read costs a decrypt.
        #
        # MEMORY KNOB (field log 2026-06-18: process RSS 1.28 GB on a 6 GB box).
        # This cache is PER CONNECTION, so the worst case is ~cache_mb × (pool_size
        # + max_overflow) connections held warm. The default stays 64 MiB (the
        # aggregation speed-up is real), but OO_SQLITE_CACHE_MB lets a memory-
        # constrained operator turn it down (e.g. 16) without code changes.
        # Resolved via the power-profile knob (OO_SQLITE_CACHE_MB override, else the active
        # profile; Optimized = 64, byte-identical to today). Read PER CONNECTION, so a profile
        # switch applies to new connections; never raises (clamped ≥ 2).
        from src.config.power_profiles import sqlite_cache_mb

        cache_mb = sqlite_cache_mb()
        cursor.execute(f"PRAGMA cache_size=-{cache_mb * 1024}")  # negative = KiB
        cursor.execute("PRAGMA temp_store=MEMORY")
        # WAL RESTING CEILING (STORAGE_5TB_PLAN §3 Phase-A: "journal_size_limit is set
        # NOWHERE"). journal_mode=WAL grows the -wal to its high-water mark and, by default
        # (limit -1), NEVER truncates it back after a checkpoint — so on our workload
        # (continuous ingest + always-on UI polls) the -wal sits at its peak between the
        # inter-pass TRUNCATE checkpoints, wasting disk. This caps the size the -wal is
        # truncated to on an automatic checkpoint, giving it a resting ceiling; it does NOT
        # bound growth DURING a long transaction/reader-starvation (that is measured, not
        # tuned — see the storage diagnostic's wal_bytes). OO_WAL_SIZE_LIMIT_MB overrides;
        # <=0 restores SQLite's default (no limit). Bytes.
        try:
            wal_mb = int(os.getenv("OO_WAL_SIZE_LIMIT_MB", "64"))
        except ValueError:
            wal_mb = 64
        cursor.execute(f"PRAGMA journal_size_limit={wal_mb * 1024 * 1024 if wal_mb > 0 else -1}")
        # mmap for PLAINTEXT stores only: SQLCipher pages cannot be memory-
        # mapped through the codec (every page passes the decrypt), so mmap
        # there would be a fabricated speed-up. For plaintext files it lets
        # reads come straight from the OS page cache without a copy.
        if "sqlcipher" not in type(dbapi_connection).__module__:
            cursor.execute("PRAGMA mmap_size=268435456")  # 256 MiB
    finally:
        cursor.close()


# Session factory. Explicit commits/flushes for predictable transaction control.
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)

# Back-compat alias: a lot of existing code does ``from ...models import Session``.
Session = SessionLocal

# The single-writer gate (keystone #1): serialise every write through one
# in-process queue so two writers never collide on the SQLite write lock. Wired
# via session events so ORM write paths need no call-site change; SQLite only
# (a server PostgreSQL backend has its own concurrency control). See
# src/database/writer.py for the full rationale.
if _IS_SQLITE:
    from src.database.writer import register_write_gate

    register_write_gate(SessionLocal)


def init_db() -> None:
    """
    Create all tables. Call this ONCE explicitly (app lifespan / installer / tests).

    Imported lazily to avoid a circular import (models imports this module).
    """
    from src.database.models import Base  # local import breaks the cycle

    Base.metadata.create_all(engine)

    # Ensure the full-text search index (SQLite FTS5). No-op on other backends. The index
    # is maintained incrementally by triggers, so ``ensure_fts`` rebuilds ONLY when needed
    # (fresh table with existing articles, or an interrupted past build) — NOT on every
    # boot, which was the P0.4 unlock-at-scale regression (a corpus-scaled codec rebuild
    # recurring 981 s → 1,645 s at 130 GB). A rebuild is a one-time, honestly-logged event.
    from src.database.fts import ensure_fts

    _fts_action = ensure_fts(engine)
    if _fts_action == "rebuilt":
        _LOG.info(
            "FTS index rebuilt from the base table (one-time: fresh table with existing "
            "articles, or a prior incomplete build); steady-state boots skip this."
        )

    # Mark a freshly-created DB at the current migration baseline so future schema
    # changes apply via `alembic upgrade head`. No-op if already alembic-managed.
    from src.database.migrate import stamp_if_unstamped

    stamp_if_unstamped(engine)

    # Hot-path indexes for databases created before they existed (create_all
    # never adds indexes to existing tables; not every install runs alembic).
    from src.database.maintenance import (
        ensure_article_analysis_columns,
        ensure_article_detected_language_column,
        ensure_article_identity_columns,
        ensure_article_ip_columns,
        ensure_external_source_discovery_columns,
        ensure_feed_backoff_columns,
        ensure_hot_indexes,
        ensure_keyword_counter_columns,
        ensure_keyword_extractor_column,
        ensure_keyword_mention_source_column,
        ensure_article_quarantine_columns,
        ensure_law_document_language_columns,
        ensure_law_text_columns,
        ensure_source_counter_columns,
        ensure_source_qualification_columns,
        ensure_supergroup_ring_column,
        ensure_wiki_text_columns,
    )

    # Denormalised keyword counters (+ their index, + one-time backfill) BEFORE the
    # generic hot-index pass, since the counters' index depends on the column.
    ensure_keyword_counter_columns(engine)

    # K1/K2 identity seams on articles (self-heal + backfill for pre-existing stores).
    ensure_article_identity_columns(engine)

    # Source IP provenance columns (self-heal for pre-existing stores; no backfill).
    ensure_article_ip_columns(engine)

    # QUARANTINE columns (S3.2, self-heal for pre-existing stores; no backfill) --
    # BEFORE ensure_hot_indexes, since idx_article_quarantined needs the column to exist.
    ensure_article_quarantine_columns(engine)

    # Secondary/deduced language column (field §2.6; self-heal, populates forward).
    ensure_article_detected_language_column(engine)

    # Denormalised keyword_mentions.source_id (flood/bury card; self-heal, no backfill).
    ensure_keyword_mention_source_column(engine)

    ensure_hot_indexes(engine)

    # Per-feed de-churn backoff columns (field log finding F) for databases that
    # already had feed_fetch_state before these columns existed (create_all never
    # ALTERs an existing table; not every install runs alembic).
    ensure_feed_backoff_columns(engine)

    # article_analyses.prompt_text (exact prompt provenance) for stores created
    # before that column existed — same self-heal reason as the feed columns.
    ensure_article_analysis_columns(engine)

    # 0.09-cycle columns that shipped WITHOUT a boot self-heal (upgrade audit,
    # release 0.1): keywords.extractor (migration c3d4e5f6a7b8), the wiki
    # living-source columns (b6c7d8e9f0a1 + c9d8e7f6a5b4) and the super-ring
    # member marker (f4a5b6c7d8e9). Without these, a 0.0.8/early-0.09 store
    # opened by 0.1 code raises "no such column" on the first ORM query.
    ensure_keyword_extractor_column(engine)
    ensure_wiki_text_columns(engine)
    ensure_supergroup_ring_column(engine)

    # Q4a: external_sources.discovered_via provenance (self-heal, no backfill; populates forward
    # as the discovery funnel resolves domains into the registry).
    ensure_external_source_discovery_columns(engine)

    # Law versioned-text columns (the versioned-sources ruling): materialised latest + per-revision
    # full text (self-heal, no backfill; populates forward as the law tracker stores full text).
    ensure_law_text_columns(engine)

    # S4b: law_documents.language/.country (the Cambodia fix — self-heal, no backfill;
    # populates forward as documents are re-registered/re-synced from the catalog).
    ensure_law_document_language_columns(engine)

    # S6: maintained per-source article counter (self-heal, no backfill; reconcile populates
    # forward + stamps freshness, a NULL count reads live).
    ensure_source_counter_columns(engine)

    # Qualification lifecycle STAMP columns (0.3 CLOSE GATE ruling): self-heal + the
    # one-time "already scraped -> already qualified" backfill (never starves an
    # install that was already collecting before this column existed).
    ensure_source_qualification_columns(engine)

    # DB-8: the self-heals above bring an OLD store's schema to head WITHOUT touching the
    # alembic stamp, leaving a "lying stamp" (behind head while the schema is ahead) that
    # breaks the next real migration and the cross-version restore's `alembic upgrade`
    # (re-adding already-present columns -> "duplicate column"). Align the stamp to head,
    # but ONLY when the schema is verified fully at head (a genuinely-behind store keeps its
    # stamp and still migrates). Cheap when already at head; best-effort, never raises.
    from src.database.migrate import align_stamp_to_head

    _stamp = align_stamp_to_head(engine)
    if _stamp.get("action") == "advanced":
        _LOG.info(
            "alembic stamp aligned to head (%s -> %s) after schema self-heal; the stamp "
            "no longer lags the healed schema.",
            _stamp.get("from"),
            _stamp.get("to"),
        )
    elif _stamp.get("action") in ("schema-behind", "behind-data-floor"):
        _LOG.info(
            "alembic stamp left at %s (%s): kept so a pending migration runs rather than "
            "being stamped forward. detail=%s",
            _stamp.get("from"),
            _stamp.get("action"),
            _stamp.get("diffs") or _stamp.get("floor"),
        )


def get_session() -> SASession:
    """Return a new session. Caller is responsible for closing it.

    Prefer ``session_scope()`` or the ``get_db`` dependency, which close for you.
    """
    return SessionLocal()


_LOG = logging.getLogger("database.session")


def close_session(session: SASession) -> None:
    """Close a session, swallowing errors (best-effort cleanup).

    The swallow is deliberate (cleanup must never raise), but we log at debug
    so a recurring close failure -- a symptom of a connection leak -- is visible
    when debugging rather than silent (finding BUG-04).
    """
    try:
        session.close()
    except Exception:
        _LOG.debug("close_session: error during session.close()", exc_info=True)


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
        _release_write_gate(session)


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
        _release_write_gate(session)


def _release_write_gate(session: SASession) -> None:
    """Safety net: release the single-writer gate if this session still holds it
    after close (the implicit rollback on close has already resolved any open
    write transaction). A no-op when the gate is off or already released by an
    event — never lets the gate leak past a session's lifetime."""
    if not _IS_SQLITE:
        return
    try:
        from src.database.writer import release_if_held

        release_if_held(session)
    except Exception:  # noqa: BLE001 - cleanup must never raise
        _LOG.debug("write-gate safety release failed", exc_info=True)


def dispose_engine() -> None:
    """Dispose the engine's connection pool (call on app shutdown)."""
    engine.dispose()
