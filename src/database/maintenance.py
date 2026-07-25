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
    # Covering index for the time-windowed trending aggregation (the #1 perf
    # hotspot; see the KeywordMention model). Leads with observed_on so
    # `SUM(count) WHERE observed_on IN [lo,hi) GROUP BY keyword_id` becomes an
    # index-only range scan instead of a heap page read (a decrypt) per row.
    "ix_mention_date_keyword": (
        "CREATE INDEX IF NOT EXISTS ix_mention_date_keyword ON keyword_mentions "
        "(observed_on, keyword_id, count)"
    ),
    # Expression index on the article "observed date" = coalesce(published_at,
    # created_at) (field-test 2026-07-08 Item 8 P0, the single biggest cost).
    # The corpus date-range probe `min(coalesce(..)), max(coalesce(..))` and the
    # `>= cutoff` range filters in integrity/link-analysis/analytics all wrote a
    # bare `SCAN articles`, dragging every ~35 KB article row (content column)
    # through the SQLCipher codec (measured 4,775 ms x 154 calls = 735 s). With
    # this index those plans become index-only (`SCAN/SEARCH articles USING
    # COVERING INDEX ix_article_observed`). SQLite matches an expression index
    # ONLY when the query expression is written identically; every call site
    # already uses func.coalesce(Article.published_at, Article.created_at), and
    # SQLite normalises the qualified query form against this unqualified index
    # expression. Byte-identical to migration 5ea842778603 (keep in lock-step).
    # NOT on the ORM model: SQLAlchemy cannot reflect expression indexes, so
    # `alembic check` never sees it -- the migration + this self-heal are the
    # two canonical creators, exactly like the mention indexes above.
    "ix_article_observed": (
        "CREATE INDEX IF NOT EXISTS ix_article_observed "
        "ON articles (coalesce(published_at, created_at))"
    ),
    # Covering index for /api/insights/map-coverage's per-source-country GROUP BY
    # (queries.source_country_counts; PR #740/#744 remediation, field-diagnostics
    # #728 item 9.2). EXPLAIN QUERY PLAN confirmed the existing idx_article_source_id
    # is a plain SEARCH (not COVERING) for this query, so every matching row still
    # costs a table page read -- a decrypt, under SQLCipher -- just to read
    # sentiment_score. Mirrored in Article.__table_args__ (fresh DBs) and migration
    # 04c029205aa8 (alembic-managed DBs); this boot self-heal covers existing
    # installs that don't run `make migrate`.
    "idx_article_source_sentiment": (
        "CREATE INDEX IF NOT EXISTS idx_article_source_sentiment "
        "ON articles (source_id, sentiment_score)"
    ),
    # S3.2 (2026-07-23 field-feedback workflow): every search/browse query filters on
    # articles.quarantined -- mirrored on the ORM model's __table_args__ (fresh DBs) +
    # the migration (alembic-managed DBs); this boot self-heal covers existing installs
    # that don't run `make migrate`.
    "idx_article_quarantined": (
        "CREATE INDEX IF NOT EXISTS idx_article_quarantined ON articles (quarantined)"
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


# K1/K2 identity seams (data-architecture Slice 5): content_multihash + canon_version
# on articles, for stores created before these columns existed. Additive + nullable; the
# backfill is a pure string op over the small `hash`/`canonical_url` columns (no content
# decrypt), so it is cheap even on a large encrypted corpus.
_ARTICLE_IDENTITY_COLUMNS: dict[str, str] = {
    "content_multihash": "ALTER TABLE articles ADD COLUMN content_multihash VARCHAR(80)",
    "canon_version": "ALTER TABLE articles ADD COLUMN canon_version VARCHAR(16)",
}


def ensure_article_identity_columns(engine: Engine) -> list[str]:
    """Self-heal ``articles.content_multihash`` / ``canon_version`` + backfill them.

    Mirrors the other self-heals (the live DB never auto-runs alembic). content_multihash
    is backfilled as ``sha2-256:<hash>`` for rows whose hash is a 64-char SHA-256 digest
    (every ingest path produces one) — never a fabricated label for an odd hash; the
    bare-hex dedup ``hash`` is untouched. canon_version is backfilled to the current
    ``CANON_VERSION`` for existing rows (they WERE canonicalised by the current rules).
    Idempotent; no-op on a fresh DB / non-sqlite / missing table.
    """
    if engine.url.get_backend_name() != "sqlite":
        return []
    from src.utils.url_utils import CANON_VERSION, CONTENT_HASH_ALGO

    added: list[str] = []
    with engine.begin() as conn:
        has_table = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='articles'")
        ).fetchone()
        if not has_table:
            return []
        existing = {r[1] for r in conn.execute(text("PRAGMA table_info(articles)")).fetchall()}
        for name, ddl in _ARTICLE_IDENTITY_COLUMNS.items():
            if name not in existing:
                conn.execute(text(ddl))
                added.append(name)
    if added:
        with engine.begin() as conn:
            if "content_multihash" in added:
                conn.execute(
                    text(
                        "UPDATE articles SET content_multihash = :pfx || hash "
                        "WHERE content_multihash IS NULL AND length(hash) = 64"
                    ),
                    {"pfx": f"{CONTENT_HASH_ALGO}:"},
                )
            if "canon_version" in added:
                conn.execute(
                    text("UPDATE articles SET canon_version = :v WHERE canon_version IS NULL"),
                    {"v": CANON_VERSION},
                )
        _LOG.info(f"added + backfilled articles identity column(s): {', '.join(added)}")
    return added


