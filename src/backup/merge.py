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
import math
import os
import re
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.backup.artifact import StagedArtifact
from src.paths import data_dir

_LOG = logging.getLogger("backup.merge")

#: Oldest restorable schema (D7): the 0.0.8 baseline. Older artifacts carry no
#: alembic revision at all and are refused BY NAME of what they lack.
FLOOR_NOTE = "0.0.8 baseline (6ae5766d3136)"

_SAMPLE_LIMIT = 5
_SNAPSHOT_KEEP = 3
# 2026-07-26 hardware diagnostics W5: _prune_snapshots() (below) only fires as a
# side effect of a LATER restore -- a "keep 3" policy correctly retains all 3
# forever once no further restore ever happens, which is exactly the diagnosed
# 97.8 GB (three restores, then none for 36 hours, on one field instance). This
# is the time-driven backstop: 7 days is a judgment call (a safety-net snapshot's
# value decays with OPERATOR REVIEW TIME, not process lifetime -- unlike the
# .bak-build-*/.restore-* crash residue sweep_stale_backup_temps() ages out at
# 24h), operator-tunable via OO_PRE_RESTORE_SNAPSHOT_MAX_AGE_HOURS.
_SNAPSHOT_MAX_AGE_HOURS_DEFAULT = 168.0


class MergeError(RuntimeError):
    """Raised when a merge cannot proceed safely. The live DB is untouched."""


class RestoreAborted(RuntimeError):
    """The operator stopped this restore BEFORE the swap; nothing was applied.

    Distinct from :class:`MergeError` on purpose: a MergeError is the engine
    REFUSING an unsafe artifact (a failure the user must read), while this is
    the user's own Stop being honoured (a normal outcome the UI reports as
    "cancelled", never as an error).

    Field ruling 2026-07-29 item 15 -- "stop/abort is IMMEDIATE, losing the
    current import and everything related to it" -- is honest ONLY on the
    pre-swap side, and that is exactly where this is raised. Everything before
    ``swap`` runs on a disposable ``.restore-<hex>`` staging directory and a
    ``working.db`` copy, so abandoning it costs nothing and leaves the live
    corpus byte-identical. After ``os.replace`` there is no undo -- building
    one would be unsound (see the ruling's own analysis) -- so the swap is
    UNINTERRUPTIBLE by design and a Stop arriving later stops only the
    remaining post-swap work. The UI must say which of the two happened rather
    than implying an undo that does not exist."""


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
    # Rows the incoming corpus carried that this merge DELIBERATELY did not copy,
    # with the reason. Distinct from every other field here: new/duplicate/conflict
    # describe what the merge DID, `deferred` describes what it chose not to do and
    # who does it instead. Emitted only when set, so every existing report shape is
    # byte-unchanged (the same additive convention as `samples`/`conflicts`).
    deferred: int = 0
    note: str = ""
    samples: list[str] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        d: dict = {"new": self.new, "duplicate": self.duplicate, "conflict": self.conflict}
        if self.deferred:
            d["deferred"] = self.deferred
        if self.note:
            d["note"] = self.note
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
    cache_mb: int | None = None, should_stop: Callable[[], bool] | None = None,
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
    never break a merge).

    ``should_stop`` (field ruling 2026-07-29 item 15): checked BETWEEN the 14
    table-merge steps. The whole merge runs inside ONE ``BEGIN IMMEDIATE`` on
    the DISPOSABLE working copy, so aborting mid-sequence rolls that
    transaction back and throws the copy away -- the live corpus is untouched
    either way. Checked between steps rather than inside them because a single
    step is one bulk SQL statement set; the granularity is honest (a Stop takes
    effect at the next step boundary, not instantly mid-statement) and is the
    difference between a Stop that works during the LONGEST phase of an import
    and one that only appears to."""
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
            if should_stop is not None and should_stop():
                # The `except` below rolls this BEGIN IMMEDIATE back; the working
                # copy is disposable and the live corpus was never opened.
                raise RestoreAborted(
                    f"stopped during the merge (before the '{name}' step) — "
                    "nothing was written to your corpus"
                )
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
    # Bit-level duplicate test: same hash AND same content bytes = duplicate; same hash,
    # different bytes = a collision or normalisation drift, i.e. a conflict (local kept,
    # surfaced with both ids).
    #
    # ONE PASS for both tallies (import-speed fix 2026-07-30). These were two separate
    # COUNT queries over the SAME hash join, and the predicate is the article CONTENT --
    # so on an encrypted corpus each one dragged every hash-matching pair's full article
    # text through the SQLCipher codec, and the pair was read TWICE. Duplicate rates on
    # re-imported backups are high by nature (that is what makes the restore additive),
    # so this is most of the incoming corpus, twice. Conditional aggregation reads each
    # pair once and is arithmetically identical, NULL content included: a NULL comparison
    # is neither TRUE nor FALSE, so it counted in neither COUNT before and takes the ELSE
    # in both CASEs now.
    row = _q(
        con,
        "SELECT COALESCE(SUM(CASE WHEN m.content = i.content THEN 1 ELSE 0 END), 0),"
        "       COALESCE(SUM(CASE WHEN m.content <> i.content THEN 1 ELSE 0 END), 0)"
        " FROM inc.articles i JOIN articles m ON m.hash = i.hash",
    )[0]
    r.duplicate, r.conflict = int(row[0]), int(row[1])
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
    """DELIBERATELY DOES NOT COPY the incoming mentions (maintainer ruling 2026-07-29,
    option (a)) -- the post-swap re-index PRODUCES them from the article text instead.

    Ruling 2 asked that articles not yet re-indexed stay out of analytics. Its premise
    was refuted: this step used to copy the incoming corpus's mentions straight in, so a
    merged article was ALREADY fully in analytics before any re-index -- the re-index was
    a refresh, not an admission gate. The chosen fix is structural rather than a flag:
    with the derived rows never copied, "not yet re-indexed" simply MEANS "has no
    mentions", which every analytics path already honours by construction (no gate, no
    per-article flag, no join added to the fifteen mention-aggregating paths, and none of
    the documented SQLCipher codec trap that join would have walked into).

    Three things fall out of it, all wanted:
      * the merge stops writing the largest table in the artifact (~10M rows for a
        50k-article backup), which is the single biggest write in a large import;
      * the re-index stops delete-then-reinserting rows it was about to replace anyway;
      * the keyword-counter drift is fixed BY CONSTRUCTION -- counters could never absorb
        a merged corpus (the INSERT omitted the counter columns under a NOT EXISTS that
        never updated), and the re-index then read `old_contrib` from the live rows, which
        after a merge WERE the imported rows, so it subtracted a contribution never added.

    THE COST, stated honestly and guarded: an imported article now has NO keywords rather
    than STALE keywords until the re-index reaches it. That trades a bounded staleness for
    an UNBOUNDED invisibility if the re-index can be lost, which is why the batch carries a
    durable re-index state (see ``mark_reindex_complete`` / ``pending_reindex_batches``) and
    the backlog is surfaced rather than forgotten.

    The count of what was NOT copied is reported, so the deferral is quantified in the
    restore report rather than merely asserted -- a domain silently reporting 0/0/0 would
    be indistinguishable from an empty artifact.
    """
    r = DomainResult()
    # One bare table count (no join): the previous three heavy join queries + the 10M-row
    # INSERT are exactly what this step no longer does, so paying for them to describe the
    # skip would defeat its purpose.
    r.deferred = _count(con, "SELECT COUNT(*) FROM inc.keyword_mentions")
    r.note = (
        "not copied by design: the post-swap re-index recomputes these from the article "
        "text with the CURRENT extraction engine (maintainer ruling 2026-07-29). Until it "
        "reaches an article, that article has no keywords and is absent from keyword "
        "analytics -- see the restore report's reindex section for the backlog."
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


_RUN_SNAPSHOT_LOCK = threading.Lock()
#: (exclusive-window token, snapshot path) — the pre-restore safety net already taken
#: for the CURRENT import run. Process-local by design: it is an optimisation about
#: work already done in THIS process, and a restart legitimately re-takes one.
_RUN_SNAPSHOT: tuple[int, Path] | None = None


def _run_scoped_snapshot() -> Path | None:
    """The pre-restore safety net already taken for this import run, if any.

    ONE SAFETY NET PER RUN, not one per item (import-speed fix 2026-07-30). Each item
    of a queue used to write a full copy of the whole live corpus as its safety net --
    on a 130 GB corpus a 16-item run meant ~2 TB written and ~390 GB of disk held at a
    time. It was also NOT giving what it appeared to: ``_SNAPSHOT_KEEP`` is 3, so the
    run's earliest (and only genuinely useful) snapshot was pruned away by item 4 --
    a defect this project's own ledger already records. The run-start copy is what an
    operator would actually want to return to ("undo this import"), and keeping exactly
    that one is both cheaper AND more useful than keeping the last three mid-run states.

    Scoped by :func:`~src.scheduler.runner.exclusive_window_token`, so:
      * a lone restore (no window; token 0) ALWAYS takes its own — unchanged behaviour;
      * every item of one queue run shares the first item's;
      * a LATER run gets a new token and therefore a new snapshot.

    Re-verifies the file still exists before reusing it: a snapshot someone deleted must
    be re-taken, never silently reported as still standing."""
    from src.scheduler.runner import exclusive_window_token

    token = exclusive_window_token()
    if not token:
        return None
    with _RUN_SNAPSHOT_LOCK:
        prior = _RUN_SNAPSHOT
    if prior is None or prior[0] != token:
        return None
    return prior[1] if prior[1].exists() else None


def _remember_run_snapshot(path: Path) -> None:
    """Record a freshly-written safety net as THIS run's, so later items reuse it."""
    from src.scheduler.runner import exclusive_window_token

    token = exclusive_window_token()
    if not token:
        return
    global _RUN_SNAPSHOT
    with _RUN_SNAPSHOT_LOCK:
        _RUN_SNAPSHOT = (token, path)


