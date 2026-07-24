"""
Merge-only restore: import a staged backup artifact WITHOUT replacing anything.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Design: docs/design/DB_RELIABILITY_02_DESIGN.md §3. The pipeline:

    staged artifact (src/backup/artifact.py -- already hash/signature checked)
      -> floor + schema checks, then `alembic upgrade` ON THE STAGED COPY (§D7)
      -> WORKING COPY = online-backup snapshot of the live DB
      -> domain-by-domain merge INTO THE COPY (one transaction; natural keys;
         FK remapping via temp maps; local always wins on conflict; every
         inserted row recorded in merged_rows -- provenance of merge)
      -> verification ON THE COPY (quick_check, foreign_key_check, count
         reconciliation, FTS rebuild + count, sampled content equality)
      -> preview: report + discard the copy        (the dry-run IS the same
         code path as the commit, so the preview can never lie)
      -> commit: pre-restore snapshot of live, additive side-file merges,
         custody-chain import, then ONE atomic swap of the working copy.

Failure anywhere before the swap leaves the live database byte-identical.
The side-file merges (settings/annotations/events/logs/keys) are additive and
idempotent BY CONSTRUCTION (local always wins; re-running converges), because
true atomicity across many files plus a database does not exist without a
cross-store journal -- stated here rather than pretended away.

Conflict policy (honesty by construction): a conflict is REPORTED with both
values and the local row is kept. Nothing is averaged, nothing silently
overwritten, imported custody chains are verified-not-trusted and NEVER
spliced into the local chain.
"""

from __future__ import annotations

import functools
import json
import logging
import os
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from src.backup.artifact import StagedArtifact
from src.paths import data_dir

_LOG = logging.getLogger("backup.merge")

#: Oldest restorable schema (D7): the 0.0.8 baseline. Older artifacts carry no
#: alembic revision at all and are refused BY NAME of what they lack.
FLOOR_NOTE = "0.0.8 baseline (6ae5766d3136)"

_SAMPLE_LIMIT = 5
_SNAPSHOT_KEEP = 3


class MergeError(RuntimeError):
    """Raised when a merge cannot proceed safely. The live DB is untouched."""


@functools.lru_cache(maxsize=1)
def _db_integrity_error_types() -> tuple[type, ...]:
    """The IntegrityError classes a UNIQUE/FK/NOT-NULL violation can surface as.

    ``sqlite3`` is stdlib (always present); ``sqlcipher3`` is the ENCRYPTED store's
    driver (the default) and defines its OWN ``IntegrityError`` class -- NOT a
    subclass of ``sqlite3.IntegrityError`` -- the exact cross-driver class
    divergence ``src/database/write.py``'s ``is_locked_error`` already had to fix
    for ``OperationalError`` (field log 2026-07-14, "297 fetched articles left
    unindexed"). Without this, ``isinstance(exc, sqlite3.IntegrityError)`` silently
    never fires for the encrypted store merge_corpus runs against, so a genuine
    data-merge collision falls through to the generic "could not restore this
    backup: ..." wording instead of the honest, more informative classification
    below (field bug 2026-07-16). Guarded: sqlcipher3 may be absent in a core
    install; cached since the imports are resolved once."""
    types: list[type] = [sqlite3.IntegrityError]
    try:
        from sqlcipher3.dbapi2 import IntegrityError as _SqlcipherIntegrityError

        types.append(_SqlcipherIntegrityError)
    except Exception:  # noqa: BLE001 - sqlcipher3 absent in a core install -> stdlib path only
        pass
    return tuple(types)


def classify_restore_error(action: str, exc: Exception) -> str:
    """Classify an unexpected restore failure into an HONEST detail (P0-2).

    Shared by both restore entry points: the single-shot ``/api/backup/v2/restore``
    endpoint (via ``_restore_error``, which wraps this in an HTTPException) and the
    background ``volume-restore`` job (``volume_job.py``, which stores the plain
    string as the job's ``error``) -- the classification must not depend on which
    surface a restore failure came through (field bug 2026-07-15: the volume-restore
    job stored the bare ``str(exc)``, e.g. an unqualified "UNIQUE constraint
    failed:", instead of this same honest classification).

    The old wording blamed an "incompatible version" for EVERY non-MergeError, so a
    plain database constraint clash (the merge UNIQUE collision the maintainer hit on
    their own backup) read as a version mismatch. Distinguish the real causes:
      * a constraint/integrity clash = a MERGE data conflict (a duplicate row), not a
        version problem;
      * a missing table/column = an actual schema/version gap (keep that wording);
      * anything else = an honest, non-speculative "could not <action>"."""
    msg = str(exc)
    low = msg.lower()
    # A real version/schema gap: a staged migration failed, or the corpus uses a
    # table/column this build doesn't know. "incompatible version" is accurate here.
    is_version = (
        "migration" in low
        or "incompatible" in low
        or "no such table" in low
        or "no such column" in low
        or "schema" in low
    )
    if isinstance(exc, _db_integrity_error_types()):
        return (
            f"the backup's data conflicts with your corpus on a database constraint "
            f"(e.g. a duplicate row) while merging — this is a data-merge issue, not a "
            f"version mismatch: {msg}"
        )
    if is_version:
        return f"could not {action} this backup (it may be from an incompatible version): {msg}"
    return f"could not {action} this backup: {msg}"


@dataclass
class DomainResult:
    new: int = 0
    duplicate: int = 0
    conflict: int = 0
    samples: list[str] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        d: dict = {"new": self.new, "duplicate": self.duplicate, "conflict": self.conflict}
        if self.samples:
            d["samples"] = self.samples
        if self.conflicts:
            d["conflicts"] = self.conflicts[:_SAMPLE_LIMIT]
        return d


# --------------------------------------------------------------------------- #
#  Stage preparation (schema floor + upgrade on the staged copy)
# --------------------------------------------------------------------------- #
def prepare_staged_corpus(staged: StagedArtifact, *, allow_unverified: bool = False) -> str:
    """Validate + upgrade the staged corpus to the running schema. Never touches
    the live DB; the staged copy is disposable. Returns the artifact's original
    schema revision."""
    from src.backup.sqlite_backup import BackupError, validate_sqlite_file
    from src.database.migrate import file_revision, known_revisions, upgrade_database_file

    if staged.hash_failures:
        raise MergeError(
            "artifact failed its own manifest hashes -- refusing to merge: "
            + "; ".join(staged.hash_failures)
        )
    if (
        staged.kind == "oo-backup-2"
        and staged.signature_state != "verified"
        and not allow_unverified
    ):
        raise MergeError(
            f"artifact manifest is {staged.signature_state}; pass "
            "allow_unverified to merge it anyway (its origin cannot be proven)"
        )

    try:
        validate_sqlite_file(staged.corpus_path)
    except BackupError as exc:
        raise MergeError(str(exc)) from exc

    original_rev = file_revision(staged.corpus_path)
    if original_rev is None:
        raise MergeError(
            f"artifact carries no schema revision (pre-{FLOOR_NOTE}); "
            "the supported restore floor is the 0.0.8 baseline"
        )
    if original_rev not in known_revisions():
        raise MergeError(
            f"artifact schema revision {original_rev!r} is unknown to this build "
            "(made by a NEWER app or a foreign fork) -- upgrade the app, then restore"
        )
    upgrade_database_file(staged.corpus_path)  # no-op when already at head
    return original_rev


# --------------------------------------------------------------------------- #
#  SQL helpers (all operate on a connection whose main schema is the WORKING
#  COPY with the staged corpus ATTACHed as `inc`)
# --------------------------------------------------------------------------- #
def _q(con: sqlite3.Connection, sql: str, params: tuple = ()) -> list:
    return con.execute(sql, params).fetchall()


