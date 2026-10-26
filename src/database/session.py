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

**SQLite is the only SUPPORTED backend** (audit ARCH-06 / question J3, ruled
2026-09-07; see ``docs/ARCHITECTURE.md``). A non-SQLite ``DATABASE_URL`` is not
rejected -- the engine is still built and ordinary ORM reads and writes work -- but
this docstring used to call that "honoured … the SQLite-specific PRAGMAs are simply
skipped", and that understated the loss by a wide margin. What a non-SQLite engine
actually skips is the SQLCipher connection factory and therefore **at-rest
encryption**, which is this app's whole stated security model; FTS5 and therefore
**the entire search path**; the single-writer gate; and the boot index self-heal.
``_build_engine`` logs a WARNING naming that, so such a URL degrades LOUDLY instead
of producing a half-working app that looks fine.
"""

from __future__ import annotations

import logging
import math
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

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
from src.database import damage as _damage

# Before any engine exists: every pool's new connections get the search index's transform
# functions, which its sync triggers call (Q506/Q507, src/database/fts_norm.py).
from src.database import fts_norm as _fts_norm  # noqa: F401
from src.database import library_generation as _library_generation
from src.database.init_steps import recorded as _record_init_steps
from src.database.init_steps import step as _init_step
from src.database.pool_reserve import ReservingQueuePool
from src.database.statement_kind import is_plain_read as _is_plain_read
from src.database.writer import _SESSION_FLAG as _WRITE_GATE_SESSION_FLAG
from src.monitoring.secret_scrub import log_failure
from src.paths import data_dir, default_sqlite_url

DATA_DIR = data_dir()

DATABASE_URL = os.getenv("DATABASE_URL", default_sqlite_url())
_IS_SQLITE = DATABASE_URL.startswith("sqlite")


def _pool_timeout_s() -> float:
    """``OO_DB_POOL_TIMEOUT``: how long a checkout waits for a pooled connection (default 30 s).

    A value the pool cannot use is refused and the default used, with a log line: ``nan`` (it
    spins a core at full speed for ever), ``inf`` or anything above ``threading.TIMEOUT_MAX``
    (``OverflowError`` from the first checkout that has to wait), a negative number
    (``ValueError``, there as well), and an unparseable value (``abc``, empty), which used to stop
    the app at import. Every value the pool CAN use, ``0`` (fail at once) and a wait of minutes
    included, is kept as it is: this is not a clamp."""
    raw = os.getenv("OO_DB_POOL_TIMEOUT", "30")
    try:
        value = float(raw)
    except ValueError:
        value = float("nan")
    if not math.isfinite(value) or value < 0 or value > threading.TIMEOUT_MAX:
        # Resolved by NAME: this runs inside the module-level ``_build_engine()`` call, above the
        # module's ``_LOG``.
        logging.getLogger("database.session").warning(
            "OO_DB_POOL_TIMEOUT=%r is not a number of seconds the pool can wait; using the default, 30 s", raw
        )
        return 30.0
    return value


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
        # S1.1: the pool's SIZE is now a function of the machine, not a constant.
        # 8 + 64 connections at 64 MiB of page cache each is a 4.6 GB worst case that
        # nothing computed before; on the 3.3 GB field machine that is the whole
        # machine. The budget resolves it from total RAM ONCE, and an explicit
        # OO_DB_POOL_SIZE / OO_DB_MAX_OVERFLOW still wins (it is read inside the
        # budget, and reported there as an override). Read HERE, at engine build, so
        # it is applied before the first connection exists — the pool size cannot be
        # changed on a live engine.
        from src.config.memory_budget import budget as _memory_budget

        _b = _memory_budget()
        return create_engine(
            DATABASE_URL,
            future=True,
            # Opened under the library lock, stamped with the generation read under it (``database/library_generation.py``).
            creator=_library_generation.guarded_creator(_creator),
            pool_size=int(_b["db_pool_size"]),
            max_overflow=int(_b["db_max_overflow"]),
            pool_timeout=_pool_timeout_s(),
            # D44 = a: collector-role checkouts leave the API's margin free.
            poolclass=ReservingQueuePool,
        )
    # NOT SQLite. Nothing here refuses the URL -- refusing would break an install in
    # the name of documenting it -- but a silent half-working app is the dishonest
    # outcome, so say what is missing, once, at the only place that knows. The logger
    # is resolved by NAME rather than through the module's ``_LOG``, because that
    # binding lives below the module-level ``_build_engine()`` call this line runs
    # inside. Only the SCHEME is printed: a DATABASE_URL carries a password, and the
    # error log ships inside the diagnostics bundle an operator hands to somebody else.
    logging.getLogger("database.session").warning(
        "DATABASE_URL is %s, not SQLite. SQLite is the only supported backend "
        "(docs/ARCHITECTURE.md): this engine has NO at-rest encryption (the SQLCipher "
        "connection factory is SQLite-only), NO full-text search (FTS5 -- search will "
        "be empty), no single-writer gate and no boot index self-heal.",
        DATABASE_URL.split("://", 1)[0] + "://...",
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


def wal_size_limit_bytes() -> int:
    """The ``-wal``'s RESTING ceiling in force (``OO_WAL_SIZE_LIMIT_MB``, default 64; ``<= 0``
    restores SQLite's no-limit default, answered as ``-1``), in bytes. A log that ever grew past
    it is truncated back to EXACTLY this size and rests there, so a leftover ``-wal`` of this size
    says how big the log once was, not how much of it is unapplied (the unlock page's recovery
    floor reads it for that reason)."""
    try:
        wal_mb = int(os.getenv("OO_WAL_SIZE_LIMIT_MB", "64"))
    except ValueError:
        wal_mb = 64
    return wal_mb * 1024 * 1024 if wal_mb > 0 else -1


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
        # S1.1: the profile knob still decides when the operator set one; otherwise the
        # RAM-aware budget does, so the per-connection cache scales with the machine
        # instead of being a flat 64 MiB on a 3.3 GB box.
        from src.config.memory_budget import budget as _memory_budget
        from src.config.power_profiles import sqlite_cache_mb

        cache_mb = (
            sqlite_cache_mb()
            if os.getenv("OO_SQLITE_CACHE_MB") is not None
            else int(_memory_budget()["sqlite_cache_mb"])
        )
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
        cursor.execute(f"PRAGMA journal_size_limit={wal_size_limit_bytes()}")
        # mmap for PLAINTEXT stores only: SQLCipher pages cannot be memory-
        # mapped through the codec (every page passes the decrypt), so mmap
        # there would be a fabricated speed-up. For plaintext files it lets
        # reads come straight from the OS page cache without a copy.
        if "sqlcipher" not in type(dbapi_connection).__module__:
            cursor.execute("PRAGMA mmap_size=268435456")  # 256 MiB
    finally:
        cursor.close()


#: The SQLite messages a vanished drive produces (R86): the file's device is gone.
_DISK_GONE = ("disk i/o error", "unable to open database file", "no such device")


@event.listens_for(engine, "handle_error")
def _data_drive_on_disk_error(context) -> None:
    """A disk error on the corpus asks the data-drive watchdog to look NOW (R86) rather
    than at its next 2 s tick. Observes only: the error still propagates unchanged."""
    msg = str(getattr(context, "original_exception", "") or "").lower()
    hit = next((m for m in _DISK_GONE if m in msg), None)
    if hit is None:
        return
    try:
        from src.safety.data_volume import MONITOR

        MONITOR.poke(f"database error: {hit}")  # our own marker, never the driver's words
    except Exception:  # noqa: BLE001 - an observer never replaces the real error
        pass


@event.listens_for(engine, "handle_error")
def _storage_guard_on_disk_full(context) -> None:
    """A write that FAILED for want of space stops collection NOW (storage guard, rank 2).

    On the field's fullest machine one pass after another failed on the same full drive
    (fourteen in a row), because nothing connected "the disk is full" to "do not start the
    next pass". The guard's supervisor would see the free figure within five seconds; this
    closes the gap between the failure and that sample, and covers a drive that reports
    room but refuses writes (a quota). SQLite's plain "disk I/O error" counts when the drive's
    free space is below the reserve (a copy-on-write filesystem reports ENOSPC at fsync that
    way). Observes only: the error still propagates unchanged.
    """
    try:
        from src.scheduler.storage_guard import on_engine_error

        on_engine_error(context)
    except Exception:  # noqa: BLE001 - an observer never replaces the real error
        pass


# A failed statement whose DRIVER error is SQLITE_CORRUPT names the corpus file as damaged and pauses
# its writers (``database/damage.py``). Observes only: the error still propagates unchanged.
_damage.attach(engine, _damage.FILE_CORPUS)

# A connection made before a repair (or a restore) switched the library to a new file must not be used after it: its statements and
# its COMMIT would land in the file that is now kept under a second name (``database/library_generation.py``).
_library_generation.attach(engine)


@event.listens_for(engine, "reset")
def _disarm_progress_handler(dbapi_connection, _connection_record, _reset_state) -> None:
    """S2.1: no connection may re-enter the pool carrying a progress handler.

    ``statement_deadline`` arms the SQLite progress handler, which is state on
    the DBAPI CONNECTION, not on the session. A block that ends (or merely
    commits) while its deadline is still running returns an ARMED connection to
    the pool, and the next thread to check it out is interrupted on the first
    thread's clock -- reproduced against the shipped code: with
    ``pool_size=1`` thread B's own statement raised ``interrupted`` while
    thread A was still inside its block.

    ``reset`` is the right hook, verified against the installed SQLAlchemy
    (2.0.52) rather than assumed: it fires before checkin on QueuePool, before
    close on NullPool (the read-snapshot engines), and on a bare
    ``raw_connection()`` checkout+close -- so there is no return path that
    escapes it.

    Defensive by construction: a driver without the attribute, or a connection
    already closed, needs no disarm and must never turn a checkin into an error.
    """
    try:
        handler = getattr(dbapi_connection, "set_progress_handler", None)
        if handler is not None:
            handler(None, 0)
    except Exception:  # noqa: BLE001 - a checkin must never fail on a teardown
        pass


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

# S2.6 (b): record which thread holds each POOLED CONNECTION. Not a duplicate of
# the write gate -- a long-lived READ transaction pins the WAL with the gate free
# the whole time, and that is the thread the gate can never name. Backend-neutral
# (it records checkouts, not writes) and cheap: a dict entry per checkout, dropped
# on checkin, no statement text.
from src.database import pool_watch as _pool_watch  # noqa: E402

_pool_watch.register(engine)


@_record_init_steps
def init_db() -> None:
    """
    Create all tables. Call this ONCE explicitly (app lifespan / installer / tests).

    Imported lazily to avoid a circular import (models imports this module).

    Every step names itself with ``_init_step`` BEFORE it runs, and ``@_record_init_steps`` keeps the
    time of each (``src/database/init_steps.py``, STORE-02): a step you add needs its line, and
    ``tests/test_init_steps.py`` fails when it has none, because the time of an unnamed step is
    charged to the one before it.
    """
    _init_step("import:models")
    from src.database.models import Base  # local import breaks the cycle

    # A country-form migration that began and did not end leaves rows in both forms: nothing boots on such a store
    # (every start path goes through here), and ``store_form()`` refuses the writes of anything already running.
    _init_step("import:country_form")
    from src.database.country_form import refuse_if_unfinished, stamp_new_store

    _init_step("refuse_if_unfinished")
    refuse_if_unfinished()

    # A file that already holds a corpus keeps the country form it has (src/database/country_form.py); one the
    # app is creating NOW is stamped alpha-3 right after the tables exist, before any row can carry a code.
    _init_step("import:sqlalchemy")
    from sqlalchemy import inspect as _sa_inspect

    # ``app_state`` alone is not a corpus: the settings store can create it before the first boot reaches here.
    _init_step("any:country_form_look")
    _had_tables = any(t != "app_state" for t in _sa_inspect(engine).get_table_names())

    _init_step("create_all")
    Base.metadata.create_all(engine)

    _init_step("stamp_new_store")
    stamp_new_store(engine, had_tables=_had_tables)

    # Ensure the full-text search index (SQLite FTS5). No-op on other backends. The index
    # is maintained incrementally by triggers, so ``ensure_fts`` rebuilds ONLY when needed
    # (fresh table with existing articles, or an interrupted past build) — NOT on every
    # boot, which was the P0.4 unlock-at-scale regression (a corpus-scaled codec rebuild
    # recurring 981 s → 1,645 s at 130 GB). A rebuild is a one-time, honestly-logged event.
    _init_step("import:fts")
    from src.database.fts import ensure_fts

    _init_step("ensure_fts")
    _fts_action = ensure_fts(engine)
    if _fts_action == "rebuilt":
        _LOG.info(
            "FTS index rebuilt from the base table (one-time: fresh table with existing "
            "articles, or a prior incomplete build); steady-state boots skip this."
        )

    # Mark a freshly-created DB at the current migration baseline so future schema
    # changes apply via `alembic upgrade head`. No-op if already alembic-managed.
    _init_step("import:bulk_build")
    from src.analytics.bulk_build import heal_bulk_build

    _init_step("import:migrate")
    from src.database.migrate import stamp_if_unstamped

    _init_step("stamp_if_unstamped")
    stamp_if_unstamped(engine)

    # Hot-path indexes for databases created before they existed (create_all
    # never adds indexes to existing tables; not every install runs alembic).
    _init_step("import:maintenance")
    from src.database.maintenance import (
        ensure_article_analysis_columns,
        ensure_article_detected_language_column,
        ensure_article_identity_columns,
        ensure_article_ip_columns,
        ensure_article_keyword_indexed_column,
        ensure_article_newsletter_attach_column,
        ensure_article_newsletter_list_id_column,
        ensure_article_quarantine_columns,
        ensure_article_source_revision_column,
        ensure_article_top_keyword_columns,
        ensure_external_source_discovery_columns,
        ensure_feed_backoff_columns,
        ensure_hot_indexes,
        ensure_keyword_counter_columns,
        ensure_keyword_extractor_column,
        ensure_keyword_mention_source_column,
        ensure_law_document_language_columns,
        ensure_law_l0_columns,
        ensure_law_model_columns,
        ensure_law_source_type,
        ensure_law_text_columns,
        ensure_merge_batch_source_digest,
        ensure_merged_rows_row_key_column,
        ensure_source_catalog_baseline_column,
        ensure_source_counter_columns,
        ensure_source_last_crawled_column,
        ensure_source_qualification_columns,
        ensure_supergroup_ring_column,
        ensure_watch_filters_column,
        ensure_wiki_text_columns,
    )

    # Denormalised keyword counters (+ their index, + one-time backfill) BEFORE the
    # generic hot-index pass, since the counters' index depends on the column.
    _init_step("ensure_keyword_counter_columns")
    ensure_keyword_counter_columns(engine)

    # K1/K2 identity seams on articles (self-heal + backfill for pre-existing stores).
    _init_step("ensure_article_identity_columns")
    ensure_article_identity_columns(engine)

    # Source IP provenance columns (self-heal for pre-existing stores; no backfill).
    _init_step("ensure_article_ip_columns")
    ensure_article_ip_columns(engine)

    # Which artifact a merge batch came from (self-heal; NO backfill -- an unknown
    # digest must never match, or a never-done import could be skipped).
    _init_step("ensure_merge_batch_source_digest")
    ensure_merge_batch_source_digest(engine)

    # QUARANTINE columns (S3.2, self-heal for pre-existing stores; no backfill) --
    # BEFORE ensure_hot_indexes, since idx_article_quarantined needs the column to exist.
    _init_step("ensure_article_quarantine_columns")
    ensure_article_quarantine_columns(engine)

    # Secondary/deduced language column (field §2.6; self-heal, populates forward).
    _init_step("ensure_article_detected_language_column")
    ensure_article_detected_language_column(engine)

    # Own-top-keyword precompute columns (rulings 23/38/39; self-heal, no backfill) --
    # BEFORE ensure_hot_indexes, whose idx_article_top_keyword is built over them.
    _init_step("ensure_article_top_keyword_columns")
    ensure_article_top_keyword_columns(engine)

    # The keyword pass's attempt record (PRH-01; self-heal, no backfill) -- what lets
    # the backfill queue rotate past an article that legitimately yields zero terms.
    _init_step("ensure_article_keyword_indexed_column")
    ensure_article_keyword_indexed_column(engine)

    # Denormalised keyword_mentions.source_id (flood/bury card; self-heal, no backfill).
    _init_step("ensure_keyword_mention_source_column")
    ensure_keyword_mention_source_column(engine)

    # The version anchor on articles (S4; self-heal, no backfill) -- which upstream
    # revision an article's stored TEXT came from, for versioned sources.
    _init_step("ensure_article_source_revision_column")
    ensure_article_source_revision_column(engine)

    # The newsletter List-Id on articles (ingest provenance; self-heal, no backfill) --
    # the ruled stable key for a platform sender whose host names no publication.
    _init_step("ensure_article_newsletter_list_id_column")
    ensure_article_newsletter_list_id_column(engine)
    _init_step("ensure_article_newsletter_attach_column")
    ensure_article_newsletter_attach_column(engine)
    _init_step("ensure_source_catalog_baseline_column")
    ensure_source_catalog_baseline_column(engine)

    # The read seam over the derived keyword rows (segmented-index step 0, R96): create the
    # view for a database made before it existed, or re-create it if the table's columns
    # moved. AFTER the column self-heals above -- a view naming a column the table does not
    # yet have blocks every ALTER ... RENAME until it is repaired. Boot makes no network call
    # and this reads one sqlite_master row when the view is current.
    _init_step("import:derived_views")
    from src.database.derived_views import ensure_derived_views

    _init_step("ensure_derived_views")
    ensure_derived_views(engine)

    # The two article-list indexes (R128) are left to the ``article-indexes`` start-up step, which shows
    # its progress in the task manager; building them here would be a silent wait inside opening the
    # database, on a big store minutes long (src/database/article_indexes.py).
    _init_step("ensure_hot_indexes")
    ensure_hot_indexes(engine, include_deferred=False)

    # R23 / PR 5: finish a bulk build that a crash interrupted with its indexes dropped.
    #
    # THIS IS NOT COVERED BY ensure_hot_indexes ABOVE, which is why it is a second call
    # rather than an entry in HOT_INDEXES: of the 14 indexes the bulk window may drop,
    # only FOUR are in that map. The other ten exist solely because `create_all` or
    # alembic built them once, and neither adds an index to an EXISTING table -- so a
    # process that died between the DROP and the rebuild would leave them gone for good,
    # turning every query that used them into a full scan, silently. The heal is driven
    # by a durable marker and asks sqlite_master what is actually absent, so it is a
    # no-op (one small read, no DDL) on every boot where nothing was interrupted.
    _init_step("heal_bulk_build")
    heal_bulk_build(engine)

    # Per-feed de-churn backoff columns (field log finding F) for databases that
    # already had feed_fetch_state before these columns existed (create_all never
    # ALTERs an existing table; not every install runs alembic).
    _init_step("ensure_feed_backoff_columns")
    ensure_feed_backoff_columns(engine)

    # article_analyses.prompt_text (exact prompt provenance) for stores created
    # before that column existed — same self-heal reason as the feed columns.
    _init_step("ensure_article_analysis_columns")
    ensure_article_analysis_columns(engine)

    # 0.09-cycle columns that shipped WITHOUT a boot self-heal (upgrade audit,
    # release 0.1): keywords.extractor (migration c3d4e5f6a7b8), the wiki
    # living-source columns (b6c7d8e9f0a1 + c9d8e7f6a5b4) and the super-ring
    # member marker (f4a5b6c7d8e9). Without these, a 0.0.8/early-0.09 store
    # opened by 0.1 code raises "no such column" on the first ORM query.
    _init_step("ensure_keyword_extractor_column")
    ensure_keyword_extractor_column(engine)
    _init_step("ensure_watch_filters_column")
    ensure_watch_filters_column(engine)
    _init_step("ensure_wiki_text_columns")
    ensure_wiki_text_columns(engine)
    _init_step("ensure_supergroup_ring_column")
    ensure_supergroup_ring_column(engine)

    # Q4a: external_sources.discovered_via provenance (self-heal, no backfill; populates forward
    # as the discovery funnel resolves domains into the registry).
    _init_step("ensure_external_source_discovery_columns")
    ensure_external_source_discovery_columns(engine)

    # Law versioned-text columns (the versioned-sources ruling): materialised latest + per-revision
    # full text (self-heal, no backfill; populates forward as the law tracker stores full text).
    _init_step("ensure_law_text_columns")
    ensure_law_text_columns(engine)

    # S4b: law_documents.language/.country (the Cambodia fix — self-heal, no backfill;
    # populates forward as documents are re-registered/re-synced from the catalog).
    _init_step("ensure_law_document_language_columns")
    ensure_law_document_language_columns(engine)

    # S04-10 S1 (Q917): the adapter's dates + the diff's anchor (self-heal, no backfill;
    # populates forward as the tracker records revisions -- a pre-existing row's NULL
    # diff_basis honestly reads "recorded before the basis was tracked").
    _init_step("ensure_law_l0_columns")
    ensure_law_l0_columns(engine)
    _init_step("ensure_law_model_columns")
    ensure_law_model_columns(engine)
    _init_step("ensure_law_source_type")
    ensure_law_source_type(engine)

    # S6: maintained per-source article counter (self-heal, no backfill; reconcile populates
    # forward + stamps freshness, a NULL count reads live).
    _init_step("ensure_source_counter_columns")
    ensure_source_counter_columns(engine)

    # Qualification lifecycle STAMP columns (0.3 CLOSE GATE ruling): self-heal + the
    # one-time "already scraped -> already qualified" backfill (never starves an
    # install that was already collecting before this column existed).
    _init_step("ensure_source_qualification_columns")
    ensure_source_qualification_columns(engine)

    # C3: crawl-supplement rotation marker (self-heal, no backfill; populates
    # forward as the §8 crawl-by-default rung visits sources).
    _init_step("ensure_source_last_crawled_column")
    ensure_source_last_crawled_column(engine)

    # A source is keyed on (domain, feed) -- row J, S05-10. AFTER every sources column self-heal above (the
    # rebuild carries the columns that exist and needs the rest present) and BEFORE the seeder, which asks
    # whether the store can hold several feeds of one domain. Additive column + backfill, then one
    # cascade-proof table rebuild; a refusal is logged by class and the store keeps one feed per domain.
    _init_step("import:source_identity")
    from src.database.source_identity import ensure_source_composite_key, ensure_source_outlet_id

    _init_step("ensure_source_composite_key")
    ensure_source_composite_key(engine)

    # R177: the integer outlet id on sources (and its three triggers). After the rebuild above, which replays the triggers
    # an old table held. A refusal of the ADD COLUMN itself fails every Source query (the model maps the column, as with any
    # self-healed column); a refusal of the triggers or the heal leaves NULL rows, which a gate reads exactly while any exist
    # (``outlets_unhealed``) until the next boot.
    _init_step("ensure_source_outlet_id")
    ensure_source_outlet_id(engine)

    # R71 (b): the natural key of a restored text-keyed row (places, Wikidata items).
    _init_step("ensure_merged_rows_row_key_column")
    ensure_merged_rows_row_key_column(engine)

    # DB-8: the self-heals above bring an OLD store's schema to head WITHOUT touching the
    # alembic stamp, leaving a "lying stamp" (behind head while the schema is ahead) that
    # breaks the next real migration and the cross-version restore's `alembic upgrade`
    # (re-adding already-present columns -> "duplicate column"). Align the stamp to head,
    # but ONLY when the schema is verified fully at head (a genuinely-behind store keeps its
    # stamp and still migrates). Cheap when already at head; best-effort, never raises.
    _init_step("import:migrate:for_align")
    from src.database.migrate import align_stamp_to_head

    _init_step("align_stamp_to_head")
    _stamp = align_stamp_to_head(engine)
    # THE STAMP ALIGNMENT RUNS ALEMBIC, and env.py drops the derived-row view for any run that
    # is not already at head (SQLite refuses a column drop or table re-create while a view
    # names the column). The ensure further up ran BEFORE this, so on the first boot of an
    # install whose stamp lagged its self-healed schema the view would be gone and every
    # migrated reader would 500 until the next restart. Re-ensure: one sqlite_master read when
    # the view is present, so it costs nothing at steady state.
    _init_step("ensure_derived_views:after_align")
    ensure_derived_views(engine)
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
    except Exception as exc:
        log_failure(_LOG, "close_session: error during session.close()", exc, level=logging.DEBUG)


# "This transaction has written." Tracked on the Session CLASS, so it holds for
# every session in the process — including one bound to an engine the
# single-writer gate was never wired to (a test engine, a read-snapshot engine).
# The gate's own flag is checked too, but relying on it ALONE would make the
# guard blind exactly where the gate is absent. Same listener shape writer.py
# already proves: set on the first flush / ORM bulk DML, cleared when the
# OUTERMOST transaction ends (a savepoint has a parent and must not clear it).
#
# COST, measured rather than waved away (the recorded "an instrument on a hot
# path is a load source" lesson): +6 us per ORM statement, against 57 us for a
# trivial in-memory read -- ~10% there, and a far smaller share of any statement
# that touches the encrypted store. ``do_orm_execute`` is the per-statement one
# and it is the price of seeing bulk DML at all: it leaves no ORM state, so
# ``before_flush`` never fires for it. writer.py already pays this exact shape
# for gated sessions; this one holds for EVERY session in the process, which is
# what makes the guard sound on an engine the gate was never wired to.
_WROTE_FLAG = "_oo_txn_wrote"


def _mark_wrote(session: SASession) -> None:
    session.info[_WROTE_FLAG] = True


@event.listens_for(SASession, "before_flush")
def _wrote_on_flush(session, _flush_context, _instances) -> None:  # pragma: no cover - event
    _mark_wrote(session)


@event.listens_for(SASession, "do_orm_execute")
def _wrote_on_bulk_dml(orm_execute_state) -> None:  # pragma: no cover - event
    if (
        orm_execute_state.is_insert
        or orm_execute_state.is_update
        or orm_execute_state.is_delete
    ):
        _mark_wrote(orm_execute_state.session)


# "What the DRIVER had changed when this transaction began." The three markers above are the SESSION's: they see an ORM flush and an
# ORM-level bulk statement, and nothing that goes round the ORM -- ``session.connection().execute(...)``, a Core statement on that
# connection, the DBAPI cursor. A rollback after one of those discards the write without a sound (measured: both writes lost).
# The driver counts every row INSERT / UPDATE / DELETE changes on its connection (``sqlite3.Connection.total_changes``, the same
# attribute on the SQLCipher driver), so the count at the start of the transaction, read again at the release, says whether anything
# was written in between, whatever path it took. Keyed by the connection (a session bound to two would hold two entries, and the
# release declines it: it can say nothing about the second). ``in_transaction`` would not do: SQLite reports it for an explicit BEGIN
# (a read pin the release exists to give back) exactly as for a write -- ``tests/test_all_diag_read_release.py::
# test_a_pinned_snapshot_is_released_at_the_boundary_so_the_log_can_be_checkpointed`` is the pin a plain flag would redden.
_CHANGES_BASELINE = "_oo_txn_rows_changed"

# "A statement other than a plain read ran on this connection's transaction." The count above does not move for a schema change
# (CREATE / DROP / ALTER / REINDEX) or a PRAGMA that writes the header (``user_version``), and under an explicit BEGIN the rollback
# undoes both. SQLAlchemy shows every statement it sends to ``before_cursor_execute``; ``statement_kind.is_plain_read`` (an
# allowlist: an unknown statement is not a read) says whether it could have changed anything, and the answer is kept on the DBAPI
# connection's ``info`` -- the one place the statement listener (it has the connection, never the session) and the release (it has
# the session, and through it the connection) can both reach. Reset when a root transaction first meets the connection.
_NON_READ_STATEMENT = "_oo_txn_ran_a_non_read"

# The same count, taken one layer down: when the CONNECTION's transaction begins (the Engine ``begin`` event), which is before a Session
# that is later bound to that connection can begin. A Session joined to a connection that already had a transaction open (``Session(bind=
# connection)`` after writes on it) would otherwise record its baseline AFTER those writes, and the release would find "nothing changed"
# and roll them back (reproduced 2026-10-16 by the independent read). The Session's own baseline is the earlier of the two.
_CONNECTION_BEGAN_AT = "_oo_conn_txn_rows_changed"


def _driver_rows_changed(connection: Any) -> int | None:
    """Rows the DBAPI connection under the SQLAlchemy ``connection`` has changed since it was opened; ``None`` when it cannot say.

    Never raises: it runs when a transaction begins, on every session in the process."""
    try:
        count = connection.connection.dbapi_connection.total_changes
    except Exception:  # noqa: BLE001 - a driver that cannot count is "cannot say", and the release then declines
        return None
    return count if type(count) is int else None


@event.listens_for(Engine, "begin")
def _note_connection_transaction_start(conn) -> None:  # pragma: no cover - event
    """A transaction began on ``conn``: remember the driver's count of changed rows and forget the last transaction's statement flag.

    Both live on the DBAPI connection's ``info`` (it outlives the checkout, so the flag is cleared HERE, at every beginning, and never
    carries a schema change an earlier use of the pooled connection made into the next). A savepoint is not a ``begin``, so a nested
    transaction moves neither. Never raises: a count that could not be taken leaves the last one, which is older, and an older baseline
    can only make the release decline."""
    try:
        info = conn.info
        info[_CONNECTION_BEGAN_AT] = _driver_rows_changed(conn)
        info.pop(_NON_READ_STATEMENT, None)
    except Exception:  # noqa: BLE001 - see the docstring: the worst outcome is a declined release
        return


@event.listens_for(SASession, "after_begin")
def _note_rows_changed_at_begin(session, transaction, connection) -> None:  # pragma: no cover - event
    """Take the baseline the first time this ROOT transaction meets ``connection``; a savepoint beginning later must not move it.

    ``after_begin`` fires for a nested transaction too. Measured 2026-10-16: an unseen write, then a savepoint that began and
    ended, and the baseline had moved up to the count with the write in it -- the release then found "nothing changed" and the
    rollback discarded the row. The count is the one the connection's own transaction recorded when it began
    (:func:`_note_connection_transaction_start`) when that is at hand and not newer than the driver's now, so a Session that joins a
    connection with writes already on it does not take them for its starting point."""
    baseline = session.info.setdefault(_CHANGES_BASELINE, {})
    if id(connection) in baseline:
        return
    started = _driver_rows_changed(connection)
    try:
        earlier = connection.info.get(_CONNECTION_BEGAN_AT)
    except Exception:  # noqa: BLE001 - no earlier count to compare with: the count above stands
        earlier = None
    if type(earlier) is int and type(started) is int and earlier <= started:
        started = earlier
    baseline[id(connection)] = started


@event.listens_for(Engine, "before_cursor_execute")
def _note_statement_that_is_not_a_read(conn, cursor, statement, parameters, context, executemany) -> None:  # pragma: no cover - event
    if not _is_plain_read(statement):
        conn.info[_NON_READ_STATEMENT] = True


@event.listens_for(SASession, "after_transaction_end")
def _clear_wrote(session, transaction) -> None:  # pragma: no cover - event
    if transaction.parent is None:
        session.info.pop(_WROTE_FLAG, None)
        session.info.pop(_CHANGES_BASELINE, None)


def release_idle_connection(session: SASession) -> bool:
    """End ``session``'s READ transaction so its pooled connection goes back.

    S1.0. A ``Session`` holds a DBAPI connection only while a transaction is open
    and re-acquires one transparently on its next statement — measured here on
    SQLAlchemy 2.0.52 with this project's own pool settings (fresh 0, a read 1,
    ``rollback()`` 0, the next read 1 again).

    WHAT THIS BUYS, measured rather than assumed. Ending the transaction does NOT
    free a resident connection's page cache: a 64 MiB warm cache stayed at
    112.5 MB RSS across ``rollback()`` + ``malloc_trim`` and fell to 46 MB only on
    ``PRAGMA shrink_memory`` or ``close()``. What it changes is how MANY
    connections exist at once. Before, each collector worker held one from its
    first read until its feed bookkeeping committed — across the feed fetch and
    every article fetch — so 50 workers meant 50 warm connections, 42 of them
    ``max_overflow`` connections this pool CLOSES on return. Releasing between
    statements collapses simultaneous checkouts to the number of statements
    actually running, so those overflow connections are largely never created,
    and any that are hand their cache back when they close. The ``pool_size``
    core stays resident with its cache by design, at every worker count: that
    floor is S1.1's job, not this one's.

    Two further effects, and on the field evidence they are the stronger
    argument: the worker no longer pins a WAL read snapshot across a Tor fetch
    (the "a long-lived reader blocks a checkpoint" note on all three 2026-09-02
    bundles), and the read-then-write window that produces ``SQLITE_BUSY_SNAPSHOT``
    — the fleet's most frequent recorded error — shrinks to the statements
    themselves.

    COST, stated because it is real and unpriced elsewhere: a re-acquire that the
    pool cannot satisfy opens a physical connection, and on the encrypted store
    that re-derives the SQLCipher key (~160-173 ms). Measured at 50 workers, the
    multiplier is dominated by ``pool_size`` — 13.9x at pool 2, 3.9x at pool 6,
    1.0x at pool 8 — which is why S1.1's small tier is shaped for slots rather
    than for the smallest possible floor.

    WHAT THE GUARD CAN AND CANNOT SEE. ``session.new/dirty/deleted`` describe
    pending, UN-FLUSHED unit-of-work state. They are all empty once a caller has
    flushed, while the rows sit unwritten in the open transaction — and
    ``Session.rollback()`` rolls back to the ROOT, so it would discard them and
    would destroy an enclosing ``begin_nested()`` savepoint as well. Three
    further checks close that: an active savepoint, and the single-writer gate's
    own ``session.info`` flag, which ``writer.py`` sets on the first flush or bulk
    DML and clears at the outermost transaction end — i.e. exactly "this
    transaction has written". Bulk ``session.execute(insert()/update()/delete())``
    leaves no ORM state at all and is caught only by that flag.

    A write that goes ROUND the ORM -- ``session.connection().execute(...)``, a
    Core or textual statement on that connection, the DBAPI cursor -- sets none of
    those, and a rollback discards it without a sound (measured 2026-10-06 by the
    deep read of the read-chunking change: both writes lost). The DRIVER knows:
    ``total_changes``, the rows INSERT / UPDATE / DELETE have changed on the
    connection since it was opened, is recorded when the session's transaction
    begins (:func:`_note_rows_changed_at_begin`) and read again here; any
    difference declines, and so does a count that cannot be read, a transaction
    with no recorded start, and a session bound to more than one connection. Why
    not SQLite's ``in_transaction``: it is True for an explicit BEGIN (the recipe
    ``read_snapshot.py`` uses, and what the all-diagnostics build's members leave
    open, the pin this helper is there to give back between members) exactly as it
    is for a write, so it cannot tell the two apart
    (``tests/test_all_diag_read_release.py::test_a_pinned_snapshot_is_released_at_the_boundary_so_the_log_can_be_checkpointed``
    is the test a plain flag reddens).

    The count does not move for a schema change (CREATE / DROP / ALTER) or a
    PRAGMA that writes the header, and under an explicit BEGIN a rollback undoes
    both. :func:`_note_statement_that_is_not_a_read` therefore flags, on the
    connection, any statement SQLAlchemy sent that is not a plain read
    (``statement_kind.is_plain_read``, an allowlist), and the release declines
    when the flag is set. WHAT IT STILL CANNOT SEE: a schema change or header
    PRAGMA sent straight to the DBAPI cursor (``connection.connection.cursor()``),
    which bypasses SQLAlchemy's statement events and moves no row count -- no
    caller in this repository does that on a session's connection.

    Three edges of "the connection the transaction holds". (1) A transaction that has not met a connection yet holds nothing: it is
    declined without asking the session for one, because asking CHECKS ONE OUT (a physical connect, and on the encrypted store a key
    derivation, or a wait on an exhausted pool) only to roll it back. (2) A connection the pool DISCARDED under the transaction (the
    damage observer does it after a read of a damaged page) took everything the transaction ran with it, and the session cannot run
    another statement until it is rolled back, so the rollback is made: declining would leave every later reader of the session
    raising ``PendingRollbackError`` (the all-diagnostics build lost every member after the damaged one). (3) A Session joined to a
    connection that already had a transaction takes the count from the connection's own beginning (:func:`_note_connection_transaction_start`),
    so writes made on it before the Session began are still seen.

    The statement listener costs, measured by the independent read of this change on a plaintext file with trivial ``SELECT``s: about
    1.5 microseconds per statement on an engine that already had listeners (every engine the app builds does), and about 5 on one that
    had none, because registering on the ``Engine`` class turns event dispatch on for every engine in the process (the classifier alone
    is 0.38 for a ``SELECT``, 1.25 for a ``PRAGMA``). The app's main engine runs pysqlite in its legacy mode, where DDL outside a
    transaction a DML opened autocommits, so the flag protects a narrow case there (a DML that matched no row, then DDL or a header
    PRAGMA); under an explicit BEGIN, the ``read_snapshot`` recipe and the tests, it protects every schema change.
    A read-only savepoint that is rolled back (``ROLLBACK TO SAVEPOINT`` is not a plain read) also declines the release for the rest of
    its transaction; nothing is lost.

    So: this releases a session that has READ and not yet written. Anything else
    is declined — slower, never wrong. Returns whether a connection was handed
    back, so a caller can REPORT the effect instead of assuming it. Never raises.
    """
    try:
        # Un-flushed ORM work: a rollback would discard it outright.
        if session.new or session.dirty or session.deleted:
            return False
        # Flushed-but-uncommitted work, and bulk DML that leaves no ORM state.
        # Two independent markers, deliberately: our own (set for EVERY session in
        # the process by the listeners below) and the single-writer gate's, so a
        # session that is gated but somehow missed by ours is still declined.
        if session.info.get(_WROTE_FLAG) or session.info.get(_WRITE_GATE_SESSION_FLAG):
            return False
        # A rollback would roll back to the ROOT, not to the savepoint, taking
        # the caller's enclosing block with it.
        if session.in_nested_transaction():
            return False
        if not session.in_transaction():
            return False
        # No connection recorded for this transaction (it began and has not run a statement): nothing is held, so nothing is given
        # back, and asking the session for its connection would CHECK ONE OUT (a physical connect and a key derivation on the
        # encrypted store, a wait on an exhausted pool) only to roll it back.
        began_at = session.info.get(_CHANGES_BASELINE) or {}
        if not began_at:
            return False
        # The connection the transaction holds is dead (a damaged page invalidated it): what ran on it is gone with it, the session
        # cannot run another statement until it is rolled back, and the rollback below loses nothing. Declining here would leave
        # every later reader of this session raising ``PendingRollbackError``. Otherwise: a write that went round the ORM is a
        # statement that is not a plain read (a schema change or a header PRAGMA move no row count), then the driver's own count of
        # changed rows against the one taken when the transaction began (see ``_CHANGES_BASELINE``). Unreadable, unrecorded or
        # different: declined.
        connection = session.connection()
        if getattr(connection, "invalidated", False) is not True:
            if connection.info.get(_NON_READ_STATEMENT):
                return False
            before = began_at.get(id(connection)) if len(began_at) == 1 else None
            now = _driver_rows_changed(connection)
            if before is None or now is None or now != before:
                return False
        session.rollback()
        return True
    except Exception as exc:  # noqa: BLE001 - releasing early is never worth an error
        log_failure(_LOG, "release_idle_connection: could not end the transaction", exc, level=logging.DEBUG)
        return False


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
    except Exception as exc:  # noqa: BLE001 - cleanup must never raise
        log_failure(_LOG, "write-gate safety release failed", exc, level=logging.DEBUG)


def dispose_engine() -> None:
    """Dispose the engine's connection pool (call on app shutdown)."""
    engine.dispose()