def _verify_fts(con, has_fts: bool, articles: int) -> dict:
    """Check that the FTS index covers every article, rebuilding ONLY if it does not.

    THE P0.4 FIX, APPLIED TO THE RESTORE PATH. ``verify_copy`` used to run an
    unconditional ``INSERT INTO article_fts(article_fts) VALUES('rebuild')`` here --
    the exact corpus-scaled operation ``ensure_fts`` was fixed to stop doing on every
    boot (``src/database/fts.py``, which records the measured cost on the field's own
    130 GB corpus: 981-1645 s PER RUN). On the boot path that cost recurred once per
    unlock; here it recurs once per IMPORTED BACKUP, so a 16-backup queue paid it
    sixteen times over a corpus that grows with every item -- hours of single-threaded
    codec work, on the largest and most repetitive import a user will ever run.

    It was also redundant AND the check it fed was tautological:
      * REDUNDANT -- ``_merge_articles`` inserts through ``INSERT INTO articles ...
        SELECT``, and the ``article_fts_ai`` trigger fires on those rows exactly as it
        does on ordinary ingest, so the merged articles are already indexed when this
        runs. (The working copy is a snapshot of the live corpus, so it carries the
        FTS table AND its triggers.)
      * TAUTOLOGICAL -- ``COUNT(*) FROM article_fts`` on an EXTERNAL-CONTENT FTS5 table
        reads the CONTENT table (``articles``), never the index (fts.py's own
        "external-content gotcha"), so the old ``fts_rows == articles`` compared
        ``COUNT(*) FROM articles`` against itself. It could not fail, which is why the
        rebuild's removal costs no real coverage: there was none to lose.

    The population probe that DOES mean something is the ``article_fts_docsize`` shadow
    table (one row per indexed document). Comparing it to the article count is a REAL
    check -- it detects a partial or empty index, which the old one could not -- and it
    is what decides the rebuild, so a genuinely incomplete index is still repaired here
    (the restore keeps its "the swapped-in corpus has a complete index" property; it
    just stops paying for it when it already holds).

    A build without the docsize shadow (``columnsize=0``) cannot be probed cheaply:
    fts.py's own precedent applies -- trust the triggers and SKIP rather than risk a
    corpus-scaled rebuild on a false negative -- and the unprovable state is reported
    rather than asserted as a pass."""
    if not has_fts:
        return {"fts_matches_articles": True}
    try:
        indexed = _count(con, "SELECT COUNT(*) FROM article_fts_docsize")
    except Exception:  # noqa: BLE001 - a columnsize=0 build has no docsize shadow
        return {
            "fts_matches_articles": True,
            "fts_indexed": None,
            "fts_rebuilt": False,
            "fts_note": "index population not probeable on this FTS5 build; "
            "the sync triggers are trusted (never rebuilt on a false negative)",
        }
    rebuilt = False
    if indexed != articles:
        con.execute("INSERT INTO article_fts(article_fts) VALUES('rebuild')")
        con.commit()
        indexed = _count(con, "SELECT COUNT(*) FROM article_fts_docsize")
        rebuilt = True
    return {
        "fts_indexed": indexed,
        "fts_rebuilt": rebuilt,
        "fts_matches_articles": indexed == articles,
    }


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
        v["articles"] = _count(con, "SELECT COUNT(*) FROM articles")
        v.update(_verify_fts(con, has_fts, v["articles"]))

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
    from src.backup.stream_backup import is_active_staging

    snaps = sorted(data_dir().glob("pre-restore-*.db"), key=lambda p: p.name, reverse=True)
    removed = []
    for p in snaps[keep:]:
        if is_active_staging(p):
            # Skeptic fix (2026-07-27, race-concurrency lens): NEVER delete
            # another IN-FLIGHT restore's own snapshot. LIVE-REPRODUCED: this
            # function runs unconditionally on EVERY commit (not just the
            # committer's own), so a THIRD (or fourth...) concurrently
            # committing restore's own call could previously delete an
            # EARLIER restore's still-active snapshot the moment enough newer
            # snapshots pushed it past ``keep`` -- there is no lock preventing
            # two REST restore-commit requests from running truly
            # concurrently. It simply survives an extra round past ``keep``
            # here; it becomes fair game again the instant its own restore
            # releases the guard.
            continue
        try:
            p.unlink()
            removed.append(p.name)
        except OSError:  # pragma: no cover
            pass
    return removed