def _count(con: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    return con.execute(sql, params).fetchone()[0]


#: A legitimate SQLite table identifier as carried in a restore artifact. Names
#: failing this are REPORTED under ``_rejected_tables`` and never interpolated
#: into SQL (audit OO-01). Modelled on stream_backup.py's ``_SAFE_VOL_NAME``,
#: tightened to a plain SQL identifier (the app's own schema uses only these).
_SAFE_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _ident(name: str) -> str:
    """Quote a SQLite identifier: wrap in ``""`` and double any embedded ``"``
    (mirrors ``src/database/fts.py``'s ``_quote``). This is the primary defence
    for any identifier that must be interpolated; ``_SAFE_TABLE_NAME`` is the
    defence-in-depth allowlist layered on top of it."""
    return '"' + name.replace('"', '""') + '"'


def _insert_tracked(
    con: sqlite3.Connection,
    batch_id: int,
    table: str,
    insert_sql: str,
    params: tuple = (),
) -> int:
    """Run an INSERT..SELECT and record every new row in merged_rows (provenance).

    Uses a rowid watermark: we hold the copy exclusively inside one transaction,
    so rows with rowid > the pre-insert max are exactly the inserted ones."""
    wm = con.execute(f'SELECT COALESCE(MAX(rowid), 0) FROM "{table}"').fetchone()[0]  # noqa: S608  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
    con.execute(insert_sql, params)
    con.execute(
        f'INSERT INTO merged_rows (batch_id, table_name, row_id) '  # noqa: S608  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        f'SELECT ?, ?, rowid FROM "{table}" WHERE rowid > ?',
        (batch_id, table, wm),
    )
    return _count(con, f'SELECT COUNT(*) FROM "{table}" WHERE rowid > ?', (wm,))  # noqa: S608  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input


def _build_map(con: sqlite3.Connection, name: str, select_old_new: str) -> None:
    """Create temp mapping table ``name(old -> new)`` from a SELECT old, new."""
    con.execute(f'DROP TABLE IF EXISTS temp."{name}"')
    con.execute(f'CREATE TEMP TABLE "{name}" (old INTEGER PRIMARY KEY, new INTEGER NOT NULL)')
    con.execute(f'INSERT INTO temp."{name}" (old, new) {select_old_new}')  # noqa: S608


# --------------------------------------------------------------------------- #
#  The corpus merge (single transaction on the working copy)
# --------------------------------------------------------------------------- #
def merge_corpus(
    staged_corpus: Path, working_copy: Path, batch_meta: dict, progress_cb=None,
    cache_mb: int | None = None,
) -> tuple[dict, int]:
    """Merge the staged corpus into the working copy. Returns (per-domain counts,
    batch_id). The working copy is disposable; the live DB is never touched.

    ``progress_cb(step_done, step_total, step_name)`` is called after each table-merge
    step so a caller can show a determinate progress bar + ETA for the "merging" phase
    (field ask 2026-07-02). It is REPORT-ONLY — wrapped so a reporting error can never
    affect the merge — and its granularity is per table-step (steps are uneven, so the
    derived ETA is an estimate, stated as such in the UI).

    ``cache_mb`` (2026-07-24 field-feedback Session A §4, "import owns the machine"):
    this connection is opened via the raw :func:`~src.database.connect.connect`
    factory, NEVER the pooled app engine — so the app's own ``OO_SQLITE_CACHE_MB``
    tuning (``src/database/session.py``) never reaches it, and the whole 14-step
    merge otherwise runs at SQLite's tiny compiled-in default page cache. When
    given, an enlarged ``PRAGMA cache_size`` is applied to THIS connection only —
    a pure resource-usage tuning knob (never a behaviour/correctness change), so
    it is safe unconditionally and best-effort (a tuning-PRAGMA failure must
    never break a merge)."""
    from src.database.connect import attach
    from src.database.connect import connect as db_connect

    con = db_connect(working_copy, check_same_thread=False)
    con.isolation_level = None  # explicit BEGIN/COMMIT (auto-BEGIN would collide)
    if cache_mb:
        try:
            con.execute(f"PRAGMA cache_size=-{int(cache_mb) * 1024}")  # negative = KiB
        except Exception:  # noqa: BLE001 - a tuning PRAGMA must never break a merge
            pass
    try:
        con.execute("PRAGMA foreign_keys=OFF")  # order is FK-safe; checked at the end
        attach(con, staged_corpus, "inc")  # staged members are plaintext by design
        con.execute("BEGIN IMMEDIATE")
        results: dict[str, DomainResult] = {}

        cur = con.execute(
            "INSERT INTO merge_batches (imported_at, artifact_kind, origin_fingerprint,"
            " app_version, alembic_rev, manifest_json, status)"
            " VALUES (?, ?, ?, ?, ?, ?, 'merged')",
            (
                datetime.now(UTC).isoformat(timespec="seconds"),
                batch_meta.get("artifact_kind", "oo-backup-2"),
                batch_meta.get("origin_fingerprint", "unsigned"),
                batch_meta.get("app_version"),
                batch_meta.get("alembic_rev"),
                json.dumps(batch_meta.get("manifest")) if batch_meta.get("manifest") else None,
            ),
        )
        batch_id = int(cur.lastrowid or 0)

        # Ordered, FK-safe merge steps. Named so a caller can report which step is
        # running; the order is UNCHANGED from the previous explicit sequence.
        steps = (
            ("keyword categories", _merge_keyword_categories),
            ("sources", _merge_sources),
            ("articles", _merge_articles),
            ("keywords", _merge_keywords),
            ("article-keyword links", _merge_article_keyword_links),
            ("keyword mentions", _merge_keyword_mentions),
            ("curation", _merge_curation),
            ("link graph", _merge_external_link_graph),
            ("article derivations", _merge_article_derivations),
            ("wiki", _merge_wiki),
            ("law", _merge_law),
            ("markets", _merge_markets),
            ("rule tables", _merge_rule_tables),
            ("source candidates", _merge_source_candidates),
        )
        total = len(steps)
        for i, (name, fn) in enumerate(steps, 1):
            fn(con, batch_id, results)
            if progress_cb is not None:
                try:
                    progress_cb(i, total, name)
                except Exception:  # noqa: BLE001 - progress reporting must never break a merge
                    pass

        counts: dict[str, object] = {k: v.as_dict() for k, v in results.items()}
        unmerged, rejected = _unmerged_tables(con)
        if unmerged:
            counts["_unmerged_tables"] = unmerged  # stated, never silent
        if rejected:
            # Incoming table names that are not plain SQL identifiers: surfaced
            # (never silently dropped) and never interpolated/counted (OO-01).
            counts["_rejected_tables"] = rejected

        con.execute(
            "UPDATE merge_batches SET counts_json = ? WHERE id = ?",
            (json.dumps(counts), batch_id),
        )
        con.execute("COMMIT")
        return counts, batch_id
    except Exception:
        from contextlib import suppress

        with suppress(sqlite3.Error):  # may already be rolled back
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()


_MERGE_HANDLED = {
    "keyword_categories", "sources", "source_groups", "source_group_association",
    "source_metadata", "articles", "keywords", "article_keyword_association",
    "article_keywords", "keyword_mentions", "keyword_family_overrides",
    "keyword_supergroups", "keyword_supergroup_members", "external_sources",
    "source_articles", "article_links", "article_source_relationships",
    "article_analyses", "article_mentioned_dates", "wiki_pages", "wiki_revisions",
    "law_documents", "law_revisions", "commodity_prices", "market_extraction_rules",
    "link_classification_rules", "source_credibility_rules", "source_candidates",
}
# Deliberately not merged: the other corpus's OWN import history + schema/FTS internals,
# plus ``app_state`` — per-machine settings/UI prefs (DB-reliability D1 / T10: local wins
# entirely, incoming values are never adopted by a merge).
#
# ``event_imports`` (Wave 4 J) stays here as a REASONED deliberate omission, NOT a "handler
# not built yet" TODO (Wave 5 L analysis). It is a DERIVED FULL-REPLACE MIRROR of the
# authoritative ``calendar_feed_imports.json`` side-file: ``event_store.sync_imports`` DELETEs
# the whole table and re-INSERTs the flattened JSON on every save, so the table has NO
# independent identity — it is a cache of the JSON. The events restore additively through the
# side-file UNION-merge (``merge_side_files`` -> ``merge_imported_store``), the merge target.
# A native ``_MERGE_HANDLED`` handler for the TABLE would be actively WRONG while the JSON is
# authoritative: (1) it would DOUBLE-ACCOUNT the same events in the restore report — once as
# table rows in ``plan``, once as JSON entries in ``side_files``; (2) its natural row
# ``local-wins`` semantics would DIVERGE from the side-file's ``union sources/uids`` semantics
# (which wins regardless, being the source of truth). So the table stays side-file-authoritative
# and the report stays clean (no ``_unmerged_tables`` entry), while ``run_restore``'s post-swap
# ``_refresh_event_mirror`` keeps the durable table CORRECT after a restore (the side-file merge
# runs with ``mirror=False`` PRE-swap — it must not touch the still-live OLD DB, torture T1/T7 —
# so without the refresh the mirror would stay stale until the next calendar write). The true
# native UNION-merge is the LARGER D1 follow-up that RETIRES the JSON as the merge target
# (making the table the source of truth); that is out of this slice's scope. Restore
# correctness is sacred — honest deferral beats a double-count bug.
_MERGE_IGNORED = {"merge_batches", "merged_rows", "alembic_version", "app_state", "event_imports"}


def _unmerged_tables(con: sqlite3.Connection) -> tuple[dict[str, int], list[str]]:
    """Tables present in the incoming corpus that no handler covered.

    Returns ``(unmerged, rejected)``. ``unmerged`` maps each such table to its
    row count so nothing is ever dropped silently. ``rejected`` lists incoming
    table names that fail the ``_SAFE_TABLE_NAME`` allowlist -- those are NOT a
    legitimate artifact (the app's own schema uses only plain identifiers), so
    they are surfaced (never silently dropped) but never interpolated into SQL
    or counted (audit OO-01: the incoming name is untrusted input, not our own
    fixed schema)."""
    out: dict[str, int] = {}
    rejected: list[str] = []
    for (name,) in _q(
        con,
        "SELECT name FROM inc.sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'article_fts%'",
    ):
        if name in _MERGE_HANDLED or name in _MERGE_IGNORED:
            continue
        if not _SAFE_TABLE_NAME.fullmatch(name):
            rejected.append(name)
            continue
        # The identifier is now allowlist-validated AND quoted -- two independent
        # defences against a hostile table name breaking out of the SQL string.
        n = _count(con, f"SELECT COUNT(*) FROM inc.{_ident(name)}")  # noqa: S608  # nosec B608 - identifier is allowlist-validated (_SAFE_TABLE_NAME) AND quoted (_ident); see audit OO-01
        if n:
            out[name] = n
    return out, rejected


def _merge_keyword_categories(con, batch_id, results) -> None:
    r = DomainResult()
    r.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.keyword_categories i "
        "WHERE EXISTS (SELECT 1 FROM keyword_categories m WHERE m.name = i.name)",
    )
    r.new = _insert_tracked(
        con, batch_id, "keyword_categories",
        "INSERT INTO keyword_categories (name, description, color, is_active, created_at, updated_at)"
        " SELECT i.name, i.description, i.color, i.is_active, i.created_at, i.updated_at"
        " FROM inc.keyword_categories i"
        " WHERE NOT EXISTS (SELECT 1 FROM keyword_categories m WHERE m.name = i.name)",
    )
    _build_map(
        con, "map_kwcat",
        "SELECT i.id, m.id FROM inc.keyword_categories i"
        " JOIN keyword_categories m ON m.name = i.name",
    )
    # Parent links for freshly inserted categories (self-FK remap).
    con.execute(
        "UPDATE keyword_categories SET parent_id ="
        " (SELECT mp.new FROM inc.keyword_categories i"
        "   JOIN temp.map_kwcat mc ON mc.old = i.id"
        "   JOIN temp.map_kwcat mp ON mp.old = i.parent_id"
        "  WHERE mc.new = keyword_categories.id)"
        " WHERE parent_id IS NULL AND id IN"
        " (SELECT row_id FROM merged_rows WHERE batch_id = ? AND table_name = 'keyword_categories')",
        (batch_id,),
    )
    results["keyword_categories"] = r


def _merge_sources(con, batch_id, results) -> None:
    r = DomainResult()
    r.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.sources i WHERE EXISTS"
        " (SELECT 1 FROM sources m WHERE m.domain = i.domain)",
    )
    # Local wins entirely: differing incoming fields are REPORTED, never applied.
    for row in _q(
        con,
        "SELECT i.domain, i.name, m.name FROM inc.sources i"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " JOIN sources m ON m.domain = i.domain"
        " WHERE COALESCE(i.name,'') <> COALESCE(m.name,'')"
        f" LIMIT {_SAMPLE_LIMIT}",
    ):
        r.conflicts.append({"domain": row[0], "incoming_name": row[1], "local_name": row[2]})
    r.conflict = _count(
        con,
        "SELECT COUNT(*) FROM inc.sources i JOIN sources m ON m.domain = i.domain"
        " WHERE COALESCE(i.name,'') <> COALESCE(m.name,'')",
    )
    r.new = _insert_tracked(
        con, batch_id, "sources",
        "INSERT INTO sources (name, domain, rss_url, rate_limit_ms, enabled, priority, tags,"
        " reliability_score, language, region, country, source_type, update_frequency,"
        " cacheability)"
        " SELECT i.name, i.domain, i.rss_url, i.rate_limit_ms, i.enabled, i.priority, i.tags,"
        " i.reliability_score, i.language, i.region, i.country, i.source_type,"
        " i.update_frequency, i.cacheability"
        " FROM inc.sources i"
        " WHERE NOT EXISTS (SELECT 1 FROM sources m WHERE m.domain = i.domain)",
    )
    for row in _q(
        con,
        "SELECT i.domain FROM inc.sources i WHERE NOT EXISTS"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        f" (SELECT 1 FROM sources m WHERE m.domain = i.domain) LIMIT {_SAMPLE_LIMIT}",
    ):
        r.samples.append(row[0])
    _build_map(
        con, "map_sources",
        "SELECT i.id, m.id FROM inc.sources i JOIN sources m ON m.domain = i.domain",
    )

    g = DomainResult()
    g.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.source_groups i WHERE EXISTS"
        " (SELECT 1 FROM source_groups m WHERE m.name = i.name)",
    )
    g.new = _insert_tracked(
        con, batch_id, "source_groups",
        "INSERT INTO source_groups (name, description, color, is_tag_based, tag_pattern,"
        " priority, rate_limit_ms, enabled, created_at, updated_at)"
        " SELECT i.name, i.description, i.color, i.is_tag_based, i.tag_pattern,"
        " i.priority, i.rate_limit_ms, i.enabled, i.created_at, i.updated_at"
        " FROM inc.source_groups i"
        " WHERE NOT EXISTS (SELECT 1 FROM source_groups m WHERE m.name = i.name)",
    )
    _build_map(
        con, "map_groups",
        "SELECT i.id, m.id FROM inc.source_groups i JOIN source_groups m ON m.name = i.name",
    )
    g.new += _insert_tracked(
        con, batch_id, "source_group_association",
        "INSERT INTO source_group_association (source_id, group_id, added_at)"
        " SELECT ms.new, mg.new, i.added_at FROM inc.source_group_association i"
        " JOIN temp.map_sources ms ON ms.old = i.source_id"
        " JOIN temp.map_groups mg ON mg.old = i.group_id"
        " WHERE NOT EXISTS (SELECT 1 FROM source_group_association a"
        "  WHERE a.source_id = ms.new AND a.group_id = mg.new)",
    )
    results["source_groups"] = g

    m = DomainResult()
    m.new = _insert_tracked(
        con, batch_id, "source_metadata",
        "INSERT INTO source_metadata (source_id, language, country, region, city, timezone,"
        " robots_txt_url, robots_allowed, crawl_delay, sitemap_url, favicon_url, logo_url,"
        " contact_email, social_twitter, social_facebook, social_linkedin, alexa_rank,"
        " last_checked, notes)"
        " SELECT ms.new, i.language, i.country, i.region, i.city, i.timezone,"
        " i.robots_txt_url, i.robots_allowed, i.crawl_delay, i.sitemap_url, i.favicon_url,"
        " i.logo_url, i.contact_email, i.social_twitter, i.social_facebook, i.social_linkedin,"
        " i.alexa_rank, i.last_checked, i.notes"
        " FROM inc.source_metadata i JOIN temp.map_sources ms ON ms.old = i.source_id"
        " WHERE NOT EXISTS (SELECT 1 FROM source_metadata m2 WHERE m2.source_id = ms.new)",
    )
    m.duplicate = max(0, _count(con, "SELECT COUNT(*) FROM inc.source_metadata") - m.new)
    results["source_metadata"] = m
    results["sources"] = r