# Source IP provenance (data-architecture Slice 6a): server_ip / ip_observed_at /
# server_ip_reason on articles, for stores created before these columns existed. All
# nullable, NO backfill -- a pre-existing article simply has no captured server IP
# (honest NULL), and future fetches populate it forward via the pipeline.
_ARTICLE_IP_COLUMNS: dict[str, str] = {
    "server_ip": "ALTER TABLE articles ADD COLUMN server_ip VARCHAR(45)",
    "ip_observed_at": "ALTER TABLE articles ADD COLUMN ip_observed_at DATETIME",
    "server_ip_reason": "ALTER TABLE articles ADD COLUMN server_ip_reason VARCHAR(64)",
}


def ensure_article_ip_columns(engine: Engine) -> list[str]:
    """Self-heal the source-IP columns on ``articles`` (idempotent, additive).

    No backfill: existing articles have no captured server IP (honest NULL); the fetch
    pipeline populates them forward. No-op on a fresh DB / non-sqlite / missing table.
    """
    if engine.url.get_backend_name() != "sqlite":
        return []
    added: list[str] = []
    with engine.begin() as conn:
        has_table = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='articles'")
        ).fetchone()
        if not has_table:
            return []
        existing = {r[1] for r in conn.execute(text("PRAGMA table_info(articles)")).fetchall()}
        for name, ddl in _ARTICLE_IP_COLUMNS.items():
            if name not in existing:
                conn.execute(text(ddl))
                added.append(name)
    if added:
        _LOG.info(f"added articles source-IP column(s): {', '.join(added)}")
    return added


# QUARANTINE columns (S3.2, 2026-07-23 field-feedback workflow). Additive + NULLABLE,
# no backfill -- an existing article simply has quarantined=NULL ("never judged"),
# treated identically to False by every reader (Article.quarantined.isnot(True)). Same
# self-heal pattern as the IP/identity columns.
_ARTICLE_QUARANTINE_COLUMNS: dict[str, str] = {
    "quarantined": "ALTER TABLE articles ADD COLUMN quarantined BOOLEAN",
    "quarantine_reason": "ALTER TABLE articles ADD COLUMN quarantine_reason VARCHAR(255)",
    "quarantine_criteria_version": "ALTER TABLE articles ADD COLUMN quarantine_criteria_version VARCHAR(40)",
    "quarantined_at": "ALTER TABLE articles ADD COLUMN quarantined_at DATETIME",
}


def ensure_article_quarantine_columns(engine: Engine) -> list[str]:
    """Self-heal the quarantine columns on ``articles`` (idempotent, additive).

    No backfill: an existing article has quarantined=NULL (never judged), identical in
    meaning to quarantined=False. No-op on a fresh DB / non-sqlite / missing table."""
    if engine.url.get_backend_name() != "sqlite":
        return []
    added: list[str] = []
    with engine.begin() as conn:
        has_table = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='articles'")
        ).fetchone()
        if not has_table:
            return []
        existing = {r[1] for r in conn.execute(text("PRAGMA table_info(articles)")).fetchall()}
        for name, ddl in _ARTICLE_QUARANTINE_COLUMNS.items():
            if name not in existing:
                conn.execute(text(ddl))
                added.append(name)
    if added:
        _LOG.info(f"added articles quarantine column(s): {', '.join(added)}")
    return added


# Secondary/deduced language column (field §2.6). Same additive self-heal as the IP /
# identity columns: create_all builds it on a fresh DB, this ALTERs an existing one, and
# not every install runs alembic. No backfill -- it populates forward at ingest/re-index
# (only for articles whose authoritative `language` is NULL).
_ARTICLE_DETECTED_LANG_COLUMN: dict[str, str] = {
    "detected_language": "ALTER TABLE articles ADD COLUMN detected_language VARCHAR(10)",
}