def _snapshot_max_age_hours() -> float:
    """``OO_PRE_RESTORE_SNAPSHOT_MAX_AGE_HOURS`` -- the same env-var idiom as
    ``_incremental_vacuum_hours()``/``_maint_interval_s()`` elsewhere in this
    codebase: ``float(os.getenv(NAME, default))``, degrading to the default on
    an unparseable value rather than raising into a background safety net."""
    try:
        return float(
            os.getenv(
                "OO_PRE_RESTORE_SNAPSHOT_MAX_AGE_HOURS", str(_SNAPSHOT_MAX_AGE_HOURS_DEFAULT)
            )
        )
    except ValueError:
        return _SNAPSHOT_MAX_AGE_HOURS_DEFAULT


_SNAPSHOT_TS_RE = re.compile(r"^pre-restore-(\d{8}T\d{6}Z)\.db$")


def prune_pre_restore_snapshots_by_age(max_age_hours: float | None = None) -> list[str]:
    """Remove ``pre-restore-<ts>.db`` safety-net snapshots older than
    ``max_age_hours``.

    Complements :func:`_prune_snapshots`'s count-based policy, which only fires
    as a side effect of a LATER restore -- this is the time-driven backstop for
    the case where no further restore ever happens (the diagnosed 97.8 GB: three
    restores in a burst, then none, so ``keep 3`` correctly retained all three
    forever). Age is read from the file's OWN embedded timestamp, never
    filesystem mtime (mtime can be touched by an unrelated copy/backup tool). A
    snapshot currently registered via :func:`src.backup.stream_backup.
    is_active_staging` -- an in-flight restore's own, still-running commit tail
    -- is NEVER touched regardless of its age; the count-based policy above is
    unconditional and untouched by this function. Only files matching the exact
    self-generated ``pre-restore-<ISO8601Z>.db`` shape are ever considered --
    an unrecognized name is never guessed at, never touched."""
    from src.backup.stream_backup import is_active_staging

    hours = max_age_hours if max_age_hours is not None else _snapshot_max_age_hours()
    try:
        if math.isnan(hours):
            # NaN must be routed to the SAME "fall back to the documented
            # default" path as inf/1e300 below -- NOT silently absorbed by
            # the negative-value clamp. max(0.0, nan) evaluates to 0.0 (a
            # genuinely surprising CPython quirk: max() keeps its FIRST
            # argument as the running "best" and only replaces it when the
            # NEXT one compares strictly greater, and nan > 0.0 is False) --
            # so without this explicit check, a nan input would silently
            # sweep EVERYTHING (as if max_age_hours=0) instead of degrading
            # to the safe 168h default like every other non-finite value.
            raise ValueError("hours is NaN")
        # Skeptic fix (2026-07-27, config-abuse lens): a NEGATIVE ``hours``
        # (e.g. an explicit caller, or a future Settings knob with no lower
        # bound -- the env-var path's own float() parse never rejects "-5")
        # would otherwise produce a cutoff in the FUTURE, over-sweeping
        # EVERYTHING regardless of age. Clamp to "sweep everything created
        # before this instant" at worst -- never "sweep something created
        # after this instant."
        cutoff = datetime.now(UTC) - timedelta(hours=max(0.0, hours))
    except (OverflowError, ValueError):
        # A non-finite (inf/-inf/nan) or absurdly large ``hours`` value --
        # whether passed explicitly or read from a malformed/fat-fingered env
        # var -- can slip PAST _snapshot_max_age_hours()'s float() parse
        # (float("inf")/float("nan")/float("1e300") all parse cleanly, so its
        # bare ``except ValueError`` never fires for these) and then raise
        # HERE instead, one level down, while constructing/subtracting the
        # timedelta. Falling back to the documented default rather than
        # letting this raise keeps the sweep from crashing on EVERY future
        # call -- a misconfigured env var must never permanently and
        # silently disable the very safety net it exists to provide.
        cutoff = datetime.now(UTC) - timedelta(hours=_SNAPSHOT_MAX_AGE_HOURS_DEFAULT)
    removed: list[str] = []
    for p in data_dir().glob("pre-restore-*.db"):
        m = _SNAPSHOT_TS_RE.match(p.name)
        if not m:
            continue  # unrecognized shape -- never guess, never touch
        try:
            created = datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        except ValueError:
            continue
        if created >= cutoff:
            continue
        if is_active_staging(p):
            continue  # an in-flight restore's own snapshot -- never touched
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