def _merge_articles(con, batch_id, results) -> None:
    r = DomainResult()
    # Bit-level duplicate test: same hash AND same content bytes = duplicate.
    r.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.articles i JOIN articles m ON m.hash = i.hash"
        " WHERE m.content = i.content",
    )
    # Same hash, different bytes: collision or normalisation drift -- a conflict,
    # local kept, surfaced with both ids.
    r.conflict = _count(
        con,
        "SELECT COUNT(*) FROM inc.articles i JOIN articles m ON m.hash = i.hash"
        " WHERE m.content <> i.content",
    )
    for row in _q(
        con,
        "SELECT i.hash, i.title FROM inc.articles i JOIN articles m ON m.hash = i.hash"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        f" WHERE m.content <> i.content LIMIT {_SAMPLE_LIMIT}",
    ):
        r.conflicts.append({"hash": row[0], "incoming_title": row[1], "kept": "local"})
    r.new = _insert_tracked(
        con, batch_id, "articles",
        "INSERT INTO articles (url, canonical_url, source_id, title, content,"
        " compressed_content, published_at, language, hash, created_at, updated_at, region,"
        " country, author, word_count, reading_time, sentiment_score, sentiment_label,"
        # S3.2 (2026-07-23 field-feedback workflow): the quarantine stamp is a
        # DEDUCED extraction-validity fact about this exact article -- it rides
        # additive-restore exactly like sentiment_score/sentiment_label above (a
        # quarantined article stays quarantined after a restore; never silently
        # un-quarantined by import, never dropped).
        " quarantined, quarantine_reason, quarantine_criteria_version, quarantined_at)"
        " SELECT i.url, i.canonical_url, ms.new, i.title, i.content,"
        " i.compressed_content, i.published_at, i.language, i.hash, i.created_at,"
        " i.updated_at, i.region, i.country, i.author, i.word_count, i.reading_time,"
        " i.sentiment_score, i.sentiment_label,"
        " i.quarantined, i.quarantine_reason, i.quarantine_criteria_version, i.quarantined_at"
        " FROM inc.articles i JOIN temp.map_sources ms ON ms.old = i.source_id"
        " WHERE NOT EXISTS (SELECT 1 FROM articles m WHERE m.hash = i.hash)",
    )
    for row in _q(
        con,
        "SELECT i.title FROM inc.articles i WHERE NOT EXISTS"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        f" (SELECT 1 FROM articles m WHERE m.hash = i.hash) LIMIT {_SAMPLE_LIMIT}",
    ):
        r.samples.append(row[0] or "(untitled)")
    _build_map(
        con, "map_articles",
        "SELECT i.id, m.id FROM inc.articles i JOIN articles m ON m.hash = i.hash",
    )
    results["articles"] = r


def _merge_keywords(con, batch_id, results) -> None:
    r = DomainResult()
    key = "m.normalized_term = i.normalized_term AND COALESCE(m.language,'en') = COALESCE(i.language,'en')"
    r.duplicate = _count(
        con,
        f"SELECT COUNT(*) FROM inc.keywords i WHERE EXISTS (SELECT 1 FROM keywords m WHERE {key})",  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
    )
    # `keywords` carries NO unique constraint on (normalized_term, language) --
    # deliberately, so near-duplicate rows are reconciled later at the family/ring
    # layer, never at the schema layer. So an incoming corpus can genuinely hold TWO
    # rows for the same term+language (a historical gap, e.g. a race predating the
    # single-writer gate). The plain `NOT EXISTS` guard above only dedupes against
    # the TARGET; it does nothing to collapse duplicates WITHIN the incoming batch
    # itself, so both would insert as two SEPARATE new target rows -- defeating the
    # whole point of this function's natural-key matching and (worse) perpetuating
    # the same collapsible-duplicate shape into the target on every restore (field
    # bug 2026-07-16, the keyword_mentions crash this fixes downstream in
    # _merge_keyword_mentions/_merge_article_keyword_links). The `rep` join keeps
    # only ONE representative incoming row per (normalized_term, language) group --
    # deterministically the lowest incoming id, the SAME tie-break map_keywords
    # below already uses for the target side.
    r.new = _insert_tracked(
        con, batch_id, "keywords",
        "INSERT INTO keywords (term, normalized_term, language, frequency, category_id,"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " is_ngram, ngram_size, is_entity, entity_type, relevance_score, extractor,"
        " created_at, updated_at)"
        " SELECT i.term, i.normalized_term, i.language, i.frequency, mc.new,"
        " i.is_ngram, i.ngram_size, i.is_entity, i.entity_type, i.relevance_score,"
        " i.extractor, i.created_at, i.updated_at"
        " FROM inc.keywords i LEFT JOIN temp.map_kwcat mc ON mc.old = i.category_id"
        " JOIN (SELECT normalized_term, COALESCE(language,'en') AS lang, MIN(id) AS rep_id"
        "       FROM inc.keywords GROUP BY normalized_term, COALESCE(language,'en')) rep"
        "  ON rep.normalized_term = i.normalized_term"
        "  AND rep.lang = COALESCE(i.language,'en') AND rep.rep_id = i.id"
        f" WHERE NOT EXISTS (SELECT 1 FROM keywords m WHERE {key})",
    )
    _build_map(
        con, "map_keywords",
        "SELECT i.id, (SELECT MIN(m.id) FROM keywords m WHERE "
        "m.normalized_term = i.normalized_term AND COALESCE(m.language,'en') ="
        " COALESCE(i.language,'en')) FROM inc.keywords i",
    )
    results["keywords"] = r


def _merge_article_keyword_links(con, batch_id, results) -> None:
    r = DomainResult()
    for table, cols in (
        ("article_keyword_association", "frequency, position, relevance_score, created_at"),
        ("article_keywords", "frequency, first_position, last_position, relevance_score, created_at"),
    ):
        icols = ", ".join("i." + c.strip() for c in cols.split(","))
        # INSERT OR IGNORE (field bug 2026-07-16, same class as the article_mentioned_dates
        # fix below): `keywords` has NO unique constraint on (normalized_term, language) --
        # deliberately, so near-duplicate keyword rows can be reconciled later at the
        # family/ring layer instead of the schema layer. So `map_keywords` (built by
        # `_merge_keywords`, matched on normalized_term+language) can be a COLLAPSING map:
        # two DISTINCT incoming keyword ids landing on the SAME local keyword id. If both
        # of those incoming ids have a link row for the same article, both candidate rows
        # here target the identical (article_id, keyword_id) pair -- the plain NOT EXISTS
        # guard only checks the pre-statement state of the target table, so it does not
        # stop a second candidate colliding with the first candidate's OWN insert within
        # this same statement, and the real PRIMARY KEY on (article_id, keyword_id) aborts
        # the whole merge. OR IGNORE keeps one, silently drops the other (an arbitrary but
        # harmless tie-break -- the two incoming rows describe the same article+concept).
        r.new += _insert_tracked(
            con, batch_id, table,
            f"INSERT OR IGNORE INTO {table} (article_id, keyword_id, {cols})"  # noqa: S608  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
            f" SELECT ma.new, mk.new, {icols} FROM inc.{table} i"
            " JOIN temp.map_articles ma ON ma.old = i.article_id"
            " JOIN temp.map_keywords mk ON mk.old = i.keyword_id"
            f" WHERE NOT EXISTS (SELECT 1 FROM {table} t"
            "  WHERE t.article_id = ma.new AND t.keyword_id = mk.new)",
        )
    r.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.article_keyword_association i"
        " JOIN temp.map_articles ma ON ma.old = i.article_id"
        " JOIN temp.map_keywords mk ON mk.old = i.keyword_id"
        " WHERE EXISTS (SELECT 1 FROM article_keyword_association t"
        "  WHERE t.article_id = ma.new AND t.keyword_id = mk.new)",
    )
    results["article_keyword_links"] = r


def _merge_keyword_mentions(con, batch_id, results) -> None:
    r = DomainResult()
    r.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.keyword_mentions i"
        " JOIN temp.map_articles ma ON ma.old = i.article_id"
        " JOIN temp.map_keywords mk ON mk.old = i.keyword_id"
        " JOIN keyword_mentions t ON t.article_id = ma.new AND t.keyword_id = mk.new"
        " WHERE t.count = i.count",
    )
    r.conflict = _count(
        con,
        "SELECT COUNT(*) FROM inc.keyword_mentions i"
        " JOIN temp.map_articles ma ON ma.old = i.article_id"
        " JOIN temp.map_keywords mk ON mk.old = i.keyword_id"
        " JOIN keyword_mentions t ON t.article_id = ma.new AND t.keyword_id = mk.new"
        " WHERE t.count <> i.count",
    )
    # INSERT OR IGNORE (field bug 2026-07-16: an 18 GB restore failed after hours of
    # merging with "UNIQUE constraint failed: keyword_mentions.keyword_id,
    # keyword_mentions.article_id"). Root cause is the same collapsing-map hazard as
    # _merge_article_keyword_links above: `keywords` carries no unique constraint on
    # (normalized_term, language) by design, so a large/old corpus can genuinely contain
    # two keyword rows for the same term+language (a known historical gap this project's
    # own family/ring reconciliation layer exists to paper over, never to delete). When
    # such a corpus is the SOURCE of a restore, `map_keywords` collapses both incoming ids
    # onto the one local keyword, and if both had a mention on the same article the two
    # candidate rows target the identical (keyword_id, article_id) pair -- the real unique
    # index (ix_mention_keyword_article) then aborts the whole restore on the second one,
    # since the NOT EXISTS guard only sees the target table's pre-statement state, not a
    # sibling candidate row inserted moments earlier by this SAME statement. Reproduced
    # directly against sqlite3 (not mocked) before this fix; confirmed to raise the exact
    # field error without OR IGNORE.
    r.new = _insert_tracked(
        con, batch_id, "keyword_mentions",
        "INSERT OR IGNORE INTO keyword_mentions (keyword_id, article_id, count, first_offset,"
        " observed_on, country, city, extractor, created_at)"
        " SELECT mk.new, ma.new, i.count, i.first_offset, i.observed_on, i.country,"
        " i.city, i.extractor, i.created_at"
        " FROM inc.keyword_mentions i"
        " JOIN temp.map_articles ma ON ma.old = i.article_id"
        " JOIN temp.map_keywords mk ON mk.old = i.keyword_id"
        " WHERE NOT EXISTS (SELECT 1 FROM keyword_mentions t"
        "  WHERE t.article_id = ma.new AND t.keyword_id = mk.new)",
    )
    results["keyword_mentions"] = r