def ensure_article_detected_language_column(engine: Engine) -> list[str]:
    """Self-heal the ``articles.detected_language`` column (idempotent, additive)."""
    if engine.url.get_backend_name() != "sqlite":
        return []
    added: list[str] = []
    with engine.begin() as conn:
        has_table = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='articles'")
        ).fetchone()
        if not has_table:
            return []
        existing = {r[1] for r in conn.execute(text("PRAGMA table_info(articles)")).fetchall()}
        for name, ddl in _ARTICLE_DETECTED_LANG_COLUMN.items():
            if name not in existing:
                conn.execute(text(ddl))
                added.append(name)
    if added:
        _LOG.info(f"added articles deduced-language column(s): {', '.join(added)}")
    return added


# Q4a: the discovery funnel's resolution-table provenance. Additive, NO backfill -- it populates
# forward as discovery resolves a domain (a pre-existing row stays NULL until re-resolved).
_EXTERNAL_SOURCE_DISCOVERY_COLUMNS: dict[str, str] = {
    "discovered_via": "ALTER TABLE external_sources ADD COLUMN discovered_via VARCHAR(60)",
}


def ensure_external_source_discovery_columns(engine: Engine) -> list[str]:
    """Self-heal the ``external_sources.discovered_via`` provenance column (idempotent, additive)."""
    if engine.url.get_backend_name() != "sqlite":
        return []
    added: list[str] = []
    with engine.begin() as conn:
        has_table = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='external_sources'")
        ).fetchone()
        if not has_table:
            return []
        existing = {r[1] for r in conn.execute(text("PRAGMA table_info(external_sources)")).fetchall()}
        for name, ddl in _EXTERNAL_SOURCE_DISCOVERY_COLUMNS.items():
            if name not in existing:
                conn.execute(text(ddl))
                added.append(name)
    if added:
        _LOG.info(f"added external_sources discovery column(s): {', '.join(added)}")
    return added


# Law versioned-text columns (the versioned-sources ruling): the materialised latest + per-revision
# full text so the current law shows without replaying diffs and any past version reconstructs.
# Additive, no backfill (populates forward as the tracker stores full text).
_LAW_DOCUMENT_TEXT_COLUMNS: dict[str, str] = {
    "latest_text": "ALTER TABLE law_documents ADD COLUMN latest_text BLOB",
    "latest_text_revid": "ALTER TABLE law_documents ADD COLUMN latest_text_revid INTEGER",
}
_LAW_REVISION_TEXT_COLUMNS: dict[str, str] = {
    "full_text": "ALTER TABLE law_revisions ADD COLUMN full_text BLOB",
}


def ensure_law_text_columns(engine: Engine) -> list[str]:
    """Self-heal the law versioned-text columns (law_documents.latest_text/_revid,
    law_revisions.full_text) — idempotent, additive. Literal-string SQL (no f-string) so bandit
    B608 stays clean; table names are fixed constants either way."""
    if engine.url.get_backend_name() != "sqlite":
        return []
    added: list[str] = []
    with engine.begin() as conn:
        if conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='law_documents'")
        ).fetchone():
            existing = {r[1] for r in conn.execute(text("PRAGMA table_info(law_documents)")).fetchall()}
            for name, ddl in _LAW_DOCUMENT_TEXT_COLUMNS.items():
                if name not in existing:
                    conn.execute(text(ddl))
                    added.append(f"law_documents.{name}")
        if conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='law_revisions'")
        ).fetchone():
            existing = {r[1] for r in conn.execute(text("PRAGMA table_info(law_revisions)")).fetchall()}
            for name, ddl in _LAW_REVISION_TEXT_COLUMNS.items():
                if name not in existing:
                    conn.execute(text(ddl))
                    added.append(f"law_revisions.{name}")
    if added:
        _LOG.info(f"added law versioned-text column(s): {', '.join(added)}")
    return added


# S4b (the Cambodia fix, law-vertical brief 2026-07-17): law_documents.language/.country
# thread the catalog's OWN asserted per-document language/country to the corpus Article
# (src/law/corpus.py). Additive, no backfill: a pre-existing document heals forward the
# next time register_documents re-reads the catalog (which also heals the ALREADY-
# INGESTED Article in the same pass), never guessed retroactively.
_LAW_DOCUMENT_LANGUAGE_COLUMNS: dict[str, str] = {
    "language": "ALTER TABLE law_documents ADD COLUMN language VARCHAR(8)",
    "country": "ALTER TABLE law_documents ADD COLUMN country VARCHAR(8)",
}


def ensure_law_document_language_columns(engine: Engine) -> list[str]:
    """Self-heal ``law_documents.language`` / ``.country`` (idempotent, additive)."""
    if engine.url.get_backend_name() != "sqlite":
        return []
    added: list[str] = []
    with engine.begin() as conn:
        if conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='law_documents'")
        ).fetchone():
            existing = {r[1] for r in conn.execute(text("PRAGMA table_info(law_documents)")).fetchall()}
            for name, ddl in _LAW_DOCUMENT_LANGUAGE_COLUMNS.items():
                if name not in existing:
                    conn.execute(text(ddl))
                    added.append(f"law_documents.{name}")
    if added:
        _LOG.info(f"added law_documents language column(s): {', '.join(added)}")
    return added