# --------------------------------------------------------------------------- #
#  Durable re-index state (the guard the 2026-07-29 option-(a) ruling requires)
# --------------------------------------------------------------------------- #
# Since the merge no longer copies the incoming keyword_mentions, an imported article
# carries NO keywords until the re-index reaches it. That is only safe if the work can
# never be silently lost, so it is tracked in TWO places with different jobs:
#
#   * merge_batches.status -- DURABLE, in the corpus itself, survives anything the
#     corpus survives. 'merged' means the rows landed but the re-index is not confirmed
#     finished; 'reindexed' means it is. This is the source of truth for "is there a
#     backlog", and it is what makes the work impossible to forget.
#   * a small marker file -- the WATERMARK, for resuming mid-batch without redoing work.
#     Its loss costs time, never correctness: the re-index is idempotent (it
#     delete-then-reinserts), so a lost watermark just redoes a batch already known to be
#     pending from the DB. It is deliberately NOT the source of truth.
#
# The asymmetry is the point: the cheap, losable thing is the optimisation, and the
# durable thing is the guarantee.
_REINDEX_STATE_FILE = "reindex_backlog.json"

_STATUS_MERGED = "merged"
_STATUS_REINDEXED = "reindexed"


def _reindex_state_path() -> Path:
    return data_dir() / _REINDEX_STATE_FILE


def _save_reindex_cursor(batch_id: int, *, last_id: int, done: int, total: int) -> None:
    """Best-effort watermark write. Never raises: a resilience sidecar that can itself
    break the operation it exists to protect is worse than no sidecar (the project's
    recorded crash-journal lesson)."""
    try:
        path = _reindex_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {"batch_id": batch_id, "last_id": last_id, "done": done, "total": total},
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        os.replace(tmp, path)  # atomic: a torn read can never yield a bogus watermark
    except Exception:  # noqa: BLE001 - the watermark is an optimisation, never a guarantee
        _LOG.debug("could not persist the re-index watermark", exc_info=True)


def _load_reindex_cursor(batch_id: int) -> int | None:
    """The last completed article id for THIS batch, or None. A cursor belonging to a
    different batch is ignored rather than trusted -- resuming batch B from batch A's
    watermark would skip real work and leave articles permanently keyword-less."""
    try:
        raw = json.loads(_reindex_state_path().read_text(encoding="utf-8"))
        if int(raw.get("batch_id", -1)) != int(batch_id):
            return None
        last = raw.get("last_id")
        return int(last) if last is not None else None
    except Exception:  # noqa: BLE001 - absent/torn/foreign cursor => start from the top
        return None


def clear_reindex_cursor() -> None:
    try:
        _reindex_state_path().unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        _LOG.debug("could not clear the re-index watermark", exc_info=True)


def mark_reindex_complete(batch_id: int) -> None:
    """Record that ``batch_id``'s imported articles are fully re-indexed.

    Called ONLY when the re-index actually finished the batch. A partially-completed
    re-index deliberately leaves the batch 'merged', so the backlog survives a crash,
    a cancel, or a power loss -- that is the whole guarantee.
    """
    from sqlalchemy import text

    from src.database.session import session_scope

    try:
        with session_scope() as session:
            session.execute(
                text("UPDATE merge_batches SET status = :s WHERE id = :b"),
                {"s": _STATUS_REINDEXED, "b": int(batch_id)},
            )
        clear_reindex_cursor()
    except Exception:  # noqa: BLE001 - never undo a committed, additive restore
        _LOG.warning("could not stamp batch %s as re-indexed", batch_id, exc_info=True)


def pending_reindex_batches() -> list[dict]:
    """Imports whose articles are merged but not confirmed re-indexed.

    Each entry carries the real article count from ``merged_rows``, so the number shown
    is measured, never estimated.

    Returns [] BOTH when there is genuinely nothing pending and when the read failed --
    which is why callers should use :func:`reindex_backlog` instead, whose payload keeps
    those two apart. (An earlier docstring here claimed callers "report the degrade
    rather than the emptiness"; they could not, because this shape gives them nothing to
    tell the two apart with. That is the project's own degrade-sentinel lesson, and the
    wrapper below is the fix.)
    """
    from sqlalchemy import text

    from src.database.session import session_scope

    try:
        with session_scope() as session:
            rows = session.execute(
                text(
                    "SELECT b.id, b.created_at, COUNT(m.row_id) AS n"
                    " FROM merge_batches b"
                    " LEFT JOIN merged_rows m"
                    "   ON m.batch_id = b.id AND m.table_name = 'articles'"
                    " WHERE b.status = :s"
                    " GROUP BY b.id, b.created_at"
                    " HAVING COUNT(m.row_id) > 0"
                    " ORDER BY b.id"
                ),
                {"s": _STATUS_MERGED},
            ).fetchall()
        return [{"batch_id": int(r[0]), "created_at": r[1], "articles": int(r[2])} for r in rows]
    except Exception:  # noqa: BLE001
        _LOG.warning("could not read the re-index backlog", exc_info=True)
        return []