def _merge_curation(con, batch_id, results) -> None:
    """User curation: local ALWAYS wins; incoming-new inserted."""
    r = DomainResult()
    r.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.keyword_family_overrides i WHERE EXISTS"
        " (SELECT 1 FROM keyword_family_overrides m WHERE m.normalized_term = i.normalized_term)",
    )
    r.new = _insert_tracked(
        con, batch_id, "keyword_family_overrides",
        "INSERT INTO keyword_family_overrides (normalized_term, family_key, canonical_label,"
        " kind, created_at)"
        " SELECT i.normalized_term, i.family_key, i.canonical_label, i.kind, i.created_at"
        " FROM inc.keyword_family_overrides i"
        " WHERE NOT EXISTS (SELECT 1 FROM keyword_family_overrides m"
        "  WHERE m.normalized_term = i.normalized_term)",
    )
    results["keyword_family_overrides"] = r

    s = DomainResult()
    s.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.keyword_supergroups i WHERE EXISTS"
        " (SELECT 1 FROM keyword_supergroups m WHERE m.name = i.name)",
    )
    s.new = _insert_tracked(
        con, batch_id, "keyword_supergroups",
        "INSERT INTO keyword_supergroups (name, color, created_at)"
        " SELECT i.name, i.color, i.created_at FROM inc.keyword_supergroups i"
        " WHERE NOT EXISTS (SELECT 1 FROM keyword_supergroups m WHERE m.name = i.name)",
    )
    _build_map(
        con, "map_sg",
        "SELECT i.id, m.id FROM inc.keyword_supergroups i"
        " JOIN keyword_supergroups m ON m.name = i.name",
    )
    s.new += _insert_tracked(
        con, batch_id, "keyword_supergroup_members",
        "INSERT INTO keyword_supergroup_members (supergroup_id, normalized_term, created_at)"
        " SELECT mg.new, i.normalized_term, i.created_at"
        " FROM inc.keyword_supergroup_members i JOIN temp.map_sg mg ON mg.old = i.supergroup_id"
        " WHERE NOT EXISTS (SELECT 1 FROM keyword_supergroup_members m"
        "  WHERE m.supergroup_id = mg.new AND m.normalized_term = i.normalized_term)",
    )
    results["keyword_supergroups"] = s


def _merge_external_link_graph(con, batch_id, results) -> None:
    r = DomainResult()
    r.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.external_sources i WHERE EXISTS"
        " (SELECT 1 FROM external_sources m WHERE m.domain = i.domain)",
    )
    r.new = _insert_tracked(
        con, batch_id, "external_sources",
        "INSERT INTO external_sources (domain, name, url, source_type, credibility_score,"
        " political_bias, country, language, description, founded_year, alexa_rank,"
        " social_media_followers, is_verified, last_verified_at, created_at, updated_at)"
        " SELECT i.domain, i.name, i.url, i.source_type, i.credibility_score,"
        " i.political_bias, i.country, i.language, i.description, i.founded_year,"
        " i.alexa_rank, i.social_media_followers, i.is_verified, i.last_verified_at,"
        " i.created_at, i.updated_at FROM inc.external_sources i"
        " WHERE NOT EXISTS (SELECT 1 FROM external_sources m WHERE m.domain = i.domain)",
    )
    _build_map(
        con, "map_ext",
        "SELECT i.id, m.id FROM inc.external_sources i"
        " JOIN external_sources m ON m.domain = i.domain",
    )
    results["external_sources"] = r

    sa = DomainResult()
    sa.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.source_articles i WHERE EXISTS"
        " (SELECT 1 FROM source_articles m WHERE m.url = i.url)",
    )
    sa.new = _insert_tracked(
        con, batch_id, "source_articles",
        "INSERT INTO source_articles (source_id, url, title, published_at, author, summary,"
        " content_hash, word_count, sentiment_score, is_accessible, last_accessed_at,"
        " created_at, updated_at)"
        " SELECT me.new, i.url, i.title, i.published_at, i.author, i.summary,"
        " i.content_hash, i.word_count, i.sentiment_score, i.is_accessible,"
        " i.last_accessed_at, i.created_at, i.updated_at"
        " FROM inc.source_articles i LEFT JOIN temp.map_ext me ON me.old = i.source_id"
        " WHERE NOT EXISTS (SELECT 1 FROM source_articles m WHERE m.url = i.url)"
        " AND NOT EXISTS (SELECT 1 FROM source_articles m2 WHERE m2.content_hash = i.content_hash)",
    )
    _build_map(
        con, "map_srcart",
        "SELECT i.id, m.id FROM inc.source_articles i JOIN source_articles m ON m.url = i.url",
    )
    results["source_articles"] = sa

    li = DomainResult()
    link_key = (
        "t.article_id = ma.new AND t.url = i.url"
        " AND COALESCE(t.position,-1) = COALESCE(i.position,-1)"
    )
    li.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.article_links i"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " JOIN temp.map_articles ma ON ma.old = i.article_id"
        f" WHERE EXISTS (SELECT 1 FROM article_links t WHERE {link_key})",
    )
    # `article_links` carries NO unique constraint at all (a URL can legitimately
    # repeat at different positions in the same article, so a hard schema
    # constraint isn't the right fix here -- unlike keywords/commodity_prices,
    # there is no single "real" identity to enforce). The merge's own dedup key
    # above IS the intended identity for restore purposes though, so an incoming
    # corpus carrying two rows for the exact same (article, url, position) would
    # otherwise insert both (audit 2026-07-16, following the keyword_mentions
    # collapse fix). The `rep` join keeps only the lowest incoming id per group.
    li.new = _insert_tracked(
        con, batch_id, "article_links",
        "INSERT INTO article_links (article_id, url, normalized_url, link_text, position,"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " link_type, classification, external_source_id, source_article_id, is_followable,"
        " is_working, last_checked_at, redirect_url, http_status, created_at, updated_at)"
        " SELECT ma.new, i.url, i.normalized_url, i.link_text, i.position,"
        " i.link_type, i.classification, me.new, msa.new, i.is_followable,"
        " i.is_working, i.last_checked_at, i.redirect_url, i.http_status, i.created_at,"
        " i.updated_at"
        " FROM inc.article_links i"
        " JOIN temp.map_articles ma ON ma.old = i.article_id"
        " LEFT JOIN temp.map_ext me ON me.old = i.external_source_id"
        " LEFT JOIN temp.map_srcart msa ON msa.old = i.source_article_id"
        " JOIN (SELECT article_id, url, COALESCE(position,-1) AS pos, MIN(id) AS rep_id"
        "       FROM inc.article_links"
        "       GROUP BY article_id, url, COALESCE(position,-1)) rep"
        "  ON rep.article_id = i.article_id AND rep.url = i.url"
        "  AND rep.pos = COALESCE(i.position,-1) AND rep.rep_id = i.id"
        f" WHERE NOT EXISTS (SELECT 1 FROM article_links t WHERE {link_key})",
    )
    results["article_links"] = li

    rel = DomainResult()
    rel_key = (
        "t.article_id = ma.new AND COALESCE(t.source_id,-1) = COALESCE(me.new,-1)"
        " AND COALESCE(t.relationship_type,'') = COALESCE(i.relationship_type,'')"
    )
    rel.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.article_source_relationships i"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " JOIN temp.map_articles ma ON ma.old = i.article_id"
        " LEFT JOIN temp.map_ext me ON me.old = i.source_id"
        f" WHERE EXISTS (SELECT 1 FROM article_source_relationships t WHERE {rel_key})",
    )
    # Same rationale as article_links above: no schema-level uniqueness, so collapse
    # incoming-internal duplicates on the merge's own identity key before inserting.
    rel.new = _insert_tracked(
        con, batch_id, "article_source_relationships",
        "INSERT INTO article_source_relationships (article_id, source_id, source_article_id,"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " link_id, relationship_type, time_delta_days, is_temporal_anomaly, confidence_score,"
        " notes, created_at, updated_at)"
        " SELECT ma.new, me.new, msa.new, NULL, i.relationship_type, i.time_delta_days,"
        " i.is_temporal_anomaly, i.confidence_score, i.notes, i.created_at, i.updated_at"
        " FROM inc.article_source_relationships i"
        " JOIN temp.map_articles ma ON ma.old = i.article_id"
        " LEFT JOIN temp.map_ext me ON me.old = i.source_id"
        " LEFT JOIN temp.map_srcart msa ON msa.old = i.source_article_id"
        " JOIN (SELECT article_id, COALESCE(source_id,-1) AS sid,"
        "       COALESCE(relationship_type,'') AS rtype, MIN(id) AS rep_id"
        "       FROM inc.article_source_relationships"
        "       GROUP BY article_id, COALESCE(source_id,-1), COALESCE(relationship_type,''))"
        "  rep ON rep.article_id = i.article_id AND rep.sid = COALESCE(i.source_id,-1)"
        "  AND rep.rtype = COALESCE(i.relationship_type,'') AND rep.rep_id = i.id"
        f" WHERE NOT EXISTS (SELECT 1 FROM article_source_relationships t WHERE {rel_key})",
    )
    results["article_source_relationships"] = rel


def _merge_article_derivations(con, batch_id, results) -> None:
    an = DomainResult()
    an_key = (
        "t.article_id = ma.new AND t.kind = i.kind AND t.model = i.model"
        " AND COALESCE(t.prompt_version,'') = COALESCE(i.prompt_version,'')"
    )
    an.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.article_analyses i"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " JOIN temp.map_articles ma ON ma.old = i.article_id"
        f" WHERE EXISTS (SELECT 1 FROM article_analyses t WHERE {an_key})",
    )
    an.new = _insert_tracked(
        con, batch_id, "article_analyses",
        "INSERT INTO article_analyses (article_id, kind, result, model, prompt_version, created_at)"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " SELECT ma.new, i.kind, i.result, i.model, i.prompt_version, i.created_at"
        " FROM inc.article_analyses i JOIN temp.map_articles ma ON ma.old = i.article_id"
        f" WHERE NOT EXISTS (SELECT 1 FROM article_analyses t WHERE {an_key})",
    )
    results["article_analyses"] = an

    md = DomainResult()
    # The dedup key MUST match the real UNIQUE constraint
    # (uq_amd_article_date = article_id, mentioned_on, precision). The old key used
    # `snippet` instead of `precision`, so an incoming row with the same date+precision
    # but a different snippet passed this NOT-EXISTS guard and then violated the unique
    # constraint -> "UNIQUE constraint failed: article_mentioned_dates.article_id,
    # mentioned_on, precision" on restore (P0-2, field test 2026-06-22; the maintainer's
    # own backup failed to preview). Match the constraint exactly.
    md_key = (
        "t.article_id = ma.new AND t.mentioned_on = i.mentioned_on"
        " AND t.precision = i.precision"
    )
    md.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.article_mentioned_dates i"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " JOIN temp.map_articles ma ON ma.old = i.article_id"
        f" WHERE EXISTS (SELECT 1 FROM article_mentioned_dates t WHERE {md_key})",
    )
    # INSERT OR IGNORE is belt-and-braces: even if the INCOMING corpus itself carries
    # duplicate (article, date, precision) rows (an old backup predating the unique
    # constraint), or two map to the same local id, the second is silently skipped
    # rather than aborting the whole restore. _insert_tracked counts only rows that
    # actually landed (rowid watermark), so an ignored row is correctly not counted.
    md.new = _insert_tracked(
        con, batch_id, "article_mentioned_dates",
        "INSERT OR IGNORE INTO article_mentioned_dates (article_id, mentioned_on, precision,"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " snippet, confidence, extractor, status, created_at)"
        " SELECT ma.new, i.mentioned_on, i.precision, i.snippet, i.confidence, i.extractor,"
        " i.status, i.created_at"
        " FROM inc.article_mentioned_dates i JOIN temp.map_articles ma ON ma.old = i.article_id"
        f" WHERE NOT EXISTS (SELECT 1 FROM article_mentioned_dates t WHERE {md_key})",
    )
    results["article_mentioned_dates"] = md


