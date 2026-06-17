"""
Database maintenance: hot-path indexes, boot-time optimizer stats, statement
deadlines and the on-demand VACUUM tool (the 0.09 performance batch).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Honesty rules:
  * Everything here is mechanical database upkeep — no data is interpreted,
    no scores are computed.
  * Each helper degrades loudly: a deadline aborts with a typed error the API
    maps to an honest 503; VACUUM reports real before/after bytes; nothing is
    silently skipped.
  * mmap is applied to PLAINTEXT stores only — SQLCipher pages cannot be
    memory-mapped through the codec (each page must pass the decrypt), so
    setting it there would claim a speed-up that cannot exist.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.engine import Engine

_LOG = logging.getLogger("database.maintenance")

# The keyword analytics aggregate SUM(count)/COUNT(DISTINCT article_id)/
# MIN-MAX(observed_on) GROUP BY keyword_id over the whole mentions table
# (diagnostics export, insights top/trending). Without these payload columns
# in an index every row costs a table b-tree page read — a decrypt each,
# under SQLCipher. With them the scan is index-only. Mirrored in
# KeywordMention.__table_args__ (fresh DBs) and migration e2f3a4b5c6d7
# (alembic-managed DBs); this boot self-heal covers existing installs that
# don't run `make migrate` — create_all does not add indexes to existing
# tables (same pattern as ensure_fts).
HOT_INDEXES: dict[str, str] = {
    "ix_mention_covering": (
        "CREATE INDEX IF NOT EXISTS ix_mention_covering ON keyword_mentions "
        "(keyword_id, article_id, count, observed_on)"
    ),
}


def ensure_hot_indexes(engine: Engine) -> list[str]:
    """Create any missing hot-path indexes (idempotent). Returns those created."""
    if engine.url.get_backend_name() != "sqlite":
        return []
    created: list[str] = []
    with engine.begin() as conn:
        existing = {
            r[0]
            for r in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='index'")
            ).fetchall()
        }
        for name, ddl in HOT_INDEXES.items():
            if name not in existing:
                conn.execute(text(ddl))
                created.append(name)
    if created:
        _LOG.info(f"created hot-path index(es): {', '.join(created)}")
    return created


# De-churn backoff columns on feed_fetch_state (field log finding F). create_all
# materialises a MISSING table but never adds columns to an existing one, and not
# every install runs `make migrate`, so an install that already has
# feed_fetch_state (from the conditional-GET ship) needs these added at boot.
# Same self-heal pattern as ensure_hot_indexes; idempotent (checks PRAGMA first).
_FEED_BACKOFF_COLUMNS: dict[str, str] = {
    "consecutive_unchanged": "ALTER TABLE feed_fetch_state ADD COLUMN consecutive_unchanged INTEGER",
    "skip_until": "ALTER TABLE feed_fetch_state ADD COLUMN skip_until DATETIME",
}


def ensure_feed_backoff_columns(engine: Engine) -> list[str]:
    """Add the missing per-feed backoff columns to feed_fetch_state (idempotent).

    Returns the column names added. No-op on a fresh DB (create_all already built
    them from the model) or a non-sqlite backend or if the table doesn't exist yet.
    """
    if engine.url.get_backend_name() != "sqlite":
        return []
    added: list[str] = []
    with engine.begin() as conn:
        has_table = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='feed_fetch_state'")
        ).fetchone()
        if not has_table:
            return []
        existing = {
            r[1] for r in conn.execute(text("PRAGMA table_info(feed_fetch_state)")).fetchall()
        }
        for name, ddl in _FEED_BACKOFF_COLUMNS.items():
            if name not in existing:
                conn.execute(text(ddl))
                added.append(name)
    if added:
        _LOG.info(f"added feed_fetch_state backoff column(s): {', '.join(added)}")
    return added


_ARTICLE_ANALYSIS_COLUMNS: dict[str, str] = {
    "prompt_text": "ALTER TABLE article_analyses ADD COLUMN prompt_text TEXT",
}


def ensure_article_analysis_columns(engine: Engine) -> list[str]:
    """Add the missing article_analyses columns (idempotent).

    The live DB is never auto-upgraded by alembic (only staged copies are), so a new
    column the model expects must be self-healed at boot for existing stores, exactly
    like the feed-backoff columns. No-op on a fresh DB (create_all built them) or a
    non-sqlite backend or if the table doesn't exist yet.
    """
    if engine.url.get_backend_name() != "sqlite":
        return []
    added: list[str] = []
    with engine.begin() as conn:
        has_table = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='article_analyses'")
        ).fetchone()
        if not has_table:
            return []
        existing = {
            r[1] for r in conn.execute(text("PRAGMA table_info(article_analyses)")).fetchall()
        }
        for name, ddl in _ARTICLE_ANALYSIS_COLUMNS.items():
            if name not in existing:
                conn.execute(text(ddl))
                added.append(name)
    if added:
        _LOG.info(f"added article_analyses column(s): {', '.join(added)}")
    return added


def optimize_at_boot(engine: Engine) -> dict:
    """Refresh the query planner's statistics, bounded (PRAGMA analysis_limit).

    `PRAGMA optimize` analyzes only tables whose stats are missing/stale, so
    repeat boots are near-free; the first boot on a large corpus pays a bounded
    scan (analysis_limit caps pages examined per index). Returns what was done
    with the real duration — never blocks startup (caller wraps best-effort).
    """
    if engine.url.get_backend_name() != "sqlite":
        return {"skipped": "non-sqlite backend"}
    t0 = time.perf_counter()
    with engine.begin() as conn:
        conn.execute(text("PRAGMA analysis_limit=1000"))
        had_stats = bool(
            conn.execute(
                text("SELECT name FROM sqlite_master WHERE name='sqlite_stat1'")
            ).fetchone()
        )
        if not had_stats:
            # First boot at this schema: seed the stat tables (bounded scan).
            conn.execute(text("ANALYZE"))
        conn.execute(text("PRAGMA optimize"))
    out = {"analyzed_fresh": not had_stats, "duration_ms": round((time.perf_counter() - t0) * 1000)}
    _LOG.info(f"planner statistics refreshed: {out}")
    return out


class StatementTimeout(RuntimeError):
    """A read exceeded its deadline and was aborted (loud, typed — the API
    maps this to HTTP 503 with the deadline stated, never a hung request)."""


def _deadline_seconds() -> float:
    """Heavy-read deadline in seconds (OO_STATEMENT_TIMEOUT_S; 0 disables)."""
    try:
        return float(os.environ.get("OO_STATEMENT_TIMEOUT_S", "60"))
    except ValueError:
        return 60.0


@contextmanager
def statement_deadline(session, seconds: float | None = None) -> Iterator[None]:
    """Abort the session's SQLite statements if they run past ``seconds``.

    Uses the driver progress handler (fires every N VM opcodes; returning
    nonzero interrupts the statement), so a runaway aggregation ends with a
    typed StatementTimeout instead of an unbounded hang. Read paths only —
    an aborted write would roll back, but none of the wrapped endpoints write.
    No-op for non-SQLite backends or when the deadline is 0/None.
    """
    limit = _deadline_seconds() if seconds is None else seconds
    raw = session.connection().connection.dbapi_connection
    if not limit or limit <= 0 or not hasattr(raw, "set_progress_handler"):
        yield
        return
    started = time.monotonic()

    def _check() -> int:
        return 1 if (time.monotonic() - started) > limit else 0

    raw.set_progress_handler(_check, 20_000)
    try:
        yield
    except Exception as exc:
        # Both sqlite3 and sqlcipher3 surface an interrupt as OperationalError;
        # translate only when WE caused it (the deadline elapsed).
        if (time.monotonic() - started) > limit and "interrupt" in str(exc).lower():
            raise StatementTimeout(
                f"statement exceeded the {limit:.0f}s deadline and was aborted"
            ) from exc
        raise
    finally:
        raw.set_progress_handler(None, 0)


def vacuum_database(engine: Engine) -> dict:
    """VACUUM the main store + refresh planner stats; report real numbers.

    Rebuilds the database file, returning freed pages to the filesystem
    (deletes/retractions leave free pages that only VACUUM reclaims). Honest
    costs, stated to the caller: the rebuild takes time proportional to the
    file and blocks writers for the duration (readers continue via WAL).
    Works identically on SQLCipher stores (pages re-encrypt on write).
    """
    if engine.url.get_backend_name() != "sqlite":
        return {"supported": False, "detail": "VACUUM tool applies to SQLite stores only"}
    db_path = engine.url.database
    size_before = os.path.getsize(db_path) if db_path and os.path.exists(db_path) else None
    t0 = time.perf_counter()
    # VACUUM is a raw-SQL write that takes an exclusive lock; route it through
    # the single-writer gate so it queues with collection/import writers instead
    # of racing them on the SQLite lock (it bypasses the ORM-flush hook).
    from src.database.writer import write_lock

    with write_lock(), engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        freelist_before = conn.execute(text("PRAGMA freelist_count")).scalar() or 0
        conn.execute(text("VACUUM"))
        conn.execute(text("PRAGMA analysis_limit=1000"))
        conn.execute(text("PRAGMA optimize"))
        freelist_after = conn.execute(text("PRAGMA freelist_count")).scalar() or 0
    size_after = os.path.getsize(db_path) if db_path and os.path.exists(db_path) else None
    return {
        "supported": True,
        "bytes_before": size_before,
        "bytes_after": size_after,
        "bytes_reclaimed": (size_before - size_after)
        if size_before is not None and size_after is not None
        else None,
        "freelist_pages_before": int(freelist_before),
        "freelist_pages_after": int(freelist_after),
        "duration_ms": round((time.perf_counter() - t0) * 1000),
        "method": (
            "SQLite VACUUM (full file rebuild; frees unused pages) followed by "
            "PRAGMA optimize. Real byte sizes from the filesystem."
        ),
    }