def ensure_keyword_mention_source_column(engine: Engine) -> list[str]:
    """Self-heal the denormalised ``keyword_mentions.source_id`` column + its index.

    Additive, NO backfill: a re-index fills it forward (index_article sets it from the
    article's source) -- deliberately NOT a multi-million-row boot UPDATE join. So
    per-source analytics (flood/bury) grow as the corpus is re-indexed. Idempotent.
    """
    if engine.url.get_backend_name() != "sqlite":
        return []
    added: list[str] = []
    with engine.begin() as conn:
        has_table = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='keyword_mentions'")
        ).fetchone()
        if not has_table:
            return []
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(keyword_mentions)")).fetchall()}
        if "source_id" not in cols:
            conn.execute(text("ALTER TABLE keyword_mentions ADD COLUMN source_id INTEGER"))
            added.append("source_id")
        idx = {r[1] for r in conn.execute(text("PRAGMA index_list(keyword_mentions)")).fetchall()}
        if "ix_keyword_mentions_source_id" not in idx:
            conn.execute(
                text("CREATE INDEX ix_keyword_mentions_source_id ON keyword_mentions(source_id)")
            )
            added.append("ix_keyword_mentions_source_id")
    if added:
        _LOG.info(f"added keyword_mentions source denormalisation: {', '.join(added)}")
    return added


_SOURCE_COUNTER_COLUMNS: dict[str, str] = {
    # S6 (2026-07-14). Nullable, NO backfill: NULL = "never reconciled" -> the read falls
    # back to a live COUNT(*) (never wrong), and reconcile_source_counters() populates it
    # forward + stamps the freshness watermark. Same additive self-heal pattern as the
    # keyword-source / law-text columns; idempotent (PRAGMA-checked).
    "article_count": "ALTER TABLE sources ADD COLUMN article_count INTEGER",
    "counter_reconciled_at": "ALTER TABLE sources ADD COLUMN counter_reconciled_at DATETIME",
}


# Populate the per-source counter from the live article rows in one pass, stamping the
# freshness watermark, so there is NO NULL window after boot (a NULL counter would make the
# "articles" sort order on NULL while the row displays a live count — the skeptic's finding).
# Cheap: one correlated COUNT over the indexed articles.source_id per source (sources are few).
_SOURCE_COUNTER_BACKFILL = (
    "UPDATE sources SET "
    "article_count = COALESCE("
    "(SELECT COUNT(*) FROM articles WHERE articles.source_id = sources.id), 0), "
    "counter_reconciled_at = CURRENT_TIMESTAMP"
)


# Qualification lifecycle STAMP columns (0.3 CLOSE GATE ruling, 2026-07-19/20) for
# stores created before they existed. ``status`` gets a real DEFAULT so every existing
# row is immediately, honestly 'unqualified' (no NULL window, no silent admission); the
# one-time backfill below then promotes a source that ALREADY has collected articles to
# 'qualified' -- "the first collect pass over the catalog IS its qualification pass"
# (maintainer ruling): a source this store already scraped has already, de facto, passed
# its trial, so the admission gate must not suddenly starve an install that was already
# collecting. A source with zero articles ever collected stays 'unqualified' and enters
# the qualification job's normal candidate queue. Same additive self-heal pattern as
# ensure_source_counter_columns; idempotent (PRAGMA-checked).
_SOURCE_QUALIFICATION_COLUMNS: dict[str, str] = {
    "status": "ALTER TABLE sources ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'unqualified'",
    "qualified_at": "ALTER TABLE sources ADD COLUMN qualified_at DATETIME",
    "qualification_criteria_version": "ALTER TABLE sources ADD COLUMN qualification_criteria_version VARCHAR(40)",
}


def _source_qualification_backfill_sql() -> str:
    # Promote to 'qualified' only sources with >=1 already-collected article; the rest
    # keep the column DEFAULT ('unqualified'). Never touches a row the self-heal did not
    # just create (WHERE status = 'unqualified' AND ... -- a fresh column is always
    # 'unqualified' until this runs once, so this is safe to run only right after ADD).
    # criteria_version rides as a BOUND parameter (:criteria_version) -- the constant
    # SQL carries no interpolation, so the blocking bandit B608 gate has nothing to flag.
    return (
        "UPDATE sources SET "
        "status = 'qualified', "
        "qualified_at = CURRENT_TIMESTAMP, "
        "qualification_criteria_version = :criteria_version "
        "WHERE status = 'unqualified' "
        "AND (SELECT COUNT(*) FROM articles WHERE articles.source_id = sources.id) > 0"
    )