def _merge_wiki(con, batch_id, results) -> None:
    r = DomainResult()
    r.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.wiki_pages i WHERE EXISTS"
        " (SELECT 1 FROM wiki_pages m WHERE m.wiki = i.wiki AND m.title = i.title)",
    )
    r.new = _insert_tracked(
        con, batch_id, "wiki_pages",
        "INSERT INTO wiki_pages (wiki, title, pageid, watched, category, baseline_revid,"
        " baseline_text, last_revid, last_checked_at, missing, wiki_categories, created_at)"
        " SELECT i.wiki, i.title, i.pageid, i.watched, i.category, i.baseline_revid,"
        " i.baseline_text, i.last_revid, i.last_checked_at, i.missing, i.wiki_categories,"
        " i.created_at FROM inc.wiki_pages i"
        " WHERE NOT EXISTS (SELECT 1 FROM wiki_pages m WHERE m.wiki = i.wiki AND m.title = i.title)",
    )
    for row in _q(
        con,
        "SELECT i.wiki || ':' || i.title FROM inc.wiki_pages i WHERE NOT EXISTS"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " (SELECT 1 FROM wiki_pages m WHERE m.wiki = i.wiki AND m.title = i.title)"
        f" LIMIT {_SAMPLE_LIMIT}",
    ):
        r.samples.append(row[0])
    _build_map(
        con, "map_wiki",
        "SELECT i.id, m.id FROM inc.wiki_pages i"
        " JOIN wiki_pages m ON m.wiki = i.wiki AND m.title = i.title",
    )
    rev = DomainResult()
    rev.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.wiki_revisions i"
        " JOIN temp.map_wiki mw ON mw.old = i.page_id"
        " WHERE EXISTS (SELECT 1 FROM wiki_revisions t"
        "  WHERE t.page_id = mw.new AND t.revid = i.revid)",
    )
    rev.new = _insert_tracked(
        con, batch_id, "wiki_revisions",
        "INSERT INTO wiki_revisions (page_id, revid, parent_revid, timestamp, editor,"
        " editor_anon, comment, size, delta_bytes, tags, minor, bot, diff, ores_damaging,"
        " ores_goodfaith, ores_provenance, flagged, flag_reasons, created_at)"
        " SELECT mw.new, i.revid, i.parent_revid, i.timestamp, i.editor,"
        " i.editor_anon, i.comment, i.size, i.delta_bytes, i.tags, i.minor, i.bot, i.diff,"
        " i.ores_damaging, i.ores_goodfaith, i.ores_provenance, i.flagged, i.flag_reasons,"
        " i.created_at"
        " FROM inc.wiki_revisions i JOIN temp.map_wiki mw ON mw.old = i.page_id"
        " WHERE NOT EXISTS (SELECT 1 FROM wiki_revisions t"
        "  WHERE t.page_id = mw.new AND t.revid = i.revid)",
    )
    results["wiki_pages"] = r
    results["wiki_revisions"] = rev


def _merge_law(con, batch_id, results) -> None:
    r = DomainResult()
    r.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.law_documents i WHERE EXISTS"
        " (SELECT 1 FROM law_documents m WHERE m.jurisdiction = i.jurisdiction AND m.url = i.url)",
    )
    r.new = _insert_tracked(
        con, batch_id, "law_documents",
        "INSERT INTO law_documents (jurisdiction, title, url, official_url, category,"
        " consolidated, watched, baseline_text, baseline_hash, last_hash, last_size,"
        " last_checked_at, last_status, created_at)"
        " SELECT i.jurisdiction, i.title, i.url, i.official_url, i.category,"
        " i.consolidated, i.watched, i.baseline_text, i.baseline_hash, i.last_hash,"
        " i.last_size, i.last_checked_at, i.last_status, i.created_at"
        " FROM inc.law_documents i"
        " WHERE NOT EXISTS (SELECT 1 FROM law_documents m"
        "  WHERE m.jurisdiction = i.jurisdiction AND m.url = i.url)",
    )
    _build_map(
        con, "map_law",
        "SELECT i.id, m.id FROM inc.law_documents i"
        " JOIN law_documents m ON m.jurisdiction = i.jurisdiction AND m.url = i.url",
    )
    rev = DomainResult()
    rev.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.law_revisions i JOIN temp.map_law ml ON ml.old = i.document_id"
        " WHERE EXISTS (SELECT 1 FROM law_revisions t"
        "  WHERE t.document_id = ml.new AND t.content_hash = i.content_hash)",
    )
    rev.new = _insert_tracked(
        con, batch_id, "law_revisions",
        "INSERT INTO law_revisions (document_id, observed_at, content_hash, size, delta_bytes,"
        " diff, flagged, flag_reasons, created_at)"
        " SELECT ml.new, i.observed_at, i.content_hash, i.size, i.delta_bytes, i.diff,"
        " i.flagged, i.flag_reasons, i.created_at"
        " FROM inc.law_revisions i JOIN temp.map_law ml ON ml.old = i.document_id"
        " WHERE NOT EXISTS (SELECT 1 FROM law_revisions t"
        "  WHERE t.document_id = ml.new AND t.content_hash = i.content_hash)",
    )
    results["law_documents"] = r
    results["law_revisions"] = rev


def _merge_markets(con, batch_id, results) -> None:
    r = DomainResult()
    key = (
        "t.symbol = i.symbol AND COALESCE(t.market,'') = COALESCE(i.market,'')"
        " AND t.observed_on = i.observed_on AND COALESCE(t.source,'') = COALESCE(i.source,'')"
        " AND t.currency = i.currency AND t.unit = i.unit"
    )
    r.duplicate = _count(
        con,
        f"SELECT COUNT(*) FROM inc.commodity_prices i WHERE EXISTS"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        f" (SELECT 1 FROM commodity_prices t WHERE {key} AND t.price = i.price)",
    )
    # Same observation key, different price: a DISAGREEMENT between corpora.
    # Local kept; both values surfaced -- never averaged, never silently replaced.
    r.conflict = _count(
        con,
        f"SELECT COUNT(*) FROM inc.commodity_prices i WHERE EXISTS"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        f" (SELECT 1 FROM commodity_prices t WHERE {key} AND t.price <> i.price)",
    )
    for row in _q(
        con,
        f"SELECT i.symbol, i.observed_on, i.price,"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        f" (SELECT t.price FROM commodity_prices t WHERE {key} AND t.price <> i.price LIMIT 1)"
        f" FROM inc.commodity_prices i WHERE EXISTS"
        f" (SELECT 1 FROM commodity_prices t WHERE {key} AND t.price <> i.price)"
        f" LIMIT {_SAMPLE_LIMIT}",
    ):
        r.conflicts.append(
            {"symbol": row[0], "observed_on": row[1], "incoming": row[2], "local": row[3]}
        )
    # `commodity_prices` carries NO unique constraint at the schema level (unlike
    # `keywords`, this is not a deliberate design choice -- just never added). The
    # merge's OWN dedup key above already treats (symbol, market, observed_on,
    # source, currency, unit) as the identity of one observation (a mismatched
    # price at the same key is reported as a CONFLICT, never silently accepted) --
    # so an INCOMING corpus carrying two rows for that same identity (audit
    # 2026-07-16, following the keyword_mentions collapse fix) would insert BOTH
    # as separate new rows instead of collapsing them, quietly perpetuating a
    # duplicate-looking observation. The `rep` join keeps only the lowest incoming
    # id per identity group, same tie-break convention as `_merge_keywords`.
    r.new = _insert_tracked(
        con, batch_id, "commodity_prices",
        "INSERT INTO commodity_prices (symbol, market, observed_on, price, currency, unit,"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " source, created_at)"
        " SELECT i.symbol, i.market, i.observed_on, i.price, i.currency, i.unit, i.source,"
        " i.created_at FROM inc.commodity_prices i"
        " JOIN (SELECT symbol, COALESCE(market,'') AS mkt, observed_on,"
        "       COALESCE(source,'') AS src, currency, unit, MIN(id) AS rep_id"
        "       FROM inc.commodity_prices"
        "       GROUP BY symbol, COALESCE(market,''), observed_on, COALESCE(source,''),"
        "                currency, unit) rep"
        "  ON rep.symbol = i.symbol AND rep.mkt = COALESCE(i.market,'')"
        "  AND rep.observed_on = i.observed_on AND rep.src = COALESCE(i.source,'')"
        "  AND rep.currency = i.currency AND rep.unit = i.unit AND rep.rep_id = i.id"
        f" WHERE NOT EXISTS (SELECT 1 FROM commodity_prices t WHERE {key})",
    )
    results["commodity_prices"] = r

    er = DomainResult()
    er_key = "t.source_id = ms.new AND t.symbol = i.symbol AND t.url = i.url"
    er.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.market_extraction_rules i"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " JOIN temp.map_sources ms ON ms.old = i.source_id"
        f" WHERE EXISTS (SELECT 1 FROM market_extraction_rules t WHERE {er_key})",
    )
    er.new = _insert_tracked(
        con, batch_id, "market_extraction_rules",
        "INSERT INTO market_extraction_rules (source_id, category, symbol, label, url,"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " selector, attribute, value_regex, currency, unit, market, enabled, last_run_at,"
        " last_status, created_at, updated_at)"
        " SELECT ms.new, i.category, i.symbol, i.label, i.url, i.selector, i.attribute,"
        " i.value_regex, i.currency, i.unit, i.market, i.enabled, i.last_run_at,"
        " i.last_status, i.created_at, i.updated_at"
        " FROM inc.market_extraction_rules i JOIN temp.map_sources ms ON ms.old = i.source_id"
        f" WHERE NOT EXISTS (SELECT 1 FROM market_extraction_rules t WHERE {er_key})",
    )
    results["market_extraction_rules"] = er


def _merge_rule_tables(con, batch_id, results) -> None:
    r = DomainResult()
    r.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.link_classification_rules i WHERE EXISTS"
        " (SELECT 1 FROM link_classification_rules m WHERE m.rule_name = i.rule_name)",
    )
    r.new = _insert_tracked(
        con, batch_id, "link_classification_rules",
        "INSERT INTO link_classification_rules (rule_name, pattern, classification_type,"
        " priority, is_active, created_at, updated_at)"
        " SELECT i.rule_name, i.pattern, i.classification_type, i.priority, i.is_active,"
        " i.created_at, i.updated_at FROM inc.link_classification_rules i"
        " WHERE NOT EXISTS (SELECT 1 FROM link_classification_rules m"
        "  WHERE m.rule_name = i.rule_name)",
    )
    r.duplicate += _count(
        con,
        "SELECT COUNT(*) FROM inc.source_credibility_rules i WHERE EXISTS"
        " (SELECT 1 FROM source_credibility_rules m WHERE m.rule_name = i.rule_name)",
    )
    r.new += _insert_tracked(
        con, batch_id, "source_credibility_rules",
        "INSERT INTO source_credibility_rules (rule_name, factor, weight, min_value,"
        " max_value, is_inverse, is_active, created_at, updated_at)"
        " SELECT i.rule_name, i.factor, i.weight, i.min_value, i.max_value, i.is_inverse,"
        " i.is_active, i.created_at, i.updated_at FROM inc.source_credibility_rules i"
        " WHERE NOT EXISTS (SELECT 1 FROM source_credibility_rules m"
        "  WHERE m.rule_name = i.rule_name)",
    )
    results["rule_tables"] = r