def reindex_backlog() -> dict:
    """The re-index backlog, with "measured nothing" kept distinct from "could not read".

    THE MANDATORY GUARD that travels with the option-(a) ruling (2026-07-29): the merge
    no longer copies the incoming corpus's derived rows, so "not yet re-indexed" means
    "has no keywords" -- which every analytics path honours structurally, at the price of
    trading a BOUNDED staleness for an UNBOUNDED invisibility if the re-index is ever
    lost. The durable cursor is what makes it resumable; THIS is what makes it visible,
    so a backlog can never sit unseen.

    ``available: false`` means the backlog could not be read (a locked or missing store),
    NOT that it is empty -- reporting the two the same way would be the exact
    fabricated-reassurance this guard exists to prevent."""
    from sqlalchemy import text

    from src.database.session import session_scope

    try:
        with session_scope() as session:
            rows = session.execute(
                text(
                    "SELECT b.id, b.created_at, COUNT(m.row_id) AS n"
                    " FROM merge_batches b"
                    " LEFT JOIN merged_rows m"
                    "   ON m.batch_id = b.id AND m.table_name = 'articles'"
                    " WHERE b.status = :s"
                    " GROUP BY b.id, b.created_at"
                    " HAVING COUNT(m.row_id) > 0"
                    " ORDER BY b.id"
                ),
                {"s": _STATUS_MERGED},
            ).fetchall()
    except Exception as exc:  # noqa: BLE001 - a diagnostic must degrade, never 500
        _LOG.warning("could not read the re-index backlog", exc_info=True)
        return {"available": False, "reason": str(exc)}
    batches = [
        {"batch_id": int(r[0]), "created_at": str(r[1]) if r[1] is not None else None,
         "articles": int(r[2])}
        for r in rows
    ]
    return {
        "available": True,
        "batches": batches,
        "batches_pending": len(batches),
        "articles_pending": sum(b["articles"] for b in batches),
        "method": (
            "imports whose articles were merged but whose re-index has not been "
            "confirmed complete; counts read from merged_rows, never estimated"
        ),
    }