def ensure_source_qualification_columns(engine: Engine) -> list[str]:
    """Self-heal ``sources.status`` / ``.qualified_at`` / ``.qualification_criteria_version``
    (the admission-gate STAMP) on a store created before they existed, then BACKFILL:
    a source with an already-collected article is stamped 'qualified' (its first collect
    pass already served as its qualification pass); everything else stays 'unqualified'
    (the column default) and is picked up by the background qualification job. Additive,
    idempotent; the backfill runs ONLY when ``status`` was just added (a fresh DB gets it
    from create_all's own default, so no backfill would find anything unqualified with
    articles -- but running unconditionally after a fresh add is still a no-op there).
    """
    if engine.url.get_backend_name() != "sqlite":
        return []
    from src.catalog.qualification import CRITERIA_VERSION

    added: list[str] = []
    with engine.begin() as conn:
        if not conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='sources'")
        ).fetchone():
            return []
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(sources)")).fetchall()}
        for name, ddl in _SOURCE_QUALIFICATION_COLUMNS.items():
            if name not in cols:
                conn.execute(text(ddl))
                added.append(f"sources.{name}")
        if "sources.status" in added:
            conn.execute(
                text(_source_qualification_backfill_sql()),
                {"criteria_version": CRITERIA_VERSION},
            )
    if added:
        _LOG.info(f"added source qualification column(s): {', '.join(added)}")
    return added


# Crawl-supplement rotation marker (§8 crawl-by-default, 2026-07-24 throughput
# brief C3). Additive, NULLABLE, no backfill: an existing source simply reads
# as "never crawled by the supplement" (NULL sorts first in the rotation --
# the standing self-heal pattern, e.g. ensure_article_ip_columns).
_SOURCE_LAST_CRAWLED_COLUMN: dict[str, str] = {
    "last_crawled_at": "ALTER TABLE sources ADD COLUMN last_crawled_at DATETIME",
}


def ensure_source_last_crawled_column(engine: Engine) -> list[str]:
    """Self-heal ``sources.last_crawled_at`` on a store created before it existed."""
    if engine.url.get_backend_name() != "sqlite":
        return []
    added: list[str] = []
    with engine.begin() as conn:
        if not conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='sources'")
        ).fetchone():
            return []
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(sources)")).fetchall()}
        for name, ddl in _SOURCE_LAST_CRAWLED_COLUMN.items():
            if name not in cols:
                conn.execute(text(ddl))
                added.append(f"sources.{name}")
    if added:
        _LOG.info(f"added source last-crawled column(s): {', '.join(added)}")
    return added


def ensure_source_counter_columns(engine: Engine) -> list[str]:
    """Self-heal ``sources.article_count`` + ``sources.counter_reconciled_at`` (S6) on a store
    created before they existed, then BACKFILL from the live articles so there is no NULL window
    (a NULL counter would make the 'articles' sort disagree with the displayed live-fallback
    count). Additive, idempotent; the backfill runs ONLY when the count column was just added."""
    if engine.url.get_backend_name() != "sqlite":
        return []
    added: list[str] = []
    with engine.begin() as conn:
        if not conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='sources'")
        ).fetchone():
            return []
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(sources)")).fetchall()}
        for name, ddl in _SOURCE_COUNTER_COLUMNS.items():
            if name not in cols:
                conn.execute(text(ddl))
                added.append(f"sources.{name}")
        if "sources.article_count" in added:  # just created -> make it true at once
            conn.execute(text(_SOURCE_COUNTER_BACKFILL))
    if added:
        _LOG.info(f"added source counter column(s): {', '.join(added)}")
    return added


# Denormalised corpus-wide keyword counters (perf workstream 2026-06-18) for stores
# created before these columns existed. create_all builds them on a fresh DB but never
# ALTERs an existing table, and not every install runs alembic — so an existing corpus
# self-heals the columns here, then is POPULATED once from the live mentions (the
# columns are wrong-zero the instant they exist; the one-time backfill makes them true,
# and index_article keeps them true thereafter). Same self-heal pattern as the feed /
# analysis columns; idempotent (PRAGMA-checked).
_KEYWORD_COUNTER_COLUMNS: dict[str, str] = {
    "mention_count": "ALTER TABLE keywords ADD COLUMN mention_count INTEGER NOT NULL DEFAULT 0",
    "article_count": "ALTER TABLE keywords ADD COLUMN article_count INTEGER NOT NULL DEFAULT 0",
    # Freshness watermark for the counter honesty envelope (Slice 2). Nullable, no
    # default: a freshly self-healed column is NULL = "never reconciled" = honestly
    # `estimated` until the background reconcile stamps it. Adding it does NOT make
    # the counters wrong (they stay backfilled below), so it never forces a re-backfill.
    "last_reconciled_at": "ALTER TABLE keywords ADD COLUMN last_reconciled_at DATETIME",
}