def _merge_source_candidates(con, batch_id, results) -> None:
    r = DomainResult()
    r.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.source_candidates i WHERE EXISTS"
        " (SELECT 1 FROM source_candidates m WHERE m.domain = i.domain)",
    )
    r.new = _insert_tracked(
        con, batch_id, "source_candidates",
        "INSERT INTO source_candidates (domain, suggested_name, channel, evidence, status,"
        " first_seen, last_seen)"
        " SELECT i.domain, i.suggested_name, i.channel, i.evidence, i.status,"
        " i.first_seen, i.last_seen FROM inc.source_candidates i"
        " WHERE NOT EXISTS (SELECT 1 FROM source_candidates m WHERE m.domain = i.domain)",
    )
    results["source_candidates"] = r


# --------------------------------------------------------------------------- #
#  Verification on the working copy (design §3: the merge gate)
# --------------------------------------------------------------------------- #
def verify_copy(working_copy: Path, staged_corpus: Path, batch_id: int) -> dict:
    """Post-merge verification, all on the copy. Any failure aborts the restore
    BEFORE the swap -- the live DB never sees an unverified merge."""
    from src.database.connect import attach
    from src.database.connect import connect as db_connect

    con = db_connect(working_copy, check_same_thread=False)
    try:
        v: dict = {}
        v["quick_check"] = con.execute("PRAGMA quick_check").fetchone()[0]
        fk = con.execute("PRAGMA foreign_key_check").fetchall()
        v["foreign_key_violations"] = len(fk)

        has_fts = bool(
            con.execute(
                "SELECT 1 FROM sqlite_master WHERE name='article_fts' LIMIT 1"
            ).fetchone()
        )
        if has_fts:
            con.execute("INSERT INTO article_fts(article_fts) VALUES('rebuild')")
            con.commit()
            v["fts_rows"] = _count(con, "SELECT COUNT(*) FROM article_fts")
        v["articles"] = _count(con, "SELECT COUNT(*) FROM articles")
        v["fts_matches_articles"] = (not has_fts) or v["fts_rows"] == v["articles"]

        # Sampled transfer-integrity check: merged articles' content must equal
        # the staged source's content byte-for-byte (joined on the content hash).
        attach(con, staged_corpus, "inc")
        bad = _count(
            con,
            "SELECT COUNT(*) FROM ("
            " SELECT m.id FROM merged_rows r"
            " JOIN articles m ON m.id = r.row_id"
            " JOIN inc.articles i ON i.hash = m.hash"
            " WHERE r.batch_id = ? AND r.table_name = 'articles' AND i.content <> m.content"
            " LIMIT 32)",
            (batch_id,),
        )
        v["sampled_content_mismatches"] = bad
        v["ok"] = (
            v["quick_check"] == "ok"
            and v["foreign_key_violations"] == 0
            and v["fts_matches_articles"]
            and bad == 0
        )
        return v
    finally:
        con.close()