def reindex_imported_articles(
    batch_id: int,
    *,
    commit_batch: int | None = None,
    workers: int | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
    stats: dict | None = None,
    should_stop: Callable[[], bool] | None = None,
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
        all_ids = sorted(int(r[0]) for r in rows)
        if not all_ids:
            mark_reindex_complete(batch_id)
            return {"reindexed": 0, "failed": 0}

        # RESUME. Ascending order + a last-completed watermark is an exact cursor: every
        # id at or below it is already re-indexed. A missing/foreign watermark simply
        # starts from the top -- correct, only slower (the re-index is idempotent).
        resume_after = _load_reindex_cursor(batch_id)
        ids = [i for i in all_ids if i > resume_after] if resume_after is not None else all_ids
        already = len(all_ids) - len(ids)
        if not ids:
            mark_reindex_complete(batch_id)
            out: dict = {"reindexed": 0, "failed": 0}
            if already:
                out["resumed_already_done"] = already
            return out

        total = len(ids)

        def _tracked(done: int, _total: int) -> None:
            # Persist the watermark as the re-index advances, so a crash resumes here
            # rather than redoing the batch. `done` counts FINALISED articles in list
            # order, so ids[done-1] is the last one that completed.
            if 0 < done <= total:
                _save_reindex_cursor(
                    batch_id, last_id=ids[done - 1], done=already + done, total=len(all_ids)
                )
            if progress_cb is not None:
                progress_cb(already + done, len(all_ids))

        result = reindex_articles(
            session,
            extractor=get_extractor("baseline"),
            article_ids=ids,
            commit_batch=commit_batch,
            workers=workers,
            progress_cb=_tracked,
            stats=stats,
            should_stop=should_stop,
        )
        # Only a batch that reached the end is stamped done. Anything short of that
        # deliberately stays 'merged', so the backlog survives the interruption -- the
        # whole point of not merging the derived rows in the first place.
        if int(result.get("reindexed", 0)) + int(result.get("failed", 0)) >= total:
            mark_reindex_complete(batch_id)
        if already:
            result["resumed_already_done"] = already
        return result


def _available_ram_mb() -> int | None:
    """Currently AVAILABLE RAM in MiB, from ``/proc/meminfo``'s ``MemAvailable``.

    ``MemAvailable`` rather than ``MemFree`` or ``MemTotal``: the kernel's own
    estimate of what a new allocation can actually get without swapping, which
    already accounts for reclaimable page cache and slab. That is the honest
    denominator for "how much may this import claim" -- MemTotal would ignore
    everything else on the box, and MemFree would under-read a machine whose RAM
    is mostly healthy page cache.

    ``/proc/meminfo`` rather than ``psutil`` for the same reason
    ``vllm_lifecycle._total_ram_bytes`` does: psutil is an optional extra
    ([analysis]) and a core install must not silently lose the measurement.

    ``None`` when unreadable (non-Linux, restricted /proc) -- an honest unknown,
    never a fabricated number, and the caller falls back to the fixed default."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    # "MemAvailable:   10261176 kB"
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


#: Share of AVAILABLE RAM an owning import may claim for the merge page cache.
#: A quarter, deliberately: the same import concurrently runs a process pool of
#: up to :data:`reindex_parallel._MAX_EXCLUSIVE_WORKERS_CAP` extraction workers,
#: each holding an article body and an extractor, and the page cache is the one
#: allocation that can be claimed in a single lump. Leaving three quarters is
#: what keeps the enlarged cache a throughput win rather than the thing that
#: pushes a 12 GB box into swap -- where it would be far slower than the small
#: cache it replaced.
_IMPORT_CACHE_RAM_SHARE = 0.25
_IMPORT_CACHE_FLOOR_MB = 512  # never below the fixed default this replaced
_IMPORT_CACHE_CEIL_MB = 4096  # past this, SQLite's cache stops being the bottleneck


def import_cache_mb() -> int:
    """Enlarged SQLite page-cache MiB for the import merge connection
    specifically (field-feedback Session A §4, "import owns the machine") --
    SEPARATE from the app's general ``OO_SQLITE_CACHE_MB``
    (``src/config/power_profiles.py``), which never reaches this connection
    (opened via the raw ``connect()`` factory, not the pooled app engine).

    SCALED TO AVAILABLE RAM (maintainer ask 2026-07-30, on a 12 GB box whose RAM
    sat at 30% through an import): a fixed 512 MiB is simultaneously too big for
    a 3 GB field machine and far too small for a 12 GB one. A quarter of
    MemAvailable, clamped to [512, 4096] MiB, adapts to both -- the floor keeps
    it never worse than the fixed default it replaced, and the ceiling stops a
    very large box from claiming a cache past the point where SQLite's page
    cache is what limits the merge.

    ``OO_IMPORT_CACHE_MB`` still overrides absolutely -- an operator's explicit
    number is never second-guessed, in either direction. A machine whose RAM
    cannot be read falls back to the fixed 512 MiB default, never to a guess.

    A resource-usage tuning knob only, never a behaviour change: the merge's
    results are byte-identical at any cache size."""
    raw = os.getenv("OO_IMPORT_CACHE_MB", "").strip()
    if raw:
        try:
            return max(2, int(raw))
        except ValueError:
            pass
    avail = _available_ram_mb()
    if not avail or avail <= 0:
        return _IMPORT_CACHE_FLOOR_MB
    scaled = int(avail * _IMPORT_CACHE_RAM_SHARE)
    return max(_IMPORT_CACHE_FLOOR_MB, min(_IMPORT_CACHE_CEIL_MB, scaled))


# The canonical stage sequence a restore walks, in order. Kept BESIDE the
# ``timings.stage(...)`` calls in run_restore that produce it -- a drift here shows
# up immediately as a wrong "phase N of M", and tests/test_restore_stage_plan.py
# pins the two lists against each other by reading this module's own source.
_RESTORE_STAGES_ALWAYS: tuple[str, ...] = (
    "prepare_staged",
    "snapshot_working_copy",
    "merge",
    "verify",
    "corpus_delta_before",
)
# Everything after the dry-run early return (``if not commit``) -- i.e. only a
# COMMITTING restore reaches these.
_RESTORE_STAGES_COMMIT: tuple[str, ...] = (
    "pre_restore_snapshot",
    "side_files_and_custody",
    "report_json_write",
    "swap",
    "corpus_delta_after",
    "corpus_epoch_bump",
    "event_mirror_refresh",
    "reindex",
    "keyword_counter_reconcile",
    "quarantine_scan",
    "work_induced_tally",
    "prune_snapshots",
)


def restore_stage_plan(*, commit: bool, reindex_imported: bool = True) -> tuple[str, ...]:
    """The stages THIS restore will actually walk, in order.

    Exists so a caller can show an honest "phase N of M" (field ruling 2026-07-29
    item 17: the number of remaining phases must be visible). M is NOT a constant --
    a dry run stops after ``corpus_delta_before`` and a restore with
    ``reindex_imported=False`` never runs the ``reindex`` stage -- so a hardcoded
    denominator would be a fabricated number, exactly the thing this project's
    honesty rules forbid. Pure + total, so it is trivially testable and can never
    itself fail a restore."""
    if not commit:
        return _RESTORE_STAGES_ALWAYS
    tail = tuple(s for s in _RESTORE_STAGES_COMMIT if s != "reindex" or reindex_imported)
    return _RESTORE_STAGES_ALWAYS + tail


def import_reindex_commit_batch() -> int:
    """Commit batch for the post-merge re-index when the import owns the machine
    (field report 2026-07-29: a 50,000-article import quoted a multi-hour re-index).

    WHY THIS EXISTS SEPARATELY from :func:`_default_reindex_commit_batch`: that one
    reads ``OO_REINDEX_COMMIT_BATCH``, whose default is ``1`` -- ONE COMMIT, hence one
    fsync through the SQLCipher codec, PER ARTICLE. That default is the right
    conservative choice for the BACKGROUND corpus re-index, which must interleave with
    a live scrape and therefore must not hold the single-writer gate across a long
    batch. A restore's re-index is the opposite situation: background collection is
    paused for its duration, so nothing is waiting on the gate and a wide batch is
    pure win (fewer fsyncs, fewer gate acquisitions).

    ``OO_IMPORT_REINDEX_COMMIT_BATCH`` overrides; default 200 (maintainer-ruled
    2026-07-29). NO DATA LOSS at any batch width: ``reindex_articles``' batched path
    keeps the proven rollback-then-redo-per-article fallback, so a collision or a bad
    article never drops its batch-mates -- the batch size trades fsyncs for the SIZE
    of the redo on failure, never for correctness.

    Used ONLY when the caller confirmed exclusivity (``was_paused``); otherwise the
    caller passes None and the conservative env default applies."""
    raw = os.getenv("OO_IMPORT_REINDEX_COMMIT_BATCH", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return 200


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
    should_stop: Callable[[], bool] | None = None,
    exclusive: bool = False,
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
    ``reindex_progress_cb``). Report-only, never load-bearing.

    The contract stays ONE argument on purpose. An earlier cut of the 2026-07-29
    "phase N of M" work widened it to ``(name, index, total)``, which is a SILENT
    breaking change: ``StageTimings`` wraps ``on_start`` in its own try/except, so
    a caller still passing a 1-argument callable stopped receiving pings entirely,
    with no error anywhere. A caller that wants the position derives it from
    :func:`restore_stage_plan` — which is public, pure and drift-guarded for
    exactly that purpose.

    ``should_stop`` (field ruling 2026-07-29 item 15, "stop/abort is IMMEDIATE,
    losing the current import"): polled at every PRE-SWAP stage boundary and
    between the 14 merge steps. Every one of those stages works on the
    disposable ``.restore-<hex>`` staging dir and the ``working.db`` copy, so
    aborting there raises :class:`RestoreAborted` with the live corpus
    byte-identical -- a genuinely free, genuinely complete abort.

    The LAST poll is immediately before ``swap``. From ``os.replace`` onward
    there is deliberately NO abort hook: the swap is atomic and there is no
    sound undo for it (a ``merged_rows`` delete leaves dangling ids, hash-joined
    rows legitimately attach to PRE-EXISTING articles, and nothing repairs the
    counters afterward), so offering one would be fabricated capability. The
    post-swap tail (re-index, counters, tallies) is resumable work that a Stop
    simply leaves for later, which the caller reports as such rather than as an
    undo.

    ``exclusive`` (import-speed fix 2026-07-30): the caller asserts that this restore
    OWNS the machine -- background collection is paused and nothing else is expected to
    write the live corpus. It is passed to the two whole-corpus snapshots below as
    ``allow_file_copy``, which lets them copy the corpus's bytes instead of
    re-encrypting it row by row through the SQLCipher codec. Purely a resource decision
    with no behavioural difference: the fast path itself refuses unless it can PROVE the
    copy is complete (see :func:`~src.database.connect._quiesced_file_copy`), so passing
    it wrongly costs correctness nothing. Default False keeps every existing caller
    byte-for-byte on the old path."""
    from src.backup.sqlite_backup import live_db_path
    from src.backup.timing import StageTimings
    from src.database.session import dispose_engine, init_db
    from src.scheduler.runner import owns_the_machine

    timings = StageTimings(on_start=stage_progress_cb)

    # OWNERSHIP-DERIVED DEFAULTS (field report 2026-07-30). Two callers -- the legacy
    # single-archive restore and the /v2/restore commit -- pass none of the throughput
    # knobs and never pause anything, so their re-index ran at ONE COMMIT PER ARTICLE
    # even when nothing else was touching the machine. Derived here rather than at each
    # call site so there is one answer to "does this restore own the machine", and so a
    # future caller cannot forget. An explicit argument always wins: a caller that says
    # what it wants is never second-guessed.
    _owned = exclusive or owns_the_machine()
    if _owned:
        if reindex_commit_batch is None:
            reindex_commit_batch = import_reindex_commit_batch()
        if reindex_workers is None:
            from src.analytics.reindex_parallel import all_cores_worker_count

            reindex_workers = all_cores_worker_count()
        if merge_cache_mb is None:
            merge_cache_mb = import_cache_mb()
    exclusive = exclusive or _owned

    def _abort_point(before: str) -> None:
        """Honour a Stop at a PRE-SWAP boundary (ruling item 15). Never called
        after the swap -- see this function's docstring for why that is a design
        decision rather than an omission."""
        if should_stop is not None and should_stop():
            raise RestoreAborted(
                f"stopped before '{before}' — nothing was written to your corpus"
            )

    # Fold in stage-A (decrypt/reassemble) timing, already measured by whichever
    # producer (read_artifact / read_stream_backup / read_volume_backup) built
    # this StagedArtifact — run_restore itself never touches stage A (it only
    # ever receives an already-staged artifact), so this is the one place all
    # 7 lettered stages (A-G) converge into ONE report.
    for _name, _seconds in (staged.stage_a_timings or {}).items():
        timings.record(f"stage_a:{_name}", _seconds)

    _abort_point("prepare_staged")
    with timings.stage("prepare_staged"):
        original_rev = prepare_staged_corpus(staged, allow_unverified=allow_unverified)

    working = staged.staging_dir / "working.db"
    if working.exists():
        working.unlink()
    # The working copy PRESERVES the live at-rest state: merging on an
    # encrypted corpus must never yield a plaintext live file at the swap.
    from src.database.connect import snapshot_preserving

    _abort_point("snapshot_working_copy")
    with timings.stage("snapshot_working_copy"):
        snapshot_preserving(live_db_path(), working, allow_file_copy=exclusive)

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

    _abort_point("merge")
    with timings.stage("merge"):
        _step_clock["t"] = time.monotonic()
        counts, batch_id = merge_corpus(
            staged.corpus_path, working, meta,
            progress_cb=_timed_progress_cb, cache_mb=merge_cache_mb,
            should_stop=should_stop,
        )
    _abort_point("verify")
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
    _abort_point("corpus_delta_before")
    with timings.stage("corpus_delta_before"):
        try:
            from src.database.session import session_scope

            with session_scope() as _before_sess:
                report["corpus_delta"] = {"before": _corpus_snapshot(_before_sess)}
        except Exception:  # noqa: BLE001 - a snapshot failure must never block a commit
            _LOG.warning("pre-restore corpus snapshot failed", exc_info=True)

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    snapshot = data_dir() / f"pre-restore-{ts}.db"
    # W5 (2026-07-26 hardware diagnostics) + skeptic fix (2026-07-27): register
    # this snapshot as an ACTIVE staging path BEFORE writing it starts, not
    # after -- a data-loss-lens LIVE repro (real snapshot_preserving() against
    # a real multi-hundred-MB corpus) proved the destination file is
    # glob-visible-but-incomplete for the ENTIRE write duration, and the
    # ~110us gap between the old (post-write) registration and the write
    # returning was enough for a concurrent off-peak sweep
    # (prune_pre_restore_snapshots_by_age -- the ordinary REST commit path
    # does NOT pause the scheduler for it, unlike the separate volume-restore
    # job path) to see the file as unregistered-and-old-enough and unlink()
    # it mid-write or the instant the write finished. The WHOLE commit tail
    # below is now wrapped in try/finally so the guard releases on EVERY exit
    # path -- a race-lens LIVE repro proved several of these stages
    # (side_files_and_custody / report_json_write / swap) have no try/except
    # of their own by design, and an uncaught exception there used to leak the
    # registration for the rest of the process's life (the guard was
    # previously closed only inside prune_snapshots' own finally, unreachable
    # from an earlier raise).
    from contextlib import ExitStack

    from src.backup.stream_backup import active_staging

    _reuse = _run_scoped_snapshot()
    _snapshot_guard = ExitStack()
    # Registered whether it is being WRITTEN now or REUSED from an earlier item of this
    # run: the age-based sweep never touches a registered path, so the run's one safety
    # net is protected for every item's commit tail exactly as the writer's own is.
    # (The sweep's two callers -- boot and the scheduler's idle pass -- cannot fire
    # mid-run anyway, the latter because collection is paused for the window; this makes
    # the protection explicit rather than a consequence of that.)
    _snapshot_guard.enter_context(active_staging(_reuse if _reuse is not None else snapshot))
    try:
        _abort_point("pre_restore_snapshot")
        with timings.stage("pre_restore_snapshot"):
            if _reuse is None:
                snapshot_preserving(live_db_path(), snapshot, allow_file_copy=exclusive)
                _remember_run_snapshot(snapshot)
                report["pre_restore_snapshot"] = str(snapshot)
            else:
                report["pre_restore_snapshot"] = str(_reuse)
                report["pre_restore_snapshot_reused"] = (
                    "one safety net for the whole import run — this is the corpus as it "
                    "was BEFORE the run started, which is the state an operator would "
                    "actually want to return to"
                )

        _abort_point("side_files_and_custody")
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

        _abort_point("report_json_write")
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
        # THE LAST ABORT POINT. Past os.replace there is no undo, so no
        # further poll exists -- by design, not by omission.
        _abort_point("swap")
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
                    # A SIBLING report key, deliberately not a StageTimings entry:
                    # StageTimings is float-seconds-only and the frontend formats every
                    # one of its values as a duration, so a rate parked there would
                    # render as "1200.0 s" AND displace the real slowest stage in the
                    # "how long did this take?" table.
                    _rx_stats: dict = {}
                    report["reindex_rates"] = _rx_stats
                    report["reindexed"] = reindex_imported_articles(
                        batch_id,
                        commit_batch=reindex_commit_batch,
                        workers=reindex_workers,
                        progress_cb=reindex_progress_cb,
                        stats=_rx_stats,
                        # POST-SWAP stop (ruling item 15): the corpus is already
                        # committed and additive, so this is not an abort -- it
                        # leaves the batch marked 'merged' with its durable cursor
                        # intact, and the backlog resumes later exactly here.
                        should_stop=should_stop,
                    )
                    _rx_stats["commit_batch"] = reindex_commit_batch
                    # R3: the EFFECTIVE knobs, not the requested ones. The field
                    # report that produced this fix was "~2 articles/sec", noticed by
                    # watching a progress bar -- there was no way to see that the
                    # commit batch had silently reverted to 1 and the cache to its
                    # compiled-in default. Now the report says so.
                    _rx_stats["owned_the_machine"] = _owned
                    _rx_stats["workers"] = reindex_workers
                    _rx_stats["merge_cache_mb"] = merge_cache_mb
                except Exception:  # noqa: BLE001 - never undo a committed, additive restore
                    _LOG.warning("post-restore re-index of imported articles failed", exc_info=True)
                    # The whole batch failed before touching a single article, so NONE of the
                    # imported articles got re-indexed -- "failed" must be the true imported
                    # count (from the already-known plan), not 0. Reporting 0 here would read
                    # as "nothing needed re-indexing", which is the fabricated-signal the rest
                    # of this feature is built to avoid (see reindex_imported_articles above).
                    _imported = int((counts.get("articles") or {}).get("new") or 0)
                    report["reindexed"] = {"reindexed": 0, "failed": _imported, "skipped": "see server log"}

        # Keyword counters after a merge (bug found + reproduced 2026-07-29,
        # tests/test_restore_counter_drift.py). TWO independent halves left them wrong:
        #   (1) _merge_keywords' INSERT column list omits mention_count/article_count, so a
        #       merged keyword lands at the column default 0, and an ALREADY-PRESENT keyword
        #       is matched by WHERE NOT EXISTS and never updated -- while
        #       _merge_keyword_mentions copies the real mention rows straight in.
        #   (2) the re-index above then reads ``old_contrib`` from the LIVE mention rows --
        #       which after a merge ARE the imported rows -- so its ``new - old`` delta nets
        #       to ~0 and CEMENTS the drift instead of repairing it.
        # maybe_reconcile_counters would eventually fix this, but only from the scheduler's
        # idle pass, i.e. only if the app goes ONLINE with the collector idle -- so an
        # airplane-first user who imports and browses offline would sit on drifted counters
        # indefinitely, undisclosed. Repair it HERE, authoritatively.
        #
        # UNCONDITIONAL (outside the reindex_imported branch above): the drift comes from the
        # MERGE, so it exists whether or not the re-index ran, and it must also be repaired on
        # the re-index's own failure path. Idempotent, so running it after a successful
        # re-index is free. Best-effort + timed, exactly like the reconcile of
        # Source.article_count a few stages above -- which exists for this same class of
        # stale-but-non-NULL counter ("a wrong count shown as exact").
        #
        # SINCE THE 2026-07-29 OPTION-(a) RULING this is INSURANCE, not the load-bearing
        # repair: half (1) above cannot arise any more, because the merge no longer copies
        # the mention rows at all and the re-index is what creates them (with correct
        # counter deltas). It is deliberately KEPT because it still repairs drift already
        # sitting in corpora imported BEFORE that ruling -- real, on this maintainer's own
        # store -- and because a reconcile that runs only sometimes is the kind of
        # conditional an operator cannot reason about.
        #
        # IMPORT-SPEED FIX (field report 2026-07-30): it used to call the UNBOUNDED
        # `backfill_keyword_counters`, a whole-corpus GROUP BY over keyword_mentions plus
        # a rewrite of EVERY keyword row -- paid in full on EVERY item of an import queue,
        # over a corpus that grows with each one. It now runs the BOUNDED, RESUMABLE
        # sweep the scheduler's idle maintenance already uses: same authoritative repair,
        # same zero-then-set arithmetic, but walked in id-ordered slices under a soft
        # deadline with a DURABLE cursor (`counter_reconcile_cursor`) that survives across
        # items -- so a queue amortises ONE sweep across its items instead of redoing a
        # whole-corpus one per item. Nothing is hidden by the change: only the keywords a
        # pass actually verified get stamped, so `counter_envelope` keeps disclosing the
        # counters as `estimated` until a whole sweep lands -- a half-reconciled corpus can
        # never masquerade as exact. Still a NAMED, TIMED stage, so the real number shows up
        # in report["timings"] on the operator's hardware rather than being guessed at.
        with timings.stage("keyword_counter_reconcile"):
            try:
                from src.analytics.store import reconcile_keyword_counters
                from src.database.session import session_scope

                with session_scope() as _cnt_sess:
                    report["keyword_counters"] = reconcile_keyword_counters(_cnt_sess)
            except Exception:  # noqa: BLE001 - never undo a committed, additive restore
                _LOG.warning("keyword-counter reconcile after restore-merge failed", exc_info=True)
                report["keyword_counters"] = {"reconciled": False, "error": "see server log"}

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
    finally:
        # W5 + skeptic fix: release the active-staging guard on EVERY exit
        # path (success or exception) -- from this point on, THIS commit's
        # own snapshot is fair game for the age sweep like any other, on its
        # own future merits (age + not-currently-active).
        _snapshot_guard.close()
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