# Populate both counters from the live mentions in one pass. Correlated subqueries
# (portable across every SQLite version) over the covering index ix_mention_covering,
# so each is an index-only scan; runs ONCE, only when a column was just added.
_KEYWORD_COUNTER_BACKFILL = (
    "UPDATE keywords SET "
    "mention_count = COALESCE("
    "(SELECT SUM(count) FROM keyword_mentions WHERE keyword_id = keywords.id), 0), "
    "article_count = COALESCE("
    "(SELECT COUNT(DISTINCT article_id) FROM keyword_mentions WHERE keyword_id = keywords.id), 0)"
)


def ensure_keyword_counter_columns(engine: Engine) -> list[str]:
    """Self-heal ``keywords.mention_count`` / ``article_count`` + their index, then
    backfill from the live mentions when freshly added (idempotent).

    Returns the column names added (empty when already present / fresh DB / non-sqlite /
    no keywords table). When ANY column is added the counters are wrong-zero, so a
    one-time backfill recomputes the true ``SUM(count)`` / ``COUNT(DISTINCT article_id)``
    — after which :func:`src.analytics.store.index_article` maintains them incrementally.
    """
    if engine.url.get_backend_name() != "sqlite":
        return []
    added: list[str] = []
    with engine.begin() as conn:
        has_table = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='keywords'")
        ).fetchone()
        if not has_table:
            return []
        existing = {r[1] for r in conn.execute(text("PRAGMA table_info(keywords)")).fetchall()}
        for name, ddl in _KEYWORD_COUNTER_COLUMNS.items():
            if name not in existing:
                conn.execute(text(ddl))
                added.append(name)
        # The ordered top-N scan index (depends on the column existing, so it is
        # created here rather than in HOT_INDEXES).
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_keyword_mention_count "
                "ON keywords (mention_count)"
            )
        )
    # Only a freshly-added VALUE column is wrong-zero and needs the (potentially
    # expensive) one-pass backfill. Adding the nullable `last_reconciled_at` watermark
    # alone must NOT trigger a full recompute of already-correct counters (it would pay
    # the whole GROUP BY at boot just to add a freshness column).
    if added and ({"mention_count", "article_count"} & set(added)):
        t0 = time.perf_counter()
        with engine.begin() as conn:
            conn.execute(text(_KEYWORD_COUNTER_BACKFILL))
        _LOG.info(
            "added keywords counter column(s) %s and backfilled from live mentions in %d ms",
            ", ".join(added),
            round((time.perf_counter() - t0) * 1000),
        )
    return added


# Keyword extractor provenance (migration c3d4e5f6a7b8) for stores whose `keywords`
# table predates the column (a 0.0.8 / early-0.09 store). The keyword_mentions table
# from the same migration needs no heal — create_all materialises a MISSING table in
# full — but `keywords` already existed, so the column must be ALTERed in. Same
# self-heal pattern as the counter columns; idempotent (PRAGMA-checked). No backfill:
# NULL extractor is the honest "provenance unrecorded" state for pre-existing rows.
_KEYWORD_EXTRACTOR_COLUMNS: dict[str, str] = {
    "extractor": "ALTER TABLE keywords ADD COLUMN extractor VARCHAR(40)",
}


def ensure_keyword_extractor_column(engine: Engine) -> list[str]:
    """Self-heal ``keywords.extractor`` (idempotent, additive; migration c3d4e5f6a7b8).

    The live DB is never auto-upgraded by alembic (only staged copies are), so a store
    created before this column existed would hit "no such column: keywords.extractor"
    on any Keyword ORM query. No-op on a fresh DB / non-sqlite / missing table.
    """
    if engine.url.get_backend_name() != "sqlite":
        return []
    added: list[str] = []
    with engine.begin() as conn:
        has_table = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='keywords'")
        ).fetchone()
        if not has_table:
            return []
        existing = {r[1] for r in conn.execute(text("PRAGMA table_info(keywords)")).fetchall()}
        for name, ddl in _KEYWORD_EXTRACTOR_COLUMNS.items():
            if name not in existing:
                conn.execute(text(ddl))
                added.append(name)
    if added:
        _LOG.info(f"added keywords column(s): {', '.join(added)}")
    return added


# Wiki living-source columns (migrations b6c7d8e9f0a1 + c9d8e7f6a5b4) for stores whose
# wiki tables predate them. latest_text / full_text are CompressedText in the model =
# BLOB at the SQL layer (the migrations used LargeBinary). Neither migration created an
# index on these columns, so columns are the whole heal. All nullable, NO backfill:
# an old page row simply has no stored latest/full text yet (honest NULL — the tracker
# populates them forward), no missing-verdict and no fetched categories.
_WIKI_PAGE_COLUMNS: dict[str, str] = {
    "latest_text": "ALTER TABLE wiki_pages ADD COLUMN latest_text BLOB",
    "latest_text_revid": "ALTER TABLE wiki_pages ADD COLUMN latest_text_revid INTEGER",
    "missing": "ALTER TABLE wiki_pages ADD COLUMN missing BOOLEAN",
    "wiki_categories": "ALTER TABLE wiki_pages ADD COLUMN wiki_categories TEXT",
}
_WIKI_REVISION_COLUMNS: dict[str, str] = {
    "full_text": "ALTER TABLE wiki_revisions ADD COLUMN full_text BLOB",
}