# --------------------------------------------------------------------------- #
#  Side files (additive + idempotent; local always wins) and custody chains
# --------------------------------------------------------------------------- #
def merge_side_files(staged: StagedArtifact) -> dict:
    report: dict = {}
    base = data_dir()

    state: dict = {}
    for name, path in staged.member_paths("state"):
        local = base / name
        if name in ("calendar_feed_imports.json", "calendar_feed_checks.json"):
            try:
                incoming = json.loads(path.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                state[name] = {"action": "skipped", "reason": "unreadable in artifact"}
                continue
            from src.events.feeds import merge_imported_store

            state[name] = merge_imported_store(name, incoming)
        elif not local.exists():
            local.parent.mkdir(parents=True, exist_ok=True)
            tmp = local.with_name(local.name + ".tmp")
            tmp.write_bytes(path.read_bytes())
            os.replace(tmp, local)
            state[name] = {"action": "restored", "reason": "no local file existed"}
        else:
            try:
                same = local.read_bytes() == path.read_bytes()
            except OSError:
                same = False
            state[name] = {
                "action": "kept-local",
                "differs": not same,
                "note": "settings are never overwritten by a merge; adopt manually if wanted",
            }
    report["state"] = state

    ann: dict = {"imported_authors": 0, "kept_local": 0, "errors": []}
    for name, path in staged.member_paths("annotations"):
        local = base / name
        if local.exists():
            ann["kept_local"] += 1
            continue
        if name.startswith("annotations/imported/"):
            # The member is an imported-author RECORD, not a signed bundle: it was
            # written by import_bundle AFTER verification, so its manifest+signature
            # were stripped and it CANNOT be re-verified (its origin was proven at the
            # original import, provenance kept in verify_reason). Re-passing it to
            # import_bundle rejected it as malformed -> every imported author silently
            # failed to restore. Adopt the verified record directly instead, mirroring
            # how mine.json restores; the artifact's own signature vouches for the
            # payload, and local always wins (only adopted when no local record exists).
            try:
                from src.annotations.store import adopt_imported_record

                record = json.loads(path.read_text("utf-8"))
                # Honour the record's own trust flag ONLY for a signature-verified
                # artifact (its signature binds the member bytes = the user's own
                # web-of-trust decisions). An allow-unverified restore carries
                # attacker-controllable member bytes, so its imported authors are
                # adopted UNtrusted (the user re-affirms trust explicitly). The
                # author_id is validated inside adopt_imported_record (path-traversal
                # guard), so a crafted id is reported here, never written.
                res = adopt_imported_record(
                    record, allow_trusted=staged.signature_state == "verified"
                )
                if res.get("adopted"):
                    ann["imported_authors"] += 1
                else:
                    ann["kept_local"] += 1
            except Exception as exc:  # noqa: BLE001 - each author independent, reported
                ann["errors"].append(f"{name}: {exc}")
        else:
            local.parent.mkdir(parents=True, exist_ok=True)
            tmp = local.with_name(local.name + ".tmp")
            tmp.write_bytes(path.read_bytes())
            os.replace(tmp, local)
            ann["restored_mine"] = True
    report["annotations"] = ann

    logs: dict = {}
    for name, path in staged.member_paths("logs"):
        fname = Path(name).name
        local = base / fname
        try:
            incoming_lines = path.read_text("utf-8").splitlines()
        except OSError:
            continue
        existing: set[str] = set()
        if local.exists():
            try:
                existing = set(local.read_text("utf-8").splitlines())
            except OSError:
                existing = set()
        fresh = [ln for ln in incoming_lines if ln and ln not in existing]
        if fresh:
            with open(local, "a", encoding="utf-8") as fh:
                fh.write(
                    f'{{"merged_from": "{staged.origin_fingerprint[:16]}",'
                    f' "lines": {len(fresh)}}}\n'
                )
                fh.write("\n".join(fresh) + "\n")
        logs[fname] = {"appended": len(fresh), "duplicate": len(incoming_lines) - len(fresh)}
    report["logs"] = logs

    keys: dict = {"restored": [], "kept_local": []}
    for name, path in staged.member_paths("keys"):
        local = base / name
        if local.exists():
            keys["kept_local"].append(name)  # the existing identity ALWAYS wins
            continue
        local.parent.mkdir(parents=True, exist_ok=True)
        tmp = local.with_name(local.name + ".tmp")
        tmp.write_bytes(path.read_bytes())
        os.replace(tmp, local)
        local.chmod(0o600)
        keys["restored"].append(name)
    report["keys"] = keys
    return report


def _refresh_event_mirror(side_files: dict) -> dict | None:
    """After the atomic swap, refresh the durable ``event_imports`` mirror so it reflects the
    just-restored calendar events (DB-reliability D1 follow-up, Wave 5 L).

    ``merge_side_files`` unions ``calendar_feed_imports.json`` with ``mirror=False`` because it
    runs PRE-swap, when the live DB is still the OLD corpus that must stay byte-identical
    (torture T1/T7). So without this step the durable, encrypted, backup-carried table would
    stay STALE after a restore until the next normal calendar write re-synced it — defeating
    D1's whole point (the table, not the cleartext JSON, is the durable home of imported
    events). Now the live DB IS the merged corpus, so we FULL-REPLACE the mirror from the
    authoritative merged JSON via the same primitive normal writes use.

    Honest by construction: a full replace from the authoritative JSON CONVERGES (table == JSON)
    and can never double-count; ``sync_imports`` never raises (the JSON stays authoritative on
    any DB hiccup); and a JSON read hiccup must NEVER empty an already-populated table. Returns
    the sync status, or ``None`` when the restore carried no calendar side-file to merge (so the
    report only grows the field when it actually applies)."""
    cal = (side_files or {}).get("state", {}).get("calendar_feed_imports.json", {})
    if not isinstance(cal, dict) or cal.get("action") != "merged":
        return None
    try:
        from src.events.event_store import count as _ev_count
        from src.events.event_store import sync_imports
        from src.events.feeds import load_imports

        merged = load_imports()
        if not merged and _ev_count() > 0:
            # A read hiccup returned {} while the table already holds rows: refusing to
            # DELETE them (the JSON stays authoritative; the mirror re-syncs on next write).
            return {"synced": False, "reason": "empty read guarded"}
        return sync_imports(merged)
    except Exception:  # noqa: BLE001 - the mirror refresh must never undo a committed restore
        _LOG.warning(
            "event_imports mirror refresh after restore failed; the JSON side-file is "
            "authoritative and the mirror re-syncs on the next calendar write",
            exc_info=True,
        )
        return {"synced": False, "reason": "refresh error"}


_CUSTODY_COLS = (
    "seq, item_id, item_hash, action, actor, metadata_json,"
    " prev_entry_hash, entry_hash, signature_json, timestamp_json"
)


def _verify_chain_rows(rows: list) -> tuple[bool, list[str]]:
    from src.custody.log import CustodyEntry, verify_entries

    entries = [
        CustodyEntry(
            seq=r[0], item_id=r[1], item_hash=r[2], action=r[3], actor=r[4],
            metadata=json.loads(r[5] or "{}"), prev_entry_hash=r[6], entry_hash=r[7],
            signature=json.loads(r[8] or "{}"), timestamp=json.loads(r[9] or "{}"),
        )
        for r in rows
    ]
    return verify_entries(entries)


def merge_custody(staged_custody: Path, origin_fingerprint: str) -> dict:
    """Import foreign custody chains into custody_imported_entries: original seqs
    preserved (they are inside the signed core), every chain VERIFIED with the
    keys embedded in its entries, chains NEVER spliced into the local one.
    A failed verification still imports -- marked verified=0 with the reason,
    because the failure itself is evidence.

    Chains the foreign corpus had itself imported (its custody_imported_entries)
    propagate TRANSITIVELY under their original chain ids: an heir corpus keeps
    the whole evidence lineage, each chain standing on its own signatures."""
    src = sqlite3.connect(f"file:{staged_custody}?mode=ro", uri=True)
    try:
        src_tables = {
            r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        chains: list[tuple[str, list]] = []
        if "custody_entries" in src_tables:
            rows = src.execute(
                f"SELECT {_CUSTODY_COLS} FROM custody_entries ORDER BY seq ASC"  # noqa: S608  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
            ).fetchall()
            if rows:
                their_chain = (
                    origin_fingerprint if origin_fingerprint != "unsigned" else "unknown-origin"
                )
                chains.append((their_chain, rows))
        if "custody_imported_entries" in src_tables:
            for (cid,) in src.execute(
                "SELECT DISTINCT chain_id FROM custody_imported_entries"
            ).fetchall():
                rows = src.execute(
                    f"SELECT {_CUSTODY_COLS} FROM custody_imported_entries"  # noqa: S608  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
                    " WHERE chain_id = ? ORDER BY seq ASC",
                    (cid,),
                ).fetchall()
                if rows:
                    chains.append((cid, rows))
    finally:
        src.close()
    if not chains:
        return {"entries": 0, "imported": 0, "duplicate": 0, "chains": []}

    from src.database.connect import connect as db_connect

    dest = db_connect(data_dir() / "custody_log.db", check_same_thread=False)
    try:
        dest.execute(
            """
            CREATE TABLE IF NOT EXISTS custody_imported_entries (
                chain_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                item_id TEXT NOT NULL,
                item_hash TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT,
                metadata_json TEXT NOT NULL,
                prev_entry_hash TEXT NOT NULL,
                entry_hash TEXT NOT NULL,
                signature_json TEXT NOT NULL,
                timestamp_json TEXT NOT NULL,
                verified INTEGER NOT NULL,
                verify_note TEXT,
                imported_at TEXT NOT NULL,
                PRIMARY KEY (chain_id, seq)
            )
            """
        )
        now = datetime.now(UTC).isoformat(timespec="seconds")
        total = imported = 0
        chain_reports = []
        all_ok = True
        problems_acc: list[str] = []
        for chain_id, rows in chains:
            ok, problems = _verify_chain_rows(rows)
            all_ok = all_ok and ok
            problems_acc.extend(problems[:3])
            note = None if ok else "; ".join(problems)[:500]
            chain_new = 0
            for r in rows:
                cur = dest.execute(
                    "INSERT OR IGNORE INTO custody_imported_entries"
                    " (chain_id, seq, item_id, item_hash, action, actor, metadata_json,"
                    "  prev_entry_hash, entry_hash, signature_json, timestamp_json,"
                    "  verified, verify_note, imported_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (chain_id, *r, 1 if ok else 0, note, now),
                )
                chain_new += cur.rowcount or 0
            total += len(rows)
            imported += chain_new
            chain_reports.append(
                {"chain_id": chain_id[:16], "entries": len(rows), "new": chain_new,
                 "verified": ok}
            )
        dest.commit()
    finally:
        dest.close()
    return {
        "entries": total,
        "imported": imported,
        "duplicate": total - imported,
        "chains": chain_reports,
        "verified": all_ok,
        "problems": problems_acc[:5],
    }


# --------------------------------------------------------------------------- #
#  Orchestration
# --------------------------------------------------------------------------- #
def _prune_snapshots(keep: int = _SNAPSHOT_KEEP) -> list[str]:
    snaps = sorted(data_dir().glob("pre-restore-*.db"), key=lambda p: p.name, reverse=True)
    removed = []
    for p in snaps[keep:]:
        try:
            p.unlink()
            removed.append(p.name)
        except OSError:  # pragma: no cover
            pass
    return removed


def _default_reindex_commit_batch() -> int:
    """``OO_REINDEX_COMMIT_BATCH`` -- the SAME env var the standalone "re-index the
    whole corpus" job already reads (src/analytics/reindex_job.py), so one knob tunes
    fsync batching for both the background job AND a restore's post-merge re-index."""
    try:
        return max(1, int(os.getenv("OO_REINDEX_COMMIT_BATCH", "1") or "1"))
    except ValueError:
        return 1


def _corpus_snapshot(session) -> dict:
    """A near-free snapshot of the corpus: COUNT/DISTINCT/MIN/MAX aggregates over
    INDEXED columns only -- never a whole-table content scan. Taken once on the live
    corpus right before a commit-restore's atomic swap and once right after, so the
    UI can render the post-import CORPUS-DELTA view (maintainer field report
    2026-07-20: "I'm sure it doesn't contain 5 million articles" -- the old headline
    summed every merged TABLE, not articles) as a plain before -> after per
    dimension, with no post-merge re-scan of the corpus needed."""
    from sqlalchemy import func

    from src.database.models import Article, Keyword, Source

    date_min, date_max = session.query(
        func.min(Article.published_at), func.max(Article.published_at)
    ).one()
    return {
        "articles": int(session.query(func.count(Article.id)).scalar() or 0),
        "sources": int(session.query(func.count(Source.id)).scalar() or 0),
        "languages": int(
            session.query(func.count(func.distinct(Article.language)))
            .filter(Article.language.isnot(None))
            .scalar()
            or 0
        ),
        "countries": int(
            session.query(func.count(func.distinct(Article.country)))
            .filter(Article.country.isnot(None))
            .scalar()
            or 0
        ),
        "keywords": int(session.query(func.count(Keyword.id)).scalar() or 0),
        "date_min": date_min.isoformat() if date_min else None,
        "date_max": date_max.isoformat() if date_max else None,
    }


def reindex_imported_articles(
    batch_id: int,
    *,
    commit_batch: int | None = None,
    workers: int | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
) -> dict:
    """Recompute CORE-ENGINE metadata for the articles imported by ``batch_id``.

    Maintainer ruling 2026-06-19 (P0-4): a backup may have been produced by an OLDER
    extraction engine, so its merged-in keyword/date/place/entity rows can be
    misaligned with the current engine. Run AFTER the atomic swap, so the ORM points
    at the merged live DB and ``merged_rows`` (carried in from the working copy) names
    the imported article rowids = their live ids (articles.id == rowid). ``index_article``
    overwrites those derived rows with current-engine output; AI artifacts
    (article_analyses summaries/translations, ai_keyword) are left verbatim.

    ``commit_batch`` / ``workers`` / ``progress_cb`` (restore-merge re-index perf,
    2026-07-19 -- field report: this used to be an entirely silent, single-core,
    per-article-fsync phase that a large restore could spend HOURS in while the
    caller's UI stayed frozen on the prior "merging" step's last progress) are
    threaded straight through to :func:`src.analytics.store.reindex_articles` -- see
    there for the batching/parallel-precompute contract. ``commit_batch=None``
    (default) reads the env var above; ``workers=None`` uses
    :func:`src.analytics.reindex_parallel.worker_count`'s own default."""
    from sqlalchemy import text

    from src.analytics.extract import get_extractor
    from src.analytics.store import reindex_articles
    from src.database.session import session_scope

    if commit_batch is None:
        commit_batch = _default_reindex_commit_batch()

    with session_scope() as session:
        rows = session.execute(
            text(
                "SELECT row_id FROM merged_rows "
                "WHERE batch_id = :b AND table_name = 'articles'"
            ),
            {"b": batch_id},
        ).fetchall()
        ids = [int(r[0]) for r in rows]
        if not ids:
            return {"reindexed": 0, "failed": 0}
        return reindex_articles(
            session,
            extractor=get_extractor("baseline"),
            article_ids=ids,
            commit_batch=commit_batch,
            workers=workers,
            progress_cb=progress_cb,
        )


def import_cache_mb() -> int:
    """Enlarged SQLite page-cache MiB for the import merge connection
    specifically (field-feedback Session A §4, "import owns the machine") --
    SEPARATE from the app's general ``OO_SQLITE_CACHE_MB``
    (``src/config/power_profiles.py``), which never reaches this connection
    (opened via the raw ``connect()`` factory, not the pooled app engine).
    ``OO_IMPORT_CACHE_MB`` overrides; default 512 MiB (8x the app's own 64 MiB
    default) -- a resource-usage tuning knob only, never a behaviour change."""
    raw = os.getenv("OO_IMPORT_CACHE_MB", "").strip()
    if raw:
        try:
            return max(2, int(raw))
        except ValueError:
            pass
    return 512


def run_restore(
    staged: StagedArtifact,
    *,
    commit: bool,
    allow_unverified: bool = False,
    reindex_imported: bool = True,
    progress_cb=None,
    reindex_commit_batch: int | None = None,
    reindex_workers: int | None = None,
    reindex_progress_cb: Callable[[int, int], None] | None = None,
    merge_cache_mb: int | None = None,
    stage_progress_cb: Callable[[str], None] | None = None,
) -> dict:
    """Preview (commit=False) or perform (commit=True) a merge-restore.

    ``reindex_imported`` (default True): after the swap, recompute core-engine
    metadata for the imported articles (P0-4). The MERGE-ENGINE correctness suite
    (commutativity/idempotency/crash-safety) passes False to test the engine in
    isolation — the re-index is a one-directional post-step (it makes the FULL
    restore direction-dependent in DERIVED data by design) with its own test.

    ``reindex_commit_batch`` / ``reindex_workers`` / ``reindex_progress_cb``
    (2026-07-19): passed straight through to :func:`reindex_imported_articles` for
    that post-swap re-index. Kept as a SEPARATE callback from ``progress_cb`` (which
    reports the 14-step table-merge above via a ``(step_done, step_total, step_name)``
    signature): the re-index reports a plain ``(done, total)`` over a different unit
    of work (articles, not table-merge steps), so a caller distinguishes the two
    phases explicitly instead of guessing from a shared callback's arity.

    ``merge_cache_mb`` (2026-07-24, "import owns the machine"): forwarded to
    :func:`merge_corpus`'s ``cache_mb`` — a resource-usage tuning knob only.

    Preview and commit run THE SAME merge code against a disposable working
    copy, so the preview's numbers are exactly what a commit would do to the
    then-current corpus.

    PER-STAGE TIMING (2026-07-24 field-feedback Session A §4, "instrument
    first"): every distinct stage's wall-clock time is recorded into
    ``report["timings"]`` (via :class:`~src.backup.timing.StageTimings`) —
    MEASUREMENT ONLY, the timer's own exception-safety property guarantees it
    never changes control flow or swallows a failure (see
    ``tests/test_backup_timing.py``). Attached before every return so even a
    refused/preview-only report carries the stages that actually ran.

    ``stage_progress_cb`` ("progress everywhere", §4 item 2): fired with just
    the stage NAME the instant each stage BEGINS — a coarse "now doing: swap"
    ping for the stages (B/D/E/G) that have no callback of their own (unlike
    the fine-grained 14-step ``progress_cb`` or the per-article
    ``reindex_progress_cb``). Report-only, never load-bearing."""
    from src.backup.sqlite_backup import live_db_path
    from src.backup.timing import StageTimings
    from src.database.session import dispose_engine, init_db

    timings = StageTimings(on_start=stage_progress_cb)
    # Fold in stage-A (decrypt/reassemble) timing, already measured by whichever
    # producer (read_artifact / read_stream_backup / read_volume_backup) built
    # this StagedArtifact — run_restore itself never touches stage A (it only
    # ever receives an already-staged artifact), so this is the one place all
    # 7 lettered stages (A-G) converge into ONE report.
    for _name, _seconds in (staged.stage_a_timings or {}).items():
        timings.record(f"stage_a:{_name}", _seconds)

    with timings.stage("prepare_staged"):
        original_rev = prepare_staged_corpus(staged, allow_unverified=allow_unverified)

    working = staged.staging_dir / "working.db"
    if working.exists():
        working.unlink()
    # The working copy PRESERVES the live at-rest state: merging on an
    # encrypted corpus must never yield a plaintext live file at the swap.
    from src.database.connect import snapshot_preserving

    with timings.stage("snapshot_working_copy"):
        snapshot_preserving(live_db_path(), working)

    meta = {
        "artifact_kind": staged.kind,
        "origin_fingerprint": staged.origin_fingerprint,
        "app_version": (staged.manifest or {}).get("app_version"),
        "alembic_rev": original_rev,
        "manifest": staged.manifest,
    }
    # Wrap the caller's own progress_cb so EACH of the 14 merge steps also gets
    # its own per-step timing (into "merge_step:<name>"), with NO change to
    # merge_corpus's internals — it already wraps every progress_cb call in its
    # own try/except ("progress reporting must never break a merge"), so this
    # wrapper inherits that same safety for free; it never raises itself.
    _step_clock: dict[str, float | None] = {"t": None}

    def _timed_progress_cb(done: int, total: int, name: str) -> None:
        now = time.monotonic()
        if _step_clock["t"] is not None:
            timings.record(f"merge_step:{name}", now - _step_clock["t"])
        _step_clock["t"] = now
        if progress_cb is not None:
            progress_cb(done, total, name)

    with timings.stage("merge"):
        _step_clock["t"] = time.monotonic()
        counts, batch_id = merge_corpus(
            staged.corpus_path, working, meta,
            progress_cb=_timed_progress_cb, cache_mb=merge_cache_mb,
        )
    with timings.stage("verify"):
        verification = verify_copy(working, staged.corpus_path, batch_id)

    report: dict = {
        "artifact_kind": staged.kind,
        "signature_state": staged.signature_state,
        "origin_fingerprint": staged.origin_fingerprint,
        "artifact_schema_rev": original_rev,
        # Honest encryption verdict (field test 2026-06-19 P0-2): True when the
        # uploaded artifact was AES-256-GCM (OOENC1) at rest and we had to decrypt
        # it. Lets the preview UI confirm a backup is genuinely encrypted.
        "encrypted": staged.encrypted,
        "plan": counts,
        "verification": verification,
        "committed": False,
    }

    if not verification["ok"]:
        report["refused"] = "post-merge verification failed; live database untouched"
        report["timings"] = timings.report()
        return report
    if not commit:
        report["timings"] = timings.report()
        return report

    # ---- commit path ------------------------------------------------------ #
    # Corpus-delta "before": the live corpus is still byte-identical at this point
    # (the merge above only touched the disposable working copy) -- so this is the
    # true pre-import state. Best-effort: a snapshot hiccup must never abort an
    # otherwise-good restore; absence just means the UI shows no delta view.
    with timings.stage("corpus_delta_before"):
        try:
            from src.database.session import session_scope

            with session_scope() as _before_sess:
                report["corpus_delta"] = {"before": _corpus_snapshot(_before_sess)}
        except Exception:  # noqa: BLE001 - a snapshot failure must never block a commit
            _LOG.warning("pre-restore corpus snapshot failed", exc_info=True)

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    snapshot = data_dir() / f"pre-restore-{ts}.db"
    with timings.stage("pre_restore_snapshot"):
        snapshot_preserving(live_db_path(), snapshot)
    report["pre_restore_snapshot"] = str(snapshot)

    with timings.stage("side_files_and_custody"):
        report["side_files"] = merge_side_files(staged)
        if staged.custody_path is not None:
            report["custody"] = merge_custody(staged.custody_path, staged.origin_fingerprint)

    # Persist the final report inside the copy BEFORE it becomes the live DB.
    # (The timings captured up to this instant are what gets written; every
    # LATER stage below is necessarily missing from THIS particular copy —
    # honest by construction, since the swap/reindex/post-steps haven't
    # happened yet at the moment this row is written.)
    from src.database.connect import connect as db_connect

    with timings.stage("report_json_write"):
        report["timings"] = timings.report()
        con = db_connect(working, check_same_thread=False)
        try:
            con.execute(
                "UPDATE merge_batches SET report_json = ? WHERE id = ?",
                (json.dumps({k: v for k, v in report.items() if k != "plan"}), batch_id),
            )
            con.commit()
        finally:
            con.close()

    # The atomic swap itself: kept as close to bare as possible (the highest
    # crash-sensitivity moment in the whole engine) -- the timer adds only two
    # cheap time.monotonic() calls around the UNCHANGED block, never a new
    # exception path (a raise here still propagates exactly as before).
    with timings.stage("swap"):
        target = live_db_path()
        dispose_engine()
        for suffix in ("-wal", "-shm"):
            stale = target.with_name(target.name + suffix)
            if stale.exists():
                stale.unlink()
        os.replace(working, target)  # atomic on the same filesystem
        init_db()

    report["committed"] = True
    report["batch_id"] = batch_id

    # Corpus-delta "after": same cheap aggregates, now against the just-swapped-in
    # merged corpus. Only set alongside "before" (both best-effort; a partial pair
    # is dropped rather than shown as a false delta).
    with timings.stage("corpus_delta_after"):
        if "corpus_delta" in report:
            try:
                from src.database.session import session_scope as _session_scope_after

                with _session_scope_after() as _after_sess:
                    report["corpus_delta"]["after"] = _corpus_snapshot(_after_sess)
            except Exception:  # noqa: BLE001 - never undo a committed, additive restore
                _LOG.warning("post-restore corpus snapshot failed", exc_info=True)
                report.pop("corpus_delta", None)

    # DB-7 (corpus-epoch → restore-merge): a committed merge is a bulk mutation of the live
    # corpus, and the restore is "the one residual mutator" not yet wired to the corpus
    # epoch. Bump it once, unconditionally, so the disposable derived rollups (the
    # keyword_daily / source_coverage serves) FULL-rebuild after the restore instead of
    # trusting an incremental id-watermark merge across it. The post-swap re-index below
    # ALSO bumps when it runs, but this explicit bump covers reindex_imported=False (the
    # merge-engine + torture path), an empty import set, and a re-index that hiccups after
    # the additive merge already committed. Over-bumping is harmless (it only forces a
    # correct rebuild); best-effort so a coordination write never undoes a committed restore.
    with timings.stage("corpus_epoch_bump"):
        try:
            from src.analytics.corpus_epoch import bump_corpus_epoch
            from src.database.session import session_scope

            with session_scope() as _epoch_sess:
                report["corpus_epoch"] = bump_corpus_epoch(_epoch_sess, reason="restore_merge")
                # S6: the additive merge inserted articles onto existing sources (mapped by
                # domain) WITHOUT touching Source.article_count, so it is now stale-low and, being
                # non-NULL, the read fallback would never fire -> a wrong count shown as exact
                # (skeptic finding). Reconcile it authoritatively (cheap; sources are few).
                from src.analytics.store import reconcile_source_counters

                reconcile_source_counters(_epoch_sess)
        except Exception:  # noqa: BLE001 - a coordination bump must never undo a committed restore
            _LOG.warning("corpus-epoch bump after restore-merge failed", exc_info=True)

    # DB-reliability D1 follow-up (Wave 5 L): refresh the durable ``event_imports`` mirror
    # from the merged side-file now that the live DB IS the restored corpus. merge_side_files
    # unioned the JSON with mirror=False PRE-swap (the OLD live DB had to stay untouched), so
    # the durable table would otherwise stay stale until the next calendar write. Best-effort
    # + guarded (see _refresh_event_mirror): a full replace from the authoritative JSON, never
    # a double-count, never undoes a committed restore.
    with timings.stage("event_mirror_refresh"):
        ev_mirror = _refresh_event_mirror(report.get("side_files") or {})
        if ev_mirror is not None:
            report["event_mirror"] = ev_mirror
    # P0-4 (maintainer ruling 2026-06-19): recompute the CORE-ENGINE derived metadata
    # for the newly-imported articles so an OLD backup aligns with the CURRENT engine
    # (keywords, date/place/entity extraction, sentiment); AI artifacts are left
    # verbatim. Best-effort: the restore is already committed AND additive, so a
    # re-index hiccup must never undo it.
    if reindex_imported:
        with timings.stage("reindex"):
            try:
                report["reindexed"] = reindex_imported_articles(
                    batch_id,
                    commit_batch=reindex_commit_batch,
                    workers=reindex_workers,
                    progress_cb=reindex_progress_cb,
                )
            except Exception:  # noqa: BLE001 - never undo a committed, additive restore
                _LOG.warning("post-restore re-index of imported articles failed", exc_info=True)
                # The whole batch failed before touching a single article, so NONE of the
                # imported articles got re-indexed -- "failed" must be the true imported
                # count (from the already-known plan), not 0. Reporting 0 here would read
                # as "nothing needed re-indexing", which is the fabricated-signal the rest
                # of this feature is built to avoid (see reindex_imported_articles above).
                _imported = int((counts.get("articles") or {}).get("new") or 0)
                report["reindexed"] = {"reindexed": 0, "failed": _imported, "skipped": "see server log"}

    # S3.3 (2026-07-23 field-feedback workflow, import-time screening): scan the
    # NEWLY-MERGED articles (the exact batch_id's rows in merged_rows -- the same set
    # reindex_imported_articles above uses) for already-known non-article junk (the
    # #659 URL-shape rules + the NAV-SOUP prose gate), stamping any detected candidate
    # via the REVERSIBLE S3.2 quarantine flag -- never a delete. Best-effort: a
    # quarantine-scan hiccup must never undo a committed, additive restore.
    with timings.stage("quarantine_scan"):
        try:
            from sqlalchemy import text as _text

            from src.analytics.quarantine_job import default_quarantine_candidates_batch
            from src.database.session import session_scope as _quarantine_session_scope

            with _quarantine_session_scope() as _q_sess:
                new_article_ids = [
                    int(r[0])
                    for r in _q_sess.execute(
                        _text(
                            "SELECT row_id FROM merged_rows "
                            "WHERE batch_id = :b AND table_name = 'articles'"
                        ),
                        {"b": batch_id},
                    ).fetchall()
                ]
                if new_article_ids:
                    report["quarantine_summary"] = default_quarantine_candidates_batch(
                        _q_sess, article_ids=new_article_ids, write=True
                    )
        except Exception:  # noqa: BLE001 - never undo a committed, additive restore
            _LOG.warning("post-restore quarantine scan failed", exc_info=True)

    # S3.5 (field-feedback A1): the "work induced" queue -- corpus-wide totals (not
    # scoped to just this import; no cheap before/after delta exists for these
    # counters yet, stated explicitly in the persisted report's own rendering).
    # Best-effort; never blocks a committed restore.
    with timings.stage("work_induced_tally"):
        try:
            from sqlalchemy import func as _func

            from src.catalog.qualification import STATUS_QUALIFIED
            from src.database.models import Source
            from src.database.session import session_scope as _work_session_scope

            with _work_session_scope() as _w_sess:
                report["work_induced"] = {
                    "sources_pending": int(
                        _w_sess.query(_func.count(Source.id))
                        .filter(Source.enabled.is_(True), Source.status != STATUS_QUALIFIED)
                        .scalar()
                        or 0
                    ),
                    "sources_candidates": int(
                        _w_sess.query(_func.count(Source.id)).filter(Source.enabled.is_(False)).scalar()
                        or 0
                    ),
                }
        except Exception:  # noqa: BLE001 - never undo a committed, additive restore
            _LOG.warning("post-restore work-induced tally failed", exc_info=True)

    # S3.5 (field-feedback A1): persist a standalone, downloadable JSON report (the
    # restore-merge report ALSO already lives inside merge_batches.report_json, but
    # that column is not directly downloadable/human-readable, and does not ride an
    # export unless separately wired -- see src/backup/import_reports.py). Best-effort.
    #
    # The FINAL, COMPLETE timings (every stage through work_induced_tally) are
    # attached HERE -- distinct from the earlier, necessarily-partial snapshot
    # written into merge_batches.report_json mid-function (before the swap
    # even happened). This is the honest evidence base A4's own step 4
    # (optimise the measured biggest stage) needs.
    # Best-effort, same convention as every other post-commit step above (never undo
    # or abort a committed, additive restore) -- a skeptic-pass finding (2026-07-24):
    # this call is UNGUARDED history predating this stage-timing rework, and this
    # rework moved it BEFORE persist_import_report() below (it used to run last).
    # Without a try/except here, a prune failure would propagate past this point and
    # skip persist_import_report() entirely, silently regressing the S3.5 downloadable
    # report feature in exactly the case it is meant to survive.
    with timings.stage("prune_snapshots"):
        try:
            report["pruned_snapshots"] = _prune_snapshots()
        except Exception:  # noqa: BLE001 - never undo a committed, additive restore
            _LOG.warning("post-restore snapshot pruning failed", exc_info=True)
    report["timings"] = timings.report()  # include prune_snapshots' own duration too

    try:
        from src.backup.import_reports import persist_import_report

        report["persisted_report_path"] = str(
            persist_import_report("restore", report, run_id=str(batch_id))
        )
    except Exception:  # noqa: BLE001 - never undo a committed, additive restore
        _LOG.warning("persisting the standalone import report failed", exc_info=True)

    _LOG.info("merge-restore committed: batch=%s plan=%s", batch_id, counts)
    return report