def ensure_wiki_text_columns(engine: Engine) -> list[str]:
    """Self-heal the wiki living-source columns (idempotent, additive).

    Covers migrations b6c7d8e9f0a1 (``wiki_pages.latest_text`` /
    ``latest_text_revid``, ``wiki_revisions.full_text``) and c9d8e7f6a5b4
    (``wiki_pages.missing`` / ``wiki_categories``) for stores created before those
    columns existed — the live DB never auto-runs alembic, so without this any
    WikiPage/WikiRevision ORM query on an old store raises "no such column".
    No-op on a fresh DB / non-sqlite / missing tables.
    """
    if engine.url.get_backend_name() != "sqlite":
        return []
    added: list[str] = []
    with engine.begin() as conn:
        for table, columns in (
            ("wiki_pages", _WIKI_PAGE_COLUMNS),
            ("wiki_revisions", _WIKI_REVISION_COLUMNS),
        ):
            has_table = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
                {"t": table},
            ).fetchone()
            if not has_table:
                continue
            existing = {
                r[1] for r in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            }
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(ddl))
                    added.append(f"{table}.{name}")
    if added:
        _LOG.info(f"added wiki column(s): {', '.join(added)}")
    return added


# Super-ring member marker (migration f4a5b6c7d8e9) for stores whose
# keyword_supergroup_members table predates it. Nullable, no index in the migration,
# NO backfill: NULL ring_id = a plain family member (the pre-existing meaning).
_SUPERGROUP_MEMBER_COLUMNS: dict[str, str] = {
    "ring_id": "ALTER TABLE keyword_supergroup_members ADD COLUMN ring_id VARCHAR(64)",
}


def ensure_supergroup_ring_column(engine: Engine) -> list[str]:
    """Self-heal ``keyword_supergroup_members.ring_id`` (idempotent, additive;
    migration f4a5b6c7d8e9). Same live-DB-never-migrated reason as the others.
    No-op on a fresh DB / non-sqlite / missing table.
    """
    if engine.url.get_backend_name() != "sqlite":
        return []
    added: list[str] = []
    with engine.begin() as conn:
        has_table = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='keyword_supergroup_members'"
            )
        ).fetchone()
        if not has_table:
            return []
        existing = {
            r[1]
            for r in conn.execute(
                text("PRAGMA table_info(keyword_supergroup_members)")
            ).fetchall()
        }
        for name, ddl in _SUPERGROUP_MEMBER_COLUMNS.items():
            if name not in existing:
                conn.execute(text(ddl))
                added.append(name)
    if added:
        _LOG.info(f"added keyword_supergroup_members column(s): {', '.join(added)}")
    return added


# The complete map of live-DB self-healed columns, table -> column names. This is the
# machine-readable contract the migration-drift guard test checks every add_column in
# migrations/versions/ against (tests/test_migration_self_heal_drift.py), so a future
# migration that adds a column WITHOUT a boot self-heal fails CI instead of breaking a
# 0.0.8/early-0.09 store at upgrade ("no such column"). Keep it in sync with the
# ensure_* functions above (it is built from their DDL dicts where one exists).
SELF_HEALED_COLUMNS: dict[str, frozenset[str]] = {
    "feed_fetch_state": frozenset(_FEED_BACKOFF_COLUMNS),
    "article_analyses": frozenset(_ARTICLE_ANALYSIS_COLUMNS),
    "articles": (
        frozenset(_ARTICLE_IDENTITY_COLUMNS)
        | frozenset(_ARTICLE_IP_COLUMNS)
        | frozenset(_ARTICLE_DETECTED_LANG_COLUMN)
        | frozenset(_ARTICLE_QUARANTINE_COLUMNS)
    ),
    "keywords": frozenset(_KEYWORD_COUNTER_COLUMNS) | frozenset(_KEYWORD_EXTRACTOR_COLUMNS),
    # ensure_keyword_mention_source_column (inline DDL, column + its index).
    "keyword_mentions": frozenset({"source_id"}),
    "wiki_pages": frozenset(_WIKI_PAGE_COLUMNS),
    "wiki_revisions": frozenset(_WIKI_REVISION_COLUMNS),
    "keyword_supergroup_members": frozenset(_SUPERGROUP_MEMBER_COLUMNS),
    "external_sources": frozenset(_EXTERNAL_SOURCE_DISCOVERY_COLUMNS),
    "law_documents": frozenset(_LAW_DOCUMENT_TEXT_COLUMNS) | frozenset(_LAW_DOCUMENT_LANGUAGE_COLUMNS),
    "law_revisions": frozenset(_LAW_REVISION_TEXT_COLUMNS),
    # ensure_source_qualification_columns (the admission-gate STAMP columns) +
    # ensure_source_last_crawled_column (§8 crawl-by-default rotation marker).
    "sources": frozenset(_SOURCE_QUALIFICATION_COLUMNS) | frozenset(_SOURCE_LAST_CRAWLED_COLUMN),
}


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
    if not limit or limit <= 0:
        # Deadline disabled — don't even acquire the connection.
        yield
        return
    try:
        raw = session.connection().connection.dbapi_connection
    except Exception:
        # No raw DBAPI connection available (a unit-test stub, or a
        # non-standard session) — degrade to a no-op rather than crash; the
        # wrapped read still runs and surfaces its own error if any.
        yield
        return
    if not hasattr(raw, "set_progress_handler"):
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


def _vacuum_marker_path():
    from src.paths import data_dir

    return data_dir() / "incremental_vacuum.json"


def incremental_vacuum_state() -> dict:
    """The last automatic incremental-vacuum pass (for the diagnostics logs). Never raises."""
    import json

    try:
        p = _vacuum_marker_path()
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a diagnostic read must never crash
        pass
    return {"last_run": None}


def _incremental_vacuum_hours() -> float:
    """Minimum hours between automatic incremental-vacuum passes (OO_INCREMENTAL_VACUUM_HOURS)."""
    try:
        return float(os.getenv("OO_INCREMENTAL_VACUUM_HOURS", "1"))
    except ValueError:
        return 1.0


def _incremental_vacuum_pages() -> int:
    """Pages reclaimed per automatic pass (bounded; OO_INCREMENTAL_VACUUM_PAGES)."""
    try:
        n = int(os.getenv("OO_INCREMENTAL_VACUUM_PAGES", "2000"))
    except ValueError:
        n = 2000
    return max(n, 0)


def maybe_incremental_vacuum(engine: Engine, *, now=None) -> dict:
    """DB-10 §1a/§3: reclaim a BOUNDED number of free pages via
    ``PRAGMA incremental_vacuum(N)`` in the scheduler's idle window, instead of
    relying only on the heavy, blocking full VACUUM (the Settings button).

    Called by :func:`src.scheduler.maintenance.run_idle_maintenance` — same
    idle-gated, bounded, throttled, freshness-marker pattern as the keyword
    cleanup it runs alongside. A documented, HONEST no-op on:
      * a non-SQLite backend,
      * a store still on the PRE-ruling auto_vacuum mode (NONE/FULL) — the
        pragma has nothing to do until the store is rebuilt at INCREMENTAL (a
        migrate op, not this pass's job; reports the real mode it found),
      * a fresh-enough marker (throttled to OO_INCREMENTAL_VACUUM_HOURS).
    Freelist-page counts are real PRAGMA reads, never estimated. Off the
    request path, best-effort, never raises.
    """
    import json
    from datetime import datetime, timedelta

    if engine.url.get_backend_name() != "sqlite":
        return {"skipped": "unsupported-backend"}

    from src.database.writer import write_lock

    try:
        with write_lock(), engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            av = int(conn.execute(text("PRAGMA auto_vacuum")).scalar() or 0)
            if av != 2:
                return {"skipped": "not-incremental-mode", "auto_vacuum": av}

            now = now or datetime.now()
            state = incremental_vacuum_state()
            last = state.get("last_run")
            if last:
                try:
                    if datetime.fromisoformat(last) > now - timedelta(
                        hours=_incremental_vacuum_hours()
                    ):
                        return {"skipped": "fresh", "last_run": last}
                except (ValueError, TypeError):
                    pass  # unparseable marker -> treat as due

            pages = _incremental_vacuum_pages()
            freelist_before = int(conn.execute(text("PRAGMA freelist_count")).scalar() or 0)
            conn.execute(text(f"PRAGMA incremental_vacuum({pages})"))
            freelist_after = int(conn.execute(text("PRAGMA freelist_count")).scalar() or 0)
            report = {
                "freelist_pages_before": freelist_before,
                "freelist_pages_after": freelist_after,
                "pages_reclaimed": max(freelist_before - freelist_after, 0),
                "requested_pages": pages,
                "at": now.isoformat(timespec="seconds"),
            }
    except Exception:  # noqa: BLE001 - a background safety net must never break the pass
        _LOG.warning("off-peak incremental vacuum failed", exc_info=True)
        return {"skipped": "error"}

    try:
        p = _vacuum_marker_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"last_run": report["at"], "last_tally": report}), encoding="utf-8")
    except Exception:  # noqa: BLE001
        _LOG.warning("could not persist the incremental-vacuum marker", exc_info=True)
    return report
