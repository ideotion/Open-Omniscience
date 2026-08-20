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
from contextlib import contextmanager, suppress
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

#: How long the swap waits for another job's in-flight batch to finish before refusing.
#: Generous on purpose: a re-index batch is 300 articles, and the alternative to waiting
#: is throwing away an import that has already done hours of work.
_SWAP_QUIESCE_S = 180.0
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
#: An incoming corpus at least this many times the machine's RAM is reported as
#: a scale note. Not a threshold with behaviour attached -- purely the point at
#: which the ratio is worth stating out loud.
_IMPORT_SCALE_NOTE_RATIO = 2.0


def _report_import_scale(corpus_path: Path) -> dict:
    """State the import's SCALE up front, in the run journal, before the first
    expensive stage.

    Field 2026-08-03: a ~35-42 GB corpus was merged into a 2.49 GB one on an
    8.3 GB machine. Every number needed to see that coming was already on disk
    when the run started -- the staged file's size, the machine's RAM, the free
    space -- and none of them was ever recorded. The operator spent 46 minutes on
    quick_check and then 15.9 hours in one merge step before there was anything
    to look at.

    REPORTS, NEVER REFUSES. A big import on a small machine is slow, not wrong,
    and the operator may have every reason to run it anyway; blocking it would be
    the app overruling a decision that is not its own. Every field degrades to
    absent rather than to a guess.
    """
    facts: dict = {}
    try:
        facts["staged_bytes"] = corpus_path.stat().st_size
    except OSError:
        pass
    try:
        total = _total_ram_mb()
        if total:
            facts["ram_total_mb"] = total
    except Exception:  # noqa: BLE001
        pass
    try:
        import shutil as _shutil

        facts["dest_free_bytes"] = int(_shutil.disk_usage(str(corpus_path.parent)).free)
    except Exception:  # noqa: BLE001
        pass
    staged_mb = facts.get("staged_bytes", 0) / (1024 * 1024)
    ram_mb = facts.get("ram_total_mb") or 0
    if staged_mb and ram_mb:
        ratio = staged_mb / ram_mb
        facts["staged_to_ram_ratio"] = round(ratio, 1)
        if ratio >= _IMPORT_SCALE_NOTE_RATIO:
            facts["note"] = (
                f"the incoming corpus is {ratio:.1f}x this machine's RAM; the merge "
                "streams it once, so expect it to be disk-bound and long. Nothing is "
                "wrong -- this is stated so a long run is not mistaken for a stall."
            )
    try:
        from src.backup import runlog

        runlog.milestone("import_scale", **facts)
    except Exception:  # noqa: BLE001 - reporting never breaks an import
        pass
    return facts


def _sub_timer(timings: object):
    """A ``with _sub("name"):`` that records a sub-stage, or does nothing.

    Hoisted out of :func:`prepare_staged_corpus` when ``verify_copy`` needed the
    same thing. Duplicating it would have been the cheaper edit and the worse one:
    the no-phase-ping guarantee below is subtle, and two copies drift.

    Prefers ``StageTimings.sub()`` when the recorder has it -- same timing, but it
    ALSO emits a begin to the run journal, and that begin is what names the stage a
    KILLED run died in. Bare ``record()`` is end-only, so an interrupted sub-stage
    left no trace at all, which is precisely the case these exist for.

    RECORD, never STAGE: ``timings.stage()`` fires the phase-progress callback, and
    a sub-stage is not a phase. Pinging one would make the user-visible counter show
    a phase outside ``restore_stage_plan()``'s honest denominator.
    """
    _record = getattr(timings, "record", None)
    _sub_cm = getattr(timings, "sub", None)

    @contextmanager
    def _sub(name: str):
        if _sub_cm is not None:
            with _sub_cm(name):
                yield
            return
        if _record is None:
            yield
            return
        _t0 = time.monotonic()
        try:
            yield
        finally:
            # In a finally: time spent before a failure is real time the operator
            # waited, and a check that raises is exactly when knowing that helps.
            _record(name, time.monotonic() - _t0)

    return _sub


def prepare_staged_corpus(
    staged: StagedArtifact, *, allow_unverified: bool = False, timings: object = None
) -> str:
    """Validate + upgrade the staged corpus to the running schema. Never touches
    the live DB; the staged copy is disposable. Returns the artifact's original
    schema revision.

    ``timings`` (optional): a StageTimings-like recorder. When supplied, the two
    genuinely expensive halves are recorded SEPARATELY -- ``prepare_staged:validate``
    (a quick_check that reads every page of a multi-GB file) and
    ``prepare_staged:upgrade`` (the alembic chain, which on an artifact several
    revisions behind runs real migrations over the whole corpus). Optional so every
    existing caller and test is untouched, and so a timing failure can never break a
    restore."""
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

    # RECORD, never STAGE. timings.stage() also fires stage_progress_cb, which
    # drives the user-visible phase counter -- and that counter's honest
    # denominator is restore_stage_plan(). A sub-stage is not a phase: pinging one
    # would make volume_job._phase_of return 0 ("not in this restore's plan", its
    # deliberate honest-unknown value) for work that is really part of
    # prepare_staged, so the UI would flash an unknown phase mid-import. The
    # stage_a:* sub-timings a few lines up are recorded rather than staged for the
    # same reason; this follows them.
    _sub = _sub_timer(timings)

    _report_import_scale(staged.corpus_path)

    try:
        with _sub("prepare_staged:validate"):
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
    with _sub("prepare_staged:upgrade"):
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


#: Source BYTES per window in a windowed merge insert -- not rows.
#:
#: THE UNIT IS THE WHOLE POINT, and the first cut of this got it wrong. A
#: row-count window bounds rows; the cost is bytes. Measured on the shipped
#: engine (sqlcipher3, encrypted, FTS trigger live, 256 MiB cache), the SAME
#: 20,000 rows at three body sizes, each in a fresh process:
#:
#:     20,000 rows x  2 KB body  ->  178 MB   ( 9.1 KB/row)
#:     20,000 rows x  8 KB body  ->  393 MB   (20.1 KB/row)
#:     20,000 rows x 32 KB body  ->  947 MB   (48.5 KB/row)
#:
#: So a fixed 20,000-id window is ~180 MB on one corpus and ~950 MB on another.
#: On the 2026-08-05 field artifact (32.1 GB staged, ~1.43M articles = ~22 KB
#: each) it would have been ~800 MB -- five times what its own comment claimed.
#: Denominating in bytes is what makes the bound mean the same thing on every
#: corpus, and it is the same unit the backup already uses to size a volume
#: (512 MiB); the NUMBERS differ because they answer different constraints --
#: a volume is sized by the GF(2^8) parity ceiling and download granularity,
#: a window by what one machine can hold at once.
#:
#: WHY ANY OF IT IS NEEDED, measured the same way -- one INSERT..SELECT of N rows:
#:
#:     rows     temp_store=MEMORY (the sqlcipher3 default)   temp_store=FILE
#:     100,000  +663 MB                                      +0 MB
#:     200,000  +377 MB  (cumulative 1,138)                  +0 MB
#:     400,000  +735 MB  (cumulative 1,980)                  +0 MB
#:
#: ``cache_size`` does not bound it -- the 2026-08-03 cache lesson is about the
#: page cache; this is temp storage, a separate allocation. The field import put
#: 1,358,765 articles through one statement on a 5.5 GB machine.
#:
#: 64 MiB of source text costs roughly 100-200 MB of temp (the measurements
#: above put the multiplier near 1.5-2x once index and FTS churn are counted),
#: which is affordable even where temp storage is still RAM.
_MERGE_WINDOW_BYTES = 64 * 1024 * 1024

#: Floor and ceiling on the derived id window. The floor keeps a corpus of
#: enormous rows from degenerating into one statement per row (the per-statement
#: overhead would then dominate); the ceiling keeps a corpus of tiny rows from
#: producing a window so wide that stop latency and resume granularity get
#: coarse again -- the other two things a window buys.
_MERGE_WINDOW_MIN_IDS = 1_000
_MERGE_WINDOW_MAX_IDS = 200_000

#: Rows sampled to estimate the incoming table's average row size. Bounded and
#: tiny: at the field corpus's ~22 KB/article this reads ~4 MB through the codec
#: once per windowed step, against the tens of GB the step itself moves.
_MERGE_SAMPLE_ROWS = 200

#: Where a windowed insert's bound is spliced in. A caller that opts into
#: windowing and forgets the marker would run the WHOLE-corpus statement once
#: per window -- quadratic, and silent. So its absence is a hard error, never a
#: fallback to the unwindowed shape.
_WINDOW_MARK = "/*WINDOW*/"

#: A window key must be a plain identifier. Every caller passes a literal from
#: this module, so this can never fire on our own code -- which is the point of
#: keeping it: it is the guard that stays correct if a future caller ever
#: derives the name from something less fixed. Same discipline as
#: ``_SAFE_TABLE_NAME`` for the incoming table names.
_SAFE_KEY_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

#: WHY EACH WINDOWED STEP IS SAFE TO WINDOW -- and the reason this registry exists
#: rather than a comment per call site.
#:
#: MEASURED, not assumed: a ``NOT EXISTS`` against the target does NOT see rows the
#: SAME statement is inserting. So if the incoming corpus holds two rows sharing a
#: step's dedup key, the whole-corpus statement inserts BOTH and the windowed one
#: inserts ONE (the second window sees the first window's committed row). That is a
#: silent change to what lands in the user's corpus, and it is invisible to any test
#: whose fixture happens to have no internal duplicates.
#:
#: A step may therefore be windowed ONLY when a second candidate for one identity
#: cannot survive in the first place. Exactly three things establish that:
#:
#:   "unique"    the incoming dedup column is UNIQUE in the schema, so the corpus
#:               cannot contain a second row to collapse.
#:   "rep"       a ``_materialise_rep`` collapse reduces each identity group to one
#:               candidate BEFORE the insert, deterministically (lowest incoming id).
#:   "constraint" the TARGET carries a real PK/UNIQUE covering the dedup key and the
#:               insert is ``OR IGNORE``, so the constraint collapses the second
#:               candidate whether it arrives in the same statement or a later window.
#:
#: Steps deliberately NOT windowed are listed below with the reason, because
#: "absent" and "considered and refused" are not the same thing.
_WINDOWED_STEPS: dict[str, str] = {
    "articles": "unique",  # articles.hash is unique=True
    "keywords": "rep",  # rep_keywords, on (normalized_term, language)
    "article_links": "rep",  # rep_links, on (article_id, url, position)
    "article_source_relationships": "rep",  # rep_asr
    "article_keyword_association": "constraint",  # PK (article_id, keyword_id) + OR IGNORE
    "article_keywords": "constraint",  # PK (article_id, keyword_id) + OR IGNORE
    "article_mentioned_dates": "constraint",  # uq_amd_article_date + OR IGNORE
}

#: Corpus-proportional steps left UNWINDOWED, and why. Each would need a
#: ``_materialise_rep`` collapse added first -- which is a change to dedup
#: semantics, not a bounding change, so it is not smuggled in under a performance
#: slice.
_NOT_WINDOWED: dict[str, str] = {
    "source_articles": (
        "dedups on url AND content_hash, neither unique, no rep collapse. Windowing "
        "would collapse incoming-internal duplicates the whole-corpus statement keeps. "
        "Not urgent either: it is populated by external-link resolution, which is "
        "largely dormant, so it is not corpus-proportional in practice."
    ),
    "article_analyses": (
        "dedups on (article_id, kind, model, prompt_version) with a plain NOT EXISTS "
        "and no constraint behind it."
    ),
    "ai_keyword": (
        "INSERT OR IGNORE, but ix_ai_keyword_article_kind and ix_ai_keyword_term are "
        "both NON-unique, so there is no constraint for OR IGNORE to fire on -- it "
        "reads as protection that is not there. The NOT EXISTS alone does the dedup, "
        "which puts this in the same class as article_analyses."
    ),
}

_WINDOW_JUSTIFICATIONS = frozenset({"unique", "rep", "constraint"})

#: The FTS5 insert trigger, suspended for the duration of the article step.
_FTS_INSERT_TRIGGER = "article_fts_ai"

#: How many articles to index per bulk FTS statement. Same reasoning as the merge
#: window: bounded work per statement so stop latency and temp storage do not
#: scale with the corpus. Not byte-derived -- the FTS cost tracks TEXT volume,
#: which the row count tracks closely enough here, and the statement holds one
#: batch of tokenizer state rather than a materialised set.
_FTS_BULK_BATCH = 20_000


@contextmanager
def _fts_insert_suspended(con: sqlite3.Connection):
    """Drop the FTS5 AFTER INSERT trigger for the merge, restoring it after.

    WHY, measured on the operator's own field beat (imp-20260807T033245Z): 1,198
    of 1,223 beats in a five-hour merging phase had FTS5's internal segment-merge
    delete in flight -- 98% of the wall clock. ``article_fts_ai`` fires per
    inserted article and fts.py sets no automerge value, so FTS5 runs its default
    of 4 and merges b-tree segments continuously while hundreds of thousands of
    articles land in an index already holding hundreds of thousands more.

    THE TWO OBVIOUS FIXES ARE REFUTED, and are not to be re-tried: deferring
    ``automerge`` alone measured 0.93-0.97x (no help), and dropping the trigger to
    run ``'rebuild'`` afterwards measured 0.75x -- WORSE, because ``'rebuild'``
    re-indexes the whole corpus including the part already indexed. Indexing only
    the rows this merge actually added measured **1.36x faster overall**, with the
    article insert itself **23.7x** faster (38.11s -> 1.61s), against an identical
    index (same document count, same match count on identical content).

    ONLY the INSERT trigger is suspended. The merge's only write to ``articles``
    is one INSERT -- no UPDATE, no DELETE -- so the ``ad``/``au`` triggers have
    nothing to do here and are left alone, which keeps the blast radius to the one
    thing being replaced.

    The trigger is recreated from the SQL read out of ``sqlite_master``, not from
    a copy of fts.py's DDL: a second copy would drift, and this cannot. Restoration
    is in a ``finally``, so an exception mid-merge still puts it back -- and even
    if the process dies outright, the working copy is disposable and the live
    corpus never had its trigger touched. ``verify_copy`` additionally REFUSES to
    pass a working copy whose trigger is missing, so a copy that somehow lost it
    can never be swapped in.
    """
    ddl = _fts_insert_trigger_ddl(con)
    if not ddl:
        # No FTS on this corpus (or a build without the trigger): nothing to
        # suspend, and nothing to restore. Never fabricate a trigger we did not
        # find -- creating one here would add indexing to a corpus that had none.
        yield False
        return
    con.execute(f"DROP TRIGGER {_FTS_INSERT_TRIGGER}")
    try:
        yield True
    finally:
        # NOT sufficient on its own when the merge fails -- see
        # _restore_fts_insert_trigger, which merge_corpus calls AFTER its rollback.
        con.execute(ddl)


def _fts_insert_trigger_ddl(con) -> str | None:
    """The CREATE statement for the FTS insert trigger, or None if this corpus has none.

    Read from ``sqlite_master`` rather than from a copy of fts.py's DDL: a second copy
    would drift, and this cannot.
    """
    row = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
        (_FTS_INSERT_TRIGGER,),
    ).fetchone()
    return row[0] if row and row[0] else None


def _restore_fts_insert_trigger(con, ddl: str | None) -> bool:
    """Put the FTS insert trigger back AFTER a failed merge has rolled back.

    THE BUG THIS EXISTS FOR. ``_suspend_fts_insert_trigger`` restores the trigger in a
    ``finally``, and for a long time that read as sufficient. It is not, and the 2026-08-07
    finding already recorded half of why: on a failed merge what actually put the trigger
    back was SQLite's TRANSACTIONAL DDL rolling the DROP away, not the finally -- the
    finally's CREATE runs while the transaction is still open, and the merge's own ROLLBACK
    then undoes it moments later. The two mechanisms happened to cover for each other.

    Windowing broke that. A windowed step COMMITs and reopens (B1/B5), so on any corpus
    large enough to window -- which is every real field corpus -- the DROP is already
    durable by the time a later step fails. The rollback can no longer undo it, and it
    undoes the finally's CREATE instead. Probed directly: force one id per window, fail a
    step, and the working copy comes back with no FTS insert trigger.

    It failed CLOSED, which is why it stayed hidden: the working copy is disposable, and
    ``verify_copy`` refuses to pass a copy whose trigger is missing, so a trigger-less copy
    could never be swapped in. The cost was wasted work and a confusing refusal, not data.

    Called after the ROLLBACK, where ``isolation_level = None`` puts the connection back in
    autocommit, so the CREATE is durable immediately. Idempotent: it re-reads first and
    does nothing when the rollback already restored the trigger (the small-corpus case,
    where nothing ever committed). Best-effort by construction -- a failure here must never
    replace the exception the operator actually needs to see, and cannot make anything
    worse than the state it was called to repair.

    Returns True only when it actually created the trigger.
    """
    if not ddl:
        return False
    try:
        if _fts_insert_trigger_ddl(con):
            return False  # the rollback restored it; nothing committed the DROP
        con.execute(ddl)
        return True
    except Exception:  # noqa: BLE001 - never outrank the failure that brought us here
        _LOG.warning("could not restore the FTS insert trigger after a failed merge",
                     exc_info=True)
        return False


def _fts_hash_mb() -> int:
    """FTS5 pending-index budget for the bulk load, in MiB (OO_FTS_HASH_MB).

    This is a REAL allocation: FTS5 holds pending index data in memory and
    flushes a level-0 segment every time it exceeds this. It is therefore a
    deliberate, bounded number and not "as much as we can get" -- the merge
    already holds a page cache beside it, and the 2026-08-03 lesson is that a
    merge which sizes its memory by what the machine HAS is the one that dies on
    the machine that has least.
    """
    try:
        mb = int(os.getenv("OO_FTS_HASH_MB", "64"))
    except (TypeError, ValueError):
        mb = 64
    return max(1, min(mb, 512))


def _fts_index_merged_articles(
    con: sqlite3.Connection, batch_id: int, progress: dict | None = None
) -> int:
    """Index exactly the articles this batch inserted, in bounded batches.

    ``merged_rows`` is the provenance the merge already writes for every inserted
    row, so it is the exact set -- no watermark to get wrong, and correct even
    though merged article ids are not contiguous.

    THE STRATEGY, and what each piece is worth (measured 2026-08-08 on the
    production engine -- sqlcipher3 3.51.1, page_size 16384, auto_vacuum
    INCREMENTAL, cache 256 MiB, temp_store FILE -- over a base index that already
    held the same number of documents again; per-arm numbers in the PR):

    * ``hashsize`` -- NOTHING in this repo has ever set it, so FTS5 ran its
      default of **1 MiB**, flushing a new level-0 segment every megabyte of
      pending index data. A multi-GB index therefore arrives as thousands of tiny
      segments, and the crisis-merge cascade that collapses them is the cost.
      Raising it is the single cheapest lever available.
    * ``automerge = 0`` for the load, restored to 4 after. Kept from B6 -- and the
      restore is what makes the next point safe: ordinary ingest goes on merging
      segments incrementally, which is FTS5's designed behaviour and what this app
      did for its whole life before B6.
    * **NO post-load merge of any kind.** This is the change B6 got wrong.
      ``'optimize'`` merges the whole index into ONE b-tree, so its cost scales
      with the CORPUS and not with the import: measured 2.05 / 3.00 / 9.31 /
      13.81 s as the index grew 25k -> 50k -> 100k -> 150k documents, while the
      insert beside it stayed flat. With eighteen backups queued that is eighteen
      whole-index rewrites, each bigger than the last.

    WHAT THE QUERY SIDE COST, because dropping it is only defensible if search
    still works -- a faster import that quietly slows every later search is a
    transfer, not a win. Measured over six terms spanning the very common to the
    rare, bm25-ranked exactly as ``fts.search_ids`` runs them, on a reopened
    connection, at 100k+100k:

        b6 (automerge 0 + optimize)   build 29.10 s   median 74.6 ms   max 269.1 ms
        hashsize 64 + no merge        build 15.39 s   median 74.5 ms   max 262.6 ms
        hashsize 64 + bounded merge   build 17.85 s   median 72.7 ms   max 255.1 ms

    Query latency is the SAME (the middle row is marginally faster than the one
    that rewrote the whole index). A bounded incremental merge was written, and
    then deleted: it bought 2-3% on query -- inside this measurement's noise --
    for 16% more build. Raising ``hashsize`` already leaves the load with ~4
    segments, so there is very little left for a merge pass to collapse.

    Together: **1.89x faster** at 100k+100k (29.10 s -> 15.39 s), against an index
    verified identical -- same ``article_fts_docsize`` count, same MATCH row
    count, on identical content, and the pre-existing equivalence test against a
    trigger-built index still passes.

    WHAT IS STILL UNEXPLAINED, stated so nobody reads this as a solved problem:
    on the operator's own 2026-08-08 field run this step took **51,116 seconds
    and had not finished**, which is ~150x per document what any scale measured
    here predicts. That gap is NOT reproduced by this fixture and is NOT
    explained by these knobs. ``progress`` below is what will answer it: the next
    run reports how many articles it has indexed and how fast.
    """
    ids = [
        int(r[0]) for r in con.execute(
            "SELECT row_id FROM merged_rows WHERE batch_id = ? AND table_name = 'articles'"
            " ORDER BY row_id",
            (batch_id,),
        )
    ]
    if not ids:
        return 0
    if progress is not None:
        progress["total"] = len(ids)
        progress["done"] = 0
        progress["phase"] = "indexing"
    con.execute(
        "INSERT INTO article_fts(article_fts, rank) VALUES('hashsize', ?)",
        (_fts_hash_mb() * 1024 * 1024,),
    )
    con.execute("INSERT INTO article_fts(article_fts, rank) VALUES('automerge', 0)")
    try:
        for i in range(0, len(ids), _FTS_BULK_BATCH):
            chunk = ids[i:i + _FTS_BULK_BATCH]
            con.execute(
                "INSERT INTO article_fts(rowid, title, content)"  # noqa: S608  # nosec B608 - the only interpolation is a placeholder count derived from len(chunk); every id is a bound parameter
                " SELECT id, title, content FROM articles WHERE id IN"
                f" ({','.join('?' * len(chunk))})",
                chunk,
            )
            if progress is not None:
                progress["done"] = min(i + len(chunk), len(ids))
    finally:
        # Restore the defaults whatever happened, so a corpus is never left with
        # automerge disabled or an outsized hash budget -- either would change
        # every later ingest silently.
        con.execute("INSERT INTO article_fts(article_fts, rank) VALUES('automerge', 4)")
        con.execute(
            "INSERT INTO article_fts(article_fts, rank) VALUES('hashsize', ?)",
            (1024 * 1024,),
        )
        if progress is not None:
            progress["phase"] = "done"
    return len(ids)


def _materialise_rep(con: sqlite3.Connection, name: str, group_sql: str) -> int:
    """Materialise "the winning incoming id per identity group" into a temp table.

    Several steps must keep exactly ONE incoming row per natural-identity group
    before inserting, because the corresponding table carries no unique
    constraint (deliberately -- near-duplicates are reconciled later at the
    family/ring layer, not at the schema layer). They express that as an inline
    ``JOIN (SELECT ..., MIN(id) AS rep_id ... GROUP BY ...) rep``.

    That inline form CANNOT be windowed: the aggregate covers the whole source,
    so it re-runs per window and turns a linear step quadratic -- silently,
    because the answer stays correct. MEASURED on 200k rows with a 10% duplicate
    rate: 0.295 s unwindowed, 1.125 s at 4 windows, 4.279 s at 16, 17.119 s at
    64. Against 0.019 s at every width once materialised, plus 0.307 s to build
    it once.

    The materialised form keeps only the winning IDS, and the join collapses to
    ``rep.rep_id = i.id``. That is EXACTLY equivalent, not merely close: an id
    appears in the set iff it is its group's ``MIN(id)``, and an id belongs to
    exactly one group, so the discarded ``rep.<group col> = i.<group col>``
    conditions are implied by the id match rather than narrowing it. Verified as
    a set equality, not a row count, before this was written.

    The table is a TEMP table, so it survives the ``COMMIT`` between windows (a
    temp table's lifetime is the connection, not the transaction) -- the same
    property the ``temp.map_*`` id maps have always relied on across the
    already-windowed articles step.
    """
    if not _SAFE_KEY_NAME.fullmatch(name):
        raise ValueError(f"unsafe temp table name {name!r}")
    con.execute(f"DROP TABLE IF EXISTS temp.{name}")  # noqa: S608  # nosec B608 - name is regex-validated above and comes from a module literal
    con.execute(f"CREATE TEMP TABLE {name} (rep_id INTEGER PRIMARY KEY)")  # noqa: S608  # nosec B608 - name is regex-validated above and comes from a module literal
    cur = con.execute(f"INSERT INTO temp.{name} (rep_id) {group_sql}")  # noqa: S608  # nosec B608 - name is regex-validated above; group_sql is a module literal, never input
    n = cur.rowcount
    return int(n) if n is not None and n >= 0 else _count(con, f"SELECT COUNT(*) FROM temp.{name}")  # noqa: S608  # nosec B608 - name is regex-validated above and comes from a module literal


def _avg_row_bytes(con: sqlite3.Connection, src: str, lo: int, hi: int, key: str = "id") -> float:
    """Average size of an incoming row, from a bounded sample. 0.0 if unknowable.

    Sampled from THREE blocks -- near the low end, the middle and the high end of
    the id range -- rather than one. A single ``LIMIT n`` takes the oldest rows,
    and a corpus's oldest articles are not its typical ones (early scraping is
    not later scraping); three blocks cost three index seeks and make a
    systematic drift across the corpus visible to the average instead of
    invisible to it.

    This is an ESTIMATE and is treated as one: it decides only how wide a window
    is, and the result is clamped, so a badly non-uniform corpus makes the window
    a poor fit rather than making it unsafe.
    """
    cols = [r[1] for r in _q(con, f'PRAGMA inc.table_info("{src}")')]  # noqa: S608  # nosec B608 - table name comes from the app's OWN fixed schema maps (design doc D3), never input
    if not cols:
        return 0.0
    # CAST to BLOB so LENGTH counts BYTES: on TEXT it would count characters, and
    # a corpus is not ASCII -- every non-Latin script would be under-counted, i.e.
    # the window would be widest exactly where rows are biggest.
    expr = " + ".join(f'LENGTH(CAST(COALESCE("{c}", \'\') AS BLOB))' for c in cols)
    per = max(1, _MERGE_SAMPLE_ROWS // 3)
    span = max(1, hi - lo)
    total, seen = 0.0, 0
    for frac in (0.0, 0.5, 0.9):
        start = lo + int(span * frac)
        row = _q(
            con,
            f'SELECT SUM(n), COUNT(*) FROM (SELECT {expr} AS n FROM inc."{src}"'  # noqa: S608  # nosec B608 - table/column names come from the incoming schema, allowlist-validated upstream and quoted here; the sampled values are never interpolated
            f' WHERE "{key}" > ? ORDER BY "{key}" LIMIT {per})',
            (start,),
        )[0]
        total += float(row[0] or 0.0)
        seen += int(row[1] or 0)
    return total / seen if seen else 0.0


def _window_ids_for(con: sqlite3.Connection, src: str, lo: int, hi: int, key: str = "id") -> int:
    """How many ids a window may span, so it carries ~``_MERGE_WINDOW_BYTES``."""
    avg = _avg_row_bytes(con, src, lo, hi, key)
    if avg <= 0:
        return _MERGE_WINDOW_MAX_IDS  # nothing to measure: rows are trivially small
    ids = int(_MERGE_WINDOW_BYTES / avg)
    return max(_MERGE_WINDOW_MIN_IDS, min(_MERGE_WINDOW_MAX_IDS, ids))


def _insert_window(
    con: sqlite3.Connection,
    batch_id: int,
    table: str,
    insert_sql: str,
    params: tuple = (),
) -> int:
    """One INSERT..SELECT + its merged_rows provenance. Returns rows inserted.

    Uses a rowid watermark: we hold the copy exclusively, so rows with rowid >
    the pre-insert max are exactly the inserted ones.

    The count comes from the provenance INSERT's own ``rowcount`` (verified
    populated for ``INSERT..SELECT`` under sqlcipher3). It used to be a third
    pass -- ``SELECT COUNT(*) ... WHERE rowid > ?`` -- over the same btree
    range, which for ``articles`` means dragging every newly inserted article's
    full text back through the SQLCipher codec for a number we already hold.
    The COUNT survives only as a fallback for a driver that declines to report.
    """
    wm = con.execute(f'SELECT COALESCE(MAX(rowid), 0) FROM "{table}"').fetchone()[0]  # noqa: S608  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
    con.execute(insert_sql, params)
    cur = con.execute(
        f'INSERT INTO merged_rows (batch_id, table_name, row_id) '  # noqa: S608  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        f'SELECT ?, ?, rowid FROM "{table}" WHERE rowid > ?',
        (batch_id, table, wm),
    )
    n = cur.rowcount
    if n is None or n < 0:  # a driver that does not report -- pay for the scan
        return _count(con, f'SELECT COUNT(*) FROM "{table}" WHERE rowid > ?', (wm,))  # noqa: S608  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
    return int(n)


def _insert_tracked(
    con: sqlite3.Connection,
    batch_id: int,
    table: str,
    insert_sql: str,
    params: tuple = (),
    *,
    src: str | None = None,
    src_key: str = "id",
) -> int:
    """Run an INSERT..SELECT and record every new row in merged_rows (provenance).

    ``src`` opts this call into WINDOWED execution over the incoming table's
    primary key: the statement runs once per slice of ``i.<src_key>``, committing
    between slices, so memory and temp storage scale with the window instead of
    with the corpus. The incoming table MUST be aliased ``i`` (the house
    convention throughout this module) and ``insert_sql`` MUST carry
    ``_WINDOW_MARK`` where the bound belongs.

    ``src_key`` names the column to slice on, defaulting to the ``id`` surrogate
    key. Two link tables (``article_keyword_association``, ``article_keywords``)
    have a COMPOSITE primary key and no ``id`` at all, so they window on
    ``article_id`` instead. That is sound for the same reason ``id`` is: the
    windows partition the source exactly (every row has exactly one value, and
    the slices are contiguous and disjoint), which is the only property the
    window loop needs. It is NOT required to be unique -- a window simply carries
    all of an article's rows together, which is if anything the more natural
    grain.

    The slice is as many ids as fit ``_MERGE_WINDOW_BYTES`` of source data, from
    a sampled average row size -- NOT a fixed row count. Rows differ in size by
    orders of magnitude (this corpus holds articles from 1 KB to 412 KB), and
    the cost is bytes, so a fixed row count means a bound that silently means
    something different on every corpus.

    Two properties make committing mid-step safe, and neither is incidental:

      * The merge's commit point has always been the ``os.replace`` of the
        DISPOSABLE working copy, not the enclosing ``BEGIN IMMEDIATE``. A
        failure part-way leaves a half-merged working copy, which is thrown
        away; the live corpus is byte-identical either way.
      * Every windowed statement's predicate is idempotent (``WHERE NOT EXISTS
        (... m.hash = i.hash)`` and its siblings), so re-running a window
        inserts nothing. Correctness does not depend on knowing where we
        stopped -- which is what will make a durable resume cursor a pure speed
        optimisation when it is built, rather than a new way to corrupt.

    A source smaller than one window runs EXACTLY the unwindowed statement, so
    opting a small table in is a no-op rather than a behaviour change.

    ⚠ NOT EVERY STEP CAN BE WINDOWED AS WRITTEN. A statement that contains an
    aggregate over the WHOLE source runs that aggregate once per window, which
    turns a linear step quadratic -- silently, since the result stays correct.
    Three steps carried that shape (``keywords``, ``article_links``,
    ``article_source_relationships``): a ``rep`` subquery GROUPing the entire
    source to pick one representative row per identity group. Each now calls
    ``_materialise_rep`` FIRST and joins the result on ``rep_id = i.id``, which
    is O(1) per row. Before opting a NEW step in, read its SQL for subqueries
    whose FROM is the source table rather than the target -- and if you find
    one, materialise it rather than accepting the quadratic.
    """
    if src is None:
        return _insert_window(con, batch_id, table, insert_sql, params)

    if _WINDOW_MARK not in insert_sql:
        raise ValueError(
            f"windowed insert into {table!r} is missing {_WINDOW_MARK} -- without it "
            "the whole-corpus statement would run once per window"
        )
    if params:
        raise ValueError("a windowed insert binds its own parameters; pass none")
    if not _SAFE_KEY_NAME.fullmatch(src_key):
        raise ValueError(f"unsafe window key {src_key!r}")
    # Windowing is only behaviour-preserving where a second candidate for one
    # identity cannot survive; see _WINDOWED_STEPS for what establishes that and
    # for the measurement behind it. Refusing here rather than in a test alone
    # means the property is enforced on the real path, not just on the paths a
    # test happens to drive.
    if _WINDOWED_STEPS.get(src) not in _WINDOW_JUSTIFICATIONS:
        raise ValueError(
            f"{src!r} is not a registered windowed step. Windowing changes what lands "
            "when the incoming corpus holds two rows sharing the dedup key: the "
            "whole-corpus statement keeps both, a windowed one keeps the first. Add it "
            "to _WINDOWED_STEPS with its justification (unique/rep/constraint), or to "
            "_NOT_WINDOWED with the reason."
        )

    sql = insert_sql.replace(_WINDOW_MARK, f' AND i."{src_key}" > ? AND i."{src_key}" <= ?')
    # MIN as well as MAX: SQLite rowids may be negative if a row was inserted
    # with an explicit id, and starting at 0 would silently skip every such row.
    # The floor is exclusive, hence -1.
    row = _q(con, f'SELECT COALESCE(MIN("{src_key}"), 1) - 1, COALESCE(MAX("{src_key}"), 0) FROM inc."{src}"')[0]  # noqa: S608  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input; src_key is regex-validated above
    lo_min, hi_max = int(row[0]), int(row[1])
    step = _window_ids_for(con, src, lo_min, hi_max, src_key)
    if hi_max - lo_min <= step:
        return _insert_window(con, batch_id, table, sql, (lo_min, hi_max))

    total, lo = 0, lo_min
    while lo < hi_max:
        hi = min(lo + step, hi_max)
        total += _insert_window(con, batch_id, table, sql, (lo, hi))
        # Commit the window, then reopen. The step's progress-handler watcher
        # (see _step_watch) still owns stop-and-tick INSIDE each statement; this
        # is what bounds the work any one statement must hold.
        con.execute("COMMIT")
        con.execute("BEGIN IMMEDIATE")
        lo = hi
        _window_tick(table, lo - lo_min, hi_max - lo_min, total)
    return total


def _window_tick(table: str, done_ids: int, total_ids: int, rows: int) -> None:
    """Publish windowed progress into the beat. Report-only, never raises.

    This is the first honest ROW-level progress the merge has had: the step
    watcher can only report elapsed seconds, because it counts VM operations,
    which bear no relation to rows remaining. A window boundary knows exactly
    how much of the source id space is behind it.
    """
    try:
        from src.backup import runlog

        runlog.statement(f"merge {table}: {done_ids:,}/{total_ids:,} ids, {rows:,} rows in")
    except Exception:  # noqa: BLE001 - reporting must never break a merge
        pass


#: VDBE operations between progress-handler callbacks during a merge step.
#: MEASURED on the merge's own INSERT..SELECT shape (encrypted, page_size 16384):
#: 1,000 -> ~38 callbacks/s, 100 -> ~536/s. 1,000 gives a live signal several
#: times a second with no measurable cost; smaller only adds Python calls.
_STEP_WATCH_OPS = 1000

#: How often the watcher publishes a tick and re-reads should_stop. A merge step
#: that runs for hours needs to be observable, not chatty: this is a HEARTBEAT,
#: never a percentage.
_STEP_WATCH_INTERVAL_S = 2.0


class MergeStepStopped(RestoreAborted):
    """The operator's Stop, landed INSIDE a long merge step.

    Subclasses :class:`RestoreAborted` deliberately: every existing handler
    already treats that as a normal outcome rather than an error (the volume job
    reports "stopped-by-operator"; the live corpus is byte-identical either way),
    and a stop that arrives mid-statement is the same event as one that arrives
    between steps -- only more responsive. Nothing downstream needs to learn a
    new exception to keep behaving correctly."""


#: Longest SQL prefix kept as a statement's label. Enough to tell the six
#: statements of a merge step apart; short enough that a killed run's journal
#: stays readable.
_STMT_LABEL_CHARS = 120


def _stmt_label(sql: str) -> str:
    """A stable, short, whitespace-collapsed label for one SQL statement."""
    return " ".join((sql or "").split())[:_STMT_LABEL_CHARS]


@contextmanager
def _step_watch(con, index: int, total: int, name: str, should_stop, step_cb, stmt_cb=None,
                detail=None):
    """Make a long merge step observable AND interruptible from inside.

    SQLite's progress handler runs every ``_STEP_WATCH_OPS`` VDBE operations
    during a statement, and **returning non-zero aborts that statement** --
    verified directly, not assumed: the abort raises ``OperationalError:
    interrupted`` and the enclosing ``BEGIN IMMEDIATE`` rolls back to zero rows.
    That is the whole mechanism, and it buys two things the merge did not have:

    STOP THAT WORKS. Ruling 2026-07-29 item 15 says a Stop is immediate. It was
    not: ``should_stop`` was read only BETWEEN the 14 steps, so during the step
    that actually takes the time the button did nothing. Now the operator's Stop
    lands inside the statement.

    A COUNTER THAT MOVES. The run journal reported ``merge_step 2/19`` unchanged
    for sixteen hours because step 3 published nothing internally. The tick is a
    LIVENESS signal -- elapsed seconds in this step -- and deliberately NOT a
    percentage: the handler counts VM operations, which bear no honest relation
    to rows remaining, and inventing a fraction from them would be exactly the
    fabricated progress this project forbids.

    Report-only in both directions: a raising ``step_cb`` can never break a merge,
    and a raising ``should_stop`` is treated as "do not stop" (a broken stop
    predicate must not abort an hours-long import by accident).

    ``detail`` is an optional callable returning a short string appended to the
    step name. Elapsed seconds prove a step is EXECUTING; they cannot say how far
    it has got, and for most steps nothing honest can. The search-index step is
    the exception -- it walks a known list of article ids, so it knows exactly
    how much of that list is behind it -- and it is also the step that ran for
    14.2 hours in the field with the counter frozen. A raising ``detail`` is
    ignored, like every other reporting path here.
    """
    t0 = time.monotonic()
    last = [t0]
    stopped = [False]

    def _tick() -> int:
        # THE STOP CHECK IS NOT RATE-LIMITED. It is an Event.is_set() -- a lock
        # read -- so at ~38 ticks/s it costs nothing, and rate-limiting it would
        # add up to _STEP_WATCH_INTERVAL_S of latency to the one control the
        # operator is actively waiting on. Only the REPORTING is throttled: that
        # one crosses into the journal and the UI.
        if should_stop is not None:
            try:
                if should_stop():
                    stopped[0] = True
                    return 1  # aborts the running statement
            except Exception:  # noqa: BLE001 - a broken predicate never aborts a merge
                pass
        if step_cb is None:
            return 0
        now = time.monotonic()
        if now - last[0] < _STEP_WATCH_INTERVAL_S:
            return 0
        last[0] = now
        label = name
        if detail is not None:
            try:
                extra = detail()
                if extra:
                    label = f"{name} — {extra}"
            except Exception:  # noqa: BLE001 - reporting never breaks a merge
                pass
        try:
            step_cb(index, total, label, round(now - t0, 1))
        except Exception:  # noqa: BLE001 - reporting never breaks a merge
            pass
        return 0

    # ---- per-STATEMENT timing ------------------------------------------- #
    # A step-level tick proved step 3 was executing; it could not say WHICH of
    # its six statements was executing, so a 14 h step still left nothing to act
    # on. SQLite's trace callback fires once per statement START, so statement N
    # ends when N+1 begins -- per-statement timing for the whole merge from ONE
    # hook, with no call-site changes.
    #
    # WHAT THE CALLBACK MAY DO IS THE LOAD-BEARING PART, and the first version of
    # this got it wrong. The comment here used to read "no per-row cost -- these
    # are bulk statements, a handful per step, not one per article". That is true
    # of step 3's six statements and FALSE across all 19 steps, and it was written
    # without counting. The `begin` side then journalled a flushed line per
    # statement, which on a 24 h merge wrote 1.6 GB and left the app unable to
    # boot. So: `begin` must be a STORE (see runlog.statement) and only a
    # genuinely slow statement earns a durable line.
    #
    # Completion is still reported as each statement ENDS rather than at step
    # exit: the run this was built for was KILLED at hour 14 and never reached
    # any exit path. An exit-only breakdown would have produced exactly the
    # nothing we already had.
    cur: list = [None]  # [(label, t_start)] or [None]

    def _trace(sql) -> None:
        try:
            now = time.monotonic()
            prev = cur[0]
            if prev is not None and stmt_cb is not None:
                stmt_cb(index, name, prev[0], round(now - prev[1], 3), False)
            label = _stmt_label(sql if isinstance(sql, str) else str(sql))
            cur[0] = (label, now)
            if stmt_cb is not None:
                stmt_cb(index, name, label, 0.0, True)
        except Exception:  # noqa: BLE001 - tracing never breaks a merge
            pass

    traced = False
    try:
        con.set_progress_handler(_tick, _STEP_WATCH_OPS)
    except Exception:  # noqa: BLE001 - an old/exotic driver simply gets the old behaviour
        yield
        return
    try:
        con.set_trace_callback(_trace)
        traced = True
    except Exception:  # noqa: BLE001 - statement timing is a BONUS; its absence never costs the step
        traced = False
    try:
        yield
    except Exception as exc:
        # Deliberately NOT `except sqlite3.OperationalError`. The merge connection
        # comes from the raw connect() factory, so on an encrypted store it is a
        # SQLCIPHER3 connection, and sqlcipher3 raises its OWN exception classes --
        # `sqlcipher3.dbapi2.OperationalError` is not `sqlite3.OperationalError`.
        # A class-based catch here would miss the interrupt on exactly the store
        # every real corpus uses (the same cross-driver trap that made the
        # "database is locked" retry net dead on encrypted stores, fixed 2026-07-14).
        # Our own flag is the authority: if WE asked for the abort, this is it,
        # whatever the driver called it.
        if stopped[0]:
            # The transaction rolls back in merge_corpus's except, leaving the
            # working copy disposable and the live corpus untouched.
            raise MergeStepStopped(
                f"stopped during the merge (inside the '{name}' step) — "
                "nothing was written to your corpus"
            ) from exc
        raise
    finally:
        # Close out the statement still in flight, so the LAST one in a step is
        # reported too (it has no successor to end it). Runs on the abort path
        # as well -- when a stop lands inside a statement, the one it landed in
        # is exactly the one worth naming.
        with suppress(Exception):
            prev = cur[0]
            if prev is not None and stmt_cb is not None:
                stmt_cb(index, name, prev[0], round(time.monotonic() - prev[1], 3), False)
                # Clear the published in-flight slot (empty label == nothing in
                # flight). Without this a finished step leaves its last statement
                # showing in every later beat, which reads as a stall in a step
                # that already completed.
                stmt_cb(index, name, "", 0.0, True)
            cur[0] = None
        if traced:
            with suppress(Exception):
                con.set_trace_callback(None)
        with suppress(Exception):
            con.set_progress_handler(None, 0)


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
    step_cb: Callable[[int, int, str, float], None] | None = None,
    stmt_cb: Callable[[int, str, str, float, bool], None] | None = None,
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

    ``should_stop`` (field ruling 2026-07-29 item 15): checked between the
    table-merge steps AND, via :func:`_step_watch`, inside each one. Aborting
    discards the DISPOSABLE working copy; the live corpus is untouched either
    way -- that has always been true, and it is the commit point that matters
    (the ``os.replace`` at the end), not the transaction shape below.

    TRANSACTION SHAPE (changed 2026-08-06): the merge no longer runs as ONE
    transaction. Windowed steps (see ``_insert_tracked``'s ``src=``) commit
    between windows so that no single statement has to hold a whole corpus'
    worth of temp storage. A failure part-way therefore leaves a HALF-MERGED
    working copy rather than an empty one -- which is why ``merge_batches``
    starts at status ``merging`` and is only stamped ``merged`` at the end: a
    half-merged copy must never satisfy the already-merged skip
    (``_STATUS_MERGED``), or a resumed import would strand the rows it had not
    reached yet."""
    from src.database.connect import attach
    from src.database.connect import connect as db_connect

    con = db_connect(working_copy, check_same_thread=False)
    con.isolation_level = None  # explicit BEGIN/COMMIT (auto-BEGIN would collide)
    # Temp storage on DISK, not in RAM. The bundled sqlcipher3 is compiled
    # SQLITE_TEMP_STORE=2 (verified: `PRAGMA compile_options` says TEMP_STORE=2,
    # against the stdlib's TEMP_STORE=1), so every statement journal, temp table
    # and transient index defaults to memory -- and none of it is bounded by
    # cache_size. Measured on that engine, one INSERT..SELECT costs ~5 KB of RAM
    # per row inserted under the default and ZERO under FILE, with no time
    # penalty (see _MERGE_WINDOW_BYTES). Windowing bounds this too; setting it
    # explicitly means a later window-size increase cannot quietly bring it back.
    try:
        con.execute("PRAGMA temp_store=FILE")
    except Exception:  # noqa: BLE001 - a tuning PRAGMA must never break a merge
        pass
    if cache_mb:
        try:
            con.execute(f"PRAGMA cache_size=-{int(cache_mb) * 1024}")  # negative = KiB
        except Exception:  # noqa: BLE001 - a tuning PRAGMA must never break a merge
            pass
    # Captured BEFORE the transaction opens, because the failure path needs it AFTER the
    # rollback -- by then the trigger may be gone from sqlite_master and its own DDL with
    # it. See _restore_fts_insert_trigger for why the finally alone does not cover this.
    fts_trigger_ddl = _fts_insert_trigger_ddl(con)
    try:
        con.execute("PRAGMA foreign_keys=OFF")  # order is FK-safe; checked at the end
        attach(con, staged_corpus, "inc")  # staged members are plaintext by design
        con.execute("BEGIN IMMEDIATE")
        results: dict[str, DomainResult] = {}

        cur = con.execute(
            "INSERT INTO merge_batches (imported_at, artifact_kind, origin_fingerprint,"
            " app_version, alembic_rev, manifest_json, source_digest, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(UTC).isoformat(timespec="seconds"),
                batch_meta.get("artifact_kind", "oo-backup-2"),
                batch_meta.get("origin_fingerprint", "unsigned"),
                batch_meta.get("app_version"),
                batch_meta.get("alembic_rev"),
                json.dumps(batch_meta.get("manifest")) if batch_meta.get("manifest") else None,
                # The digest identifies the artifact for the already-merged skip.
                # It used to rely on the whole merge being one transaction: the row
                # existed if and only if the merge committed. Windowed steps commit
                # mid-merge, so that no longer holds -- and the guarantee moved to
                # the STATUS below, which stays `merging` until every step has run.
                # A half-merged artifact must never be recorded as done, or the skip
                # would strand the rows it never reached.
                batch_meta.get("source_digest"),
                _STATUS_MERGING,
            ),
        )
        batch_id = int(cur.lastrowid or 0)

        steps = _merge_steps()
        # The FTS insert trigger is suspended across the steps and the index is
        # built once, from merged_rows, at the end. See _fts_insert_suspended for
        # the field measurement that made this the single biggest win available,
        # and for the two cheaper fixes it refutes.
        with _fts_insert_suspended(con) as fts_suspended:
            # COUNT the search-index build as a step. It is not a tail: on the
            # operator's 2026-08-08 import it was 51,116 s of a 51,631 s merge,
            # i.e. 99% of it. Reporting it as `(total, total)` against a
            # denominator that excluded it made its tick publish `done = total-1`
            # -- the same number the LAST table step publishes on completion, so
            # "18/19" meant either "watches finished" or "the search index has
            # been running for fourteen hours" and the journal could not tell
            # them apart. One more in the denominator separates them.
            total = len(steps) + (1 if fts_suspended else 0)
            for i, (name, fn) in enumerate(steps, 1):
                if should_stop is not None and should_stop():
                    # The `except` below rolls this BEGIN IMMEDIATE back; the working
                    # copy is disposable and the live corpus was never opened.
                    raise RestoreAborted(
                        f"stopped during the merge (before the '{name}' step) — "
                        "nothing was written to your corpus"
                    )
                # INSIDE the step, not just between steps. A single step can run for
                # HOURS (field 2026-08-03: 15.9 h in 'articles' alone), and for that
                # whole time the between-steps checks above are unreachable -- so a
                # Stop was inert during the longest phase of an import, and the run
                # journal's counter could not move. See _step_watch.
                with _step_watch(con, i, total, name, should_stop, step_cb, stmt_cb):
                    fn(con, batch_id, results)
                if progress_cb is not None:
                    try:
                        progress_cb(i, total, name)
                    except Exception:  # noqa: BLE001 - progress reporting must never break a merge
                        pass

            # INSIDE the suspend: the bulk load must not fire the trigger it
            # replaces. Reported as its own step so the operator sees indexing
            # rather than an unexplained tail after step 19.
            if fts_suspended:
                # The one step that CAN say how far it has got: it walks a known
                # list of ids. Everything else here reports elapsed seconds only,
                # because a VDBE-operation tick bears no honest relation to rows
                # remaining -- but a position in a list does.
                fts_prog: dict[str, object] = {"done": 0, "total": 0, "phase": "reading ids"}

                def _fts_detail() -> str:
                    done, tot = fts_prog.get("done"), fts_prog.get("total")
                    phase = fts_prog.get("phase")
                    if isinstance(tot, int) and tot and isinstance(done, int):
                        return f"{done:,}/{tot:,} articles ({phase})"
                    return str(phase)

                with _step_watch(con, total, total, "search index", should_stop, step_cb,
                                 stmt_cb, detail=_fts_detail):
                    results["article_fts"] = DomainResult(
                        new=_fts_index_merged_articles(con, batch_id, progress=fts_prog)
                    )

        # Underscore keys carry non-table diagnostic blocks (the same convention
        # `_unmerged_tables` below uses); they are plain dicts, not DomainResults.
        counts: dict[str, object] = {
            k: (v.as_dict() if hasattr(v, "as_dict") else v) for k, v in results.items()
        }
        unmerged, rejected = _unmerged_tables(con)
        if unmerged:
            counts["_unmerged_tables"] = unmerged  # stated, never silent
        if rejected:
            # Incoming table names that are not plain SQL identifiers: surfaced
            # (never silently dropped) and never interpolated/counted (OO-01).
            counts["_rejected_tables"] = rejected

        # Every step has run: only now is this artifact "merged". Before the
        # windowed steps this stamp was implicit in the single transaction; it is
        # explicit because it is no longer implicit, not as belt-and-braces.
        con.execute(
            "UPDATE merge_batches SET counts_json = ?, status = ? WHERE id = ?",
            (json.dumps(counts), _STATUS_MERGED, batch_id),
        )
        con.execute("COMMIT")
        return counts, batch_id
    except Exception:
        # suppress(Exception), NOT suppress(sqlite3.Error). On any real corpus this
        # connection is SQLCIPHER3, and `sqlcipher3.Error` is NOT a subclass of
        # `sqlite3.Error` (verified) -- so a class-scoped suppress does not catch
        # the driver's own exception, and a failed ROLLBACK inside this handler
        # would propagate and REPLACE the real failure the operator needs to see.
        #
        # And it does fail, routinely: an interrupted statement (the operator's
        # Stop, see _step_watch) leaves SQLite having already rolled back, so this
        # ROLLBACK raises "cannot rollback - no transaction is active". Before this
        # fix, a Stop on an encrypted store surfaced as that message instead of as
        # the abort. A best-effort cleanup must never outrank the cause.
        with suppress(Exception):
            con.execute("ROLLBACK")
        # AFTER the rollback, never before: the rollback is what undoes the finally's
        # own CREATE whenever a windowed step already committed the DROP. Idempotent and
        # best-effort -- it must never replace the failure above.
        _restore_fts_insert_trigger(con, fts_trigger_ddl)
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
    "source_qualification_attempts",
    # 2026-08-03, from the P0 validation on the operator's 16.5 GB corpus: these rode
    # inside every artifact and no handler copied them, so a FRESH-INSTALL restore
    # dropped them. Each has a unique constraint the schema itself defines, so its
    # cross-corpus identity is the schema's answer rather than one we invented.
    "stat_figures", "stat_subscriptions", "hazard_event_details", "keyword_tags",
    # 2026-08-03, the remaining five. These have NO unique constraint, so "the same row in
    # another corpus" was a DESIGN DECISION the schema could not answer -- each was left
    # unmerged with its question stated rather than guessed at. The maintainer ruled all
    # five that day; each handler's docstring records its identity and why.
    "watches", "watch_matches", "ai_custom_prompt", "ai_keyword", "law_revision_summaries",
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

# THE THIRD STATE, made explicit (P0 validation on the 16.5 GB / 794k-article live corpus,
# 2026-08-03). A table in neither registry above falls through to ``_unmerged_tables``, where
# it is COUNTED in the restore report and COPIED BY NOTHING -- the "reported-but-not-merged"
# middle state that reads as intentional. That is the exact shape of the 2026-07-24
# ``source_qualification_attempts`` bug, whose recorded lesson asked for "a completeness check
# that a new table must join one set or the other". This registry IS that check's third set:
# it does not change merge behaviour at all, it just makes the debt nameable, so a NEWLY added
# table cannot land here silently (tests/test_merge_completeness.py fails until it is triaged).
#
# The live report showed only NINE of these, because ``_unmerged_tables`` skips empty tables --
# so the operator's own evidence UNDER-STATES the gap by five, and would under-state it
# differently on a corpus that used watches or the AI layer. Split by what a FRESH-INSTALL
# restore would actually lose (the P0.2 acceptance bar), which is the only case where any of
# this bites: a self-restore sees every row as a duplicate and hides the whole question.
_MERGE_NOT_CARRIED: dict[str, str] = {
    # (a) REBUILT by the post-swap re-index from the article text, exactly like
    # keyword_mentions (maintainer ruling 2026-07-29). Nothing is lost; these are only
    # here rather than in _MERGE_IGNORED because the report should say so.
    #
    # WHY THEIR SIBLING ``article_mentioned_dates`` IS MERGED AND THESE ARE NOT -- this
    # looked like an inconsistency (all three are written by the same index_article
    # pass) and it is NOT. ``article_mentioned_dates`` carries a ``status`` column:
    # datestore.set_status() is a human confirm/reject, and reads filter
    # ``status != 'rejected'``. A re-index recreates every date as a fresh
    # ``candidate``, so NOT merging dates would silently discard the operator's own
    # judgements. These two tables have no such column -- purely derived, so a rebuild
    # is lossless. THE RULE, for whoever adds the next one: a derived table may be left
    # to the re-index only while it carries no human decision.
    "article_mentioned_places": "purely derived, no human channel; rebuilt by index_article",
    "article_entities": "purely derived, no human channel; rebuilt by index_article",
    # (b) PER-MACHINE or self-healing: losing them costs nothing durable.
    "derived_meta": "corpus epoch + derived bookkeeping, rebuilt on demand",
    "feed_fetch_state": "per-feed ETag/Last-Modified + backoff, re-learned on the next pass",
    "stat_snapshots": "local hourly counters; recording resumes, history is machine-local",
    # (c) GENUINELY OWED A HANDLER: not recomputable from the corpus, not per-machine, and
    # dropped by a fresh-install restore. The four with a unique constraint the SCHEMA
    # defines were built 2026-08-03 (stat_figures, stat_subscriptions, hazard_event_details,
    # keyword_tags) -- their cross-corpus identity was the schema's answer, not one we made up.
    #
    # The other five had NO unique constraint, so "the same row in another corpus" was a
    # DESIGN DECISION nothing in the database could answer, and inventing one silently is how
    # a merge starts duplicating or dropping. They were left here with their QUESTIONS stated
    # rather than guessed at; the maintainer ruled all five on 2026-08-03 and they now have
    # handlers, each recording its ruled identity and the reasoning in its own docstring.
    # This section is deliberately kept (empty of entries) as the place the next such table
    # goes: an unanswerable identity is a reason to state the question, never to guess.
}


# THE SAME COMPLETENESS CHECK, ONE GRANULARITY DOWN (2026-08-03).
#
# ``_MERGE_NOT_CARRIED`` above closed the TABLE-level hole. The identical defect exists per
# COLUMN and was still open: an ``INSERT INTO t (cols) SELECT ...`` allowlist silently drops
# every column added to the model AFTER the INSERT was written. Fourteen columns across
# seven tables had gone that way -- the deduced-language channel, the socket-observed source
# IPs, both versioned-source payloads, the law's own language, two provenance fields and the
# super-group RING marker -- each confirmed behaviourally through a real ``merge_corpus``.
#
# It is a worse failure mode than a missing table: a missing table is at least COUNTED in the
# restore report, whereas a dropped column produces a row that arrives, a column that is
# nullable, and a value that is a plausible NULL. Nothing errors and nothing is reported.
#
# So every model column of a merged table must now be either IN its INSERT or named here with
# the reason it must not be carried (tests/test_merge_carries_every_column.py enforces it).
# Anything else is an oversight by definition.
_MERGE_COLUMN_INTENTIONALLY_OMITTED: dict[str, str] = {
    # (a) DENORMALISED COUNTERS, reconciled after the merge from the rows themselves.
    # Copying an incoming count would ADD it to a local count over the same underlying rows
    # and double it; `_reconcile_source_counters` / `backfill_keyword_counters` recompute
    # them from truth instead. The reconciliation is the merge's own final step, so this is
    # a handover, not a gap.
    "sources.article_count": "denormalised counter; recomputed post-merge (copying it would double-count)",
    "sources.counter_reconciled_at": "the reconciliation's own stamp; set by the reconcile, never copied",
    "keywords.article_count": "denormalised counter; recomputed post-merge (copying it would double-count)",
    "keywords.mention_count": "denormalised counter; recomputed post-merge (copying it would double-count)",
    "keywords.last_reconciled_at": "the reconciliation's own stamp; set by the reconcile, never copied",
    # (b) PER-MACHINE state. Meaningful only for the instance that observed it: the other
    # machine's crawl clock says nothing about when THIS one last crawled, and adopting it
    # would defer a crawl that is genuinely due.
    "sources.last_crawled_at": "per-machine crawl clock; the other instance's value is not a fact about this one",
    # (c) CARRIED ELSEWHERE, not by the INSERT -- so an AST reading of the INSERT alone
    # under-reports coverage here. `parent_id` is a SELF-referential FK, so it cannot be
    # resolved in the same statement that creates the rows it points at; `_merge_keyword_
    # categories` runs a dedicated remap UPDATE through temp.map_kwcat immediately after.
    # Listed rather than left undeclared precisely so the next reader does not "fix" a
    # column that is already handled.
    "keyword_categories.parent_id": "self-FK; remapped by a dedicated UPDATE after map_kwcat is built",
    # (d) DERIVED FROM ROWS THIS MERGE DELIBERATELY DOES NOT COPY. The article's own top
    # keyword (rulings 23/38/39) is computed from that article's keyword_mentions -- and
    # `_merge_keyword_mentions` deliberately copies NONE of them (maintainer ruling
    # 2026-07-29 option (a)): the post-swap re-index produces the mentions from the
    # article text instead. Carrying the precompute would therefore state a top keyword
    # for which no local mention row exists, and top_keyword_id would additionally be an
    # id from the INCOMING corpus's keyword space -- `temp.map_keywords` is not even built
    # until after `_merge_articles` runs, so it could not be remapped in this statement
    # even if we wanted to. The re-index that produces the mentions writes these three
    # columns in the same pass (src.analytics.store.index_article), so they arrive
    # correct, from local evidence, without a merge handler.
    #
    # Safe to leave to the re-index under the 2026-08-03 rule -- a derived column may be
    # rebuilt rather than merged ONLY while it carries no human decision -- which these
    # do not: they are arithmetic over occurrence counts, with no confirm/reject state
    # (contrast article_mentioned_dates, which IS merged precisely because it carries the
    # operator's own confirm/reject verdicts).
    "articles.top_keyword_id": "derived from keyword_mentions, which the merge deliberately does not copy; the post-swap re-index recomputes it from local evidence",
    "articles.top_keyword_count": "derived from keyword_mentions, which the merge deliberately does not copy; the post-swap re-index recomputes it from local evidence",
    "articles.top_keyword_tied_n": "derived from keyword_mentions, which the merge deliberately does not copy; the post-swap re-index recomputes it from local evidence",
}


def _merge_steps() -> tuple[tuple[str, Callable[..., None]], ...]:
    """The ordered, FK-safe merge steps, named so a caller can report which is running.

    Hoisted out of ``merge_corpus`` 2026-08-03 so there is ONE source of truth: the
    per-step timing test used to hardcode "14", which meant adding a step reddened a test
    about instrumentation for a reason that had nothing to do with instrumentation. It now
    reads this tuple, so the guard is the PROPERTY (every declared step gets a named
    timing) rather than a number somebody has to remember to bump.

    The order is load-bearing and unchanged: parents before children, because the child
    handlers join the ``temp.map_*`` tables their parents build.
    """
    return (
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
        # 2026-08-03: the tables the P0 validation caught riding inside every artifact
        # with no handler. After their parents, whose id maps they join.
        ("official statistics", _merge_statistics),
        ("hazard details", _merge_hazard_details),
        ("keyword tags", _merge_keyword_tags),
        # 2026-08-03, once their cross-corpus identities were ruled. `watches` has no FK
        # so it could sit anywhere; `ai_keyword` MUST follow the article step, whose
        # temp.map_articles it joins.
        ("watches", _merge_watches),
        ("AI layer", _merge_ai_layer),
    )


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


def _qualification_tally(con, *, kept: int, disagreed: int) -> dict:
    """What this import contributed to source QUALIFICATION, read off temp.qual_landed.

    Counts only -- never a score, and never a percentage of anything. Every figure is
    exact: the landing table holds one row per source whose verdict this merge either
    INTRODUCED (a source the merge added, already carrying a verdict) or ADOPTED (a
    source that existed here but had never been judged).

    ``engines`` is the criteria version that produced each verdict
    (``Source.qualification_criteria_version``) -- the "by which engine" the field ask
    names. A verdict whose criteria version was never recorded is reported under
    ``unrecorded`` rather than being dropped or attributed to the current engine: which
    engine judged it is exactly what is unknown there.
    """
    landed: dict[str, dict[str, int]] = {}
    for mode, verdict, n in _q(
        con, "SELECT mode, verdict, COUNT(*) FROM temp.qual_landed GROUP BY mode, verdict"
    ):
        landed.setdefault(str(mode), {})[str(verdict)] = int(n)

    engines = {
        (str(row[0]) if row[0] else "unrecorded"): int(row[1])
        for row in _q(
            con, "SELECT engine, COUNT(*) FROM temp.qual_landed GROUP BY engine"
        )
    }
    _span = _q(con, "SELECT MIN(stamped_at), MAX(stamped_at) FROM temp.qual_landed")
    stamped_from, stamped_to = _span[0] if _span else (None, None)

    introduced = landed.get("introduced", {})
    adopted = landed.get("adopted", {})
    return {
        "introduced_qualified": introduced.get("qualified", 0),
        "introduced_disqualified": introduced.get("disqualified", 0),
        "adopted_qualified": adopted.get("qualified", 0),
        "adopted_disqualified": adopted.get("disqualified", 0),
        # Local-wins: verdicts this instance had already reached itself, left untouched.
        "local_verdict_kept": int(kept),
        "local_verdict_disagreed": int(disagreed),
        "engines": engines,
        "qualified_at_min": str(stamped_from) if stamped_from else None,
        "qualified_at_max": str(stamped_to) if stamped_to else None,
    }


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
    # The QUALIFICATION STAMP (status / qualified_at / qualification_criteria_version)
    # rides this INSERT. It was omitted until 2026-07-24, and the omission was not
    # cosmetic: `Source.status` carries server_default='unqualified', so every source a
    # restore introduced landed UNQUALIFIED regardless of what the incoming corpus had
    # judged it. Two consequences, both real:
    #   * `select_sources` (scheduler/runner.py) admits only status='qualified', so a
    #     merged-in source was excluded from collection until re-trialled over the
    #     network at `qualification_per_pass` (default 5) a pass — a large multi-instance
    #     merge therefore starved its own collector.
    #   * WORSE, and the reason this is a data-safety fix rather than a nicety: a source
    #     the incoming corpus had DISQUALIFIED arrived indistinguishable from
    #     never-judged, and `select_unqualified` selects exactly status='unqualified' —
    #     so a merge LAUNDERED a known-bad source back into the trial queue with its
    #     backoff ladder reset. Carrying the stamp is what stops that.
    # Cross-version safe by construction: `prepare_staged` runs the alembic chain on the
    # staged copy first (§D7), and migration 8249f1450472 adds all three columns, so
    # `inc.sources` always has them by merge time even from a pre-qualification backup.
    # The WHERE NOT EXISTS guard is UNCHANGED: this only stamps sources the merge itself
    # introduces. For a domain that already exists locally the local row still wins
    # untouched (the merge's standing policy) — the incoming EVIDENCE for it is carried
    # instead by the source_qualification_attempts merge below, which is what keeps the
    # re-qualification ladder honest without overwriting a local verdict.
    # ---- what THIS import contributes to qualification (field ask 2026-08-10) ----
    # Recorded in a temp table rather than derived afterwards, because both halves are
    # only knowable BEFORE the statements that change them: "introduced" needs the
    # NOT EXISTS predicate that stops being true the moment the INSERT below runs, and
    # "adopted" needs the local row to still read 'unqualified'.
    con.execute("DROP TABLE IF EXISTS temp.qual_landed")
    con.execute(
        "CREATE TEMP TABLE qual_landed"
        " (domain TEXT, verdict TEXT, engine TEXT, stamped_at TEXT, mode TEXT)"
    )
    con.execute(
        "INSERT INTO temp.qual_landed (domain, verdict, engine, stamped_at, mode)"
        " SELECT i.domain, i.status, i.qualification_criteria_version, i.qualified_at,"
        " 'introduced' FROM inc.sources i"
        " WHERE i.status <> 'unqualified'"
        "   AND NOT EXISTS (SELECT 1 FROM sources m WHERE m.domain = i.domain)"
    )
    # The domains about to ADOPT a verdict (they exist here and were never judged), and
    # the ones where local-wins will apply because a verdict was reached here already.
    # All four figures are measured against the PRE-MERGE local state: a first draft
    # counted `kept` after the INSERT, and a source the merge had just introduced then
    # read as a pre-existing local verdict (caught by the tally test, not by review).
    con.execute(
        "INSERT INTO temp.qual_landed (domain, verdict, engine, stamped_at, mode)"
        " SELECT i.domain, i.status, i.qualification_criteria_version, i.qualified_at,"
        " 'adopted' FROM inc.sources i JOIN sources m ON m.domain = i.domain"
        " WHERE i.status <> 'unqualified' AND m.status = 'unqualified'"
    )
    _kept = _count(
        con,
        "SELECT COUNT(*) FROM inc.sources i JOIN sources m ON m.domain = i.domain"
        " WHERE i.status <> 'unqualified' AND m.status <> 'unqualified'",
    )
    _disagreed = _count(
        con,
        "SELECT COUNT(*) FROM inc.sources i JOIN sources m ON m.domain = i.domain"
        " WHERE i.status <> 'unqualified' AND m.status <> 'unqualified'"
        "   AND i.status <> m.status",
    )
    r.new = _insert_tracked(
        con, batch_id, "sources",
        "INSERT INTO sources (name, domain, rss_url, rate_limit_ms, enabled, priority, tags,"
        " reliability_score, language, region, country, source_type, update_frequency,"
        " cacheability, status, qualified_at, qualification_criteria_version)"
        " SELECT i.name, i.domain, i.rss_url, i.rate_limit_ms, i.enabled, i.priority, i.tags,"
        " i.reliability_score, i.language, i.region, i.country, i.source_type,"
        " i.update_frequency, i.cacheability, i.status, i.qualified_at,"
        " i.qualification_criteria_version"
        " FROM inc.sources i"
        " WHERE NOT EXISTS (SELECT 1 FROM sources m WHERE m.domain = i.domain)",
    )
    for row in _q(
        con,
        "SELECT i.domain FROM inc.sources i WHERE NOT EXISTS"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        f" (SELECT 1 FROM sources m WHERE m.domain = i.domain) LIMIT {_SAMPLE_LIMIT}",
    ):
        r.samples.append(row[0])

    # ---- ADOPTION: a never-judged local row takes the incoming verdict ----
    # Field report 2026-08-10: "Export and import should integrate source having been
    # qualified ... to allow backup imports to add new validated sources to their list.
    # Currently I don't see this working."
    #
    # It did not work, and the 2026-07-24 fix above is not what was missing: that fix
    # stamps sources the merge INTRODUCES. The maintainer runs many instances all seeded
    # from the SAME catalog, so essentially every domain in an incoming backup ALREADY
    # EXISTS locally -- the INSERT's `WHERE NOT EXISTS` skips it, and the standing
    # local-wins policy left the local row at its `server_default='unqualified'`.
    # Reproduced against this function before it was changed: two domains present in
    # both corpora, judged qualified/disqualified in the incoming one, both ending
    # status='unqualified' with a NULL stamp -- while their attempt history carried
    # correctly. So one instance's qualification work was invisible to every other.
    #
    # The defect is that local-wins was defending a NON-judgement. `status` is exactly
    # unqualified|qualified|disqualified, and 'unqualified' means "no verdict has been
    # reached here" -- there is nothing to overwrite. Adopting the incoming stamp there
    # is pure information gain, and it is the SAME trust basis the merge already applies
    # one line above to a brand-new source: a domain that happens to pre-exist locally
    # but was never judged should not be treated differently from one that does not.
    #
    # It is deliberately BOTH directions. Adopting 'disqualified' is the safety
    # direction the 2026-07-24 entry argues for (a known-bad source stays out of
    # collection instead of being laundered back into the trial queue); adopting
    # 'qualified' is the direction the field ask names. Neither can overwrite a local
    # verdict: the `m.status = 'unqualified'` guard is what keeps local-wins intact
    # wherever this instance actually judged the source itself -- in particular a local
    # 'disqualified' can never be laundered to 'qualified' by an incoming corpus.
    con.execute(
        "UPDATE sources SET"
        "  status = (SELECT i.status FROM inc.sources i WHERE i.domain = sources.domain),"
        "  qualified_at = (SELECT i.qualified_at FROM inc.sources i"
        "                  WHERE i.domain = sources.domain),"
        "  qualification_criteria_version = (SELECT i.qualification_criteria_version"
        "                                    FROM inc.sources i"
        "                                    WHERE i.domain = sources.domain)"
        " WHERE sources.status = 'unqualified'"
        "   AND EXISTS (SELECT 1 FROM inc.sources i"
        "               WHERE i.domain = sources.domain AND i.status <> 'unqualified')"
    )
    results["_source_qualification"] = _qualification_tally(con, kept=_kept, disagreed=_disagreed)

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

    # The qualification ATTEMPT HISTORY (append-only, the vintage convention). Until
    # 2026-07-24 this table had NO handler at all — it appeared in neither
    # _MERGE_HANDLED nor _MERGE_IGNORED, so it fell through to _unmerged_tables: its row
    # count was reported and not one row was carried. That dropped the history for EVERY
    # domain in the incoming corpus, including domains that already existed locally.
    #
    # It matters because this table is the SYSTEM OF RECORD for the re-qualification
    # backoff ladder: `consecutive_disqualifications` counts the trailing run of
    # 'disqualified' verdicts newest-first, so losing the history silently reset every
    # merged source's ladder to zero.
    #
    # Merging it is what makes the fix complete for sources that already exist locally,
    # where the Source stamp above deliberately does NOT overwrite the local verdict: the
    # local row keeps its own current status (standing local-wins policy), while the
    # incoming EVIDENCE accumulates into the shared history the ladder actually reads. So
    # a domain disqualified on another instance still moves that instance's evidence into
    # this corpus even though its current stamp is left alone.
    #
    # source_id is REMAPPED through temp.map_sources (built above from a domain join), the
    # same machinery source_metadata/articles use — ids differ between corpora, which is
    # precisely why this table was non-trivial to merge rather than a one-line omission.
    # Dedup is on (source_id, attempted_at): re-importing the SAME backup twice adds
    # nothing, while two DIFFERENT instances' attempts on the same domain are genuinely
    # distinct attempts at distinct times and both survive. That predicate is served by
    # the table's own idx_qual_attempt_source_time index.
    q = DomainResult()
    q.new = _insert_tracked(
        con, batch_id, "source_qualification_attempts",
        "INSERT INTO source_qualification_attempts"
        " (source_id, attempted_at, verdict, criteria_version)"
        " SELECT ms.new, i.attempted_at, i.verdict, i.criteria_version"
        " FROM inc.source_qualification_attempts i"
        " JOIN temp.map_sources ms ON ms.old = i.source_id"
        " WHERE NOT EXISTS ("
        "   SELECT 1 FROM source_qualification_attempts m2"
        "   WHERE m2.source_id = ms.new AND m2.attempted_at = i.attempted_at)",
    )
    q.duplicate = max(
        0, _count(con, "SELECT COUNT(*) FROM inc.source_qualification_attempts") - q.new
    )
    results["source_qualification_attempts"] = q
    results["sources"] = r


#: Article COLUMNS a duplicate may ADOPT from the incoming corpus, grouped so that
#: columns which are only meaningful together move together. Each group is
#: ``(anchor, [columns])``: the anchor is the column whose NULL-ness decides the whole
#: group, so a pair can never end up half-filled (a sentiment label without its score,
#: an observation time without the IP it belongs to).
#:
#: The rule for membership is the one the qualification fix established one level up:
#: a local NULL here means "never measured on this machine", NOT "measured and found
#: nothing", so filling it is pure information gain and can never overwrite a local
#: measurement. Anything where NULL carries a different meaning is excluded below.
_ADOPTABLE_ARTICLE_COLUMNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("published_at", ("published_at",)),
    ("language", ("language",)),
    ("detected_language", ("detected_language",)),
    ("author", ("author",)),
    ("word_count", ("word_count",)),
    ("reading_time", ("reading_time",)),
    ("region", ("region",)),
    ("country", ("country",)),
    ("content_multihash", ("content_multihash",)),
    ("sentiment_score", ("sentiment_score", "sentiment_label")),
    ("server_ip", ("server_ip", "ip_observed_at", "server_ip_reason")),
)

#: Every other Article column, and why it is NOT adoptable. This exists because the
#: 2026-08-03 AST column diff found fourteen columns silently dropped by an explicit
#: allowlist that nobody had compared against the model since it was written. A bare
#: allowlist fails OPEN and in silence; a completeness test over BOTH sets is what makes
#: a column added later a loud choice rather than a quiet loss.
_NOT_ADOPTABLE_ARTICLE_COLUMNS: dict[str, str] = {
    "id": "primary key",
    "url": "identity, not metadata: two articles duplicate on HASH and may legitimately "
           "carry different URLs, so copying one over the other rewrites provenance",
    "canonical_url": "NOT NULL, so never absent; and same identity argument as url",
    "source_id": "remapped through temp.map_sources, never copied raw",
    "title": "content, and content equality is the dedup predicate itself",
    "content": "content (see title)",
    "compressed_content": "content (see title)",
    "hash": "the dedup key",
    "canon_version": "describes how THIS machine canonicalised its own url",
    "created_at": "local bookkeeping: when this corpus first stored the row",
    "updated_at": "local bookkeeping",
    # The quarantine block is deliberately absent from the adoptable set. It is a
    # JUDGEMENT carrying its own criteria version, not a measurement, so it belongs to
    # the qualification family (adopt-if-never-judged, both verdict directions) rather
    # than the fill-a-NULL family -- a different rule with a different safety argument.
    # Folding it in here would silently apply the weaker one. Awaiting a ruling.
    "quarantined": "a judgement, not a measurement -- see the note above",
    "quarantine_reason": "a judgement (see quarantined)",
    "quarantine_criteria_version": "a judgement (see quarantined)",
    "quarantined_at": "a judgement (see quarantined)",
}


def _adopt_article_metadata(con) -> dict:
    """Fill metadata a DUPLICATE article never had here from the incoming copy.

    Field question 2026-08-10: "in the case I imported a backup with redundant
    articles, yet they would have more metadata (due for example to AI enrichment, or
    better metadata extraction engine), the importing process would disregard those
    redundant articles and dismiss also the enhanced metadata."

    Half right, and the half that was right is the half nothing can rebuild. The
    per-article CHILD tables already ride ``temp.map_articles``, which joins on HASH and
    therefore maps duplicates too -- so AI summaries/translations (article_analyses),
    AI-derived metadata (ai_keyword), extracted dates and links all attach to the local
    twin already. What was dropped is the article's own COLUMNS, because a duplicate
    takes the ``WHERE NOT EXISTS`` path and nothing ever updated the local row.

    Two of those columns are not recoverable any other way. ``server_ip`` /
    ``ip_observed_at`` is a SOCKET-TIME observation: the connection is gone, no
    re-index rebuilds it, and a re-fetch reaches a different CDN edge or nothing at all.
    ``published_at`` is the "better extraction engine" case exactly -- the date
    extractor gained CJK, Jalali and relative-date recall over time, so an older corpus
    holds NULLs a newer instance has since filled.

    Windowed over ``inc.articles.id`` on the same terms as the article INSERT: at a ~90%
    duplicate rate this join covers most of the incoming corpus, so an unwindowed
    statement would hold the whole thing. The UPDATE carries its own guard so it only
    ever touches rows that would actually change -- without it every duplicate would be
    rewritten (and journalled) to write back the values it already had.
    """
    sets, guards, counts_sql = [], [], []
    for anchor, cols in _ADOPTABLE_ARTICLE_COLUMNS:
        for c in cols:
            # The anchor decides the whole group, so a pair moves together or not at all.
            sets.append(f'"{c}" = CASE WHEN m."{anchor}" IS NULL THEN i."{c}" ELSE m."{c}" END')
        guards.append(f'(m."{anchor}" IS NULL AND i."{anchor}" IS NOT NULL)')
        counts_sql.append(f'SUM(m."{anchor}" IS NULL AND i."{anchor}" IS NOT NULL)')

    where = (
        " FROM inc.articles i WHERE i.hash = m.hash"
        " AND i.id > ? AND i.id <= ? AND (" + " OR ".join(guards) + ")"
    )
    update_sql = "UPDATE articles AS m SET " + ", ".join(sets) + where  # nosec B608 - every fragment is built from _ADOPTABLE_ARTICLE_COLUMNS, a module constant; the only inputs are bound window bounds
    count_sql = (
        "SELECT " + ", ".join(counts_sql)  # nosec B608 - column names come from _ADOPTABLE_ARTICLE_COLUMNS, a module constant; the only inputs are bound window bounds
        + " FROM articles m JOIN inc.articles i ON i.hash = m.hash"
        " WHERE i.id > ? AND i.id <= ?"
    )

    row = _q(con, "SELECT COALESCE(MIN(id), 1) - 1, COALESCE(MAX(id), 0) FROM inc.articles")[0]
    lo_min, hi_max = int(row[0]), int(row[1])
    step = _window_ids_for(con, "articles", lo_min, hi_max)

    by_group: dict[str, int] = {}
    rows = 0

    def _one(lo: int, hi: int) -> None:
        nonlocal rows
        for (anchor, _), n in zip(
            _ADOPTABLE_ARTICLE_COLUMNS, _q(con, count_sql, (lo, hi))[0], strict=True
        ):
            if n:
                by_group[anchor] = by_group.get(anchor, 0) + int(n)
        cur = con.execute(update_sql, (lo, hi))
        rows += max(0, cur.rowcount or 0)

    # A source that fits in ONE window runs the statement once and COMMITS NOTHING,
    # exactly as _insert_tracked does.
    #
    # THIS USED TO BE LOAD-BEARING AND NO LONGER IS -- recorded rather than deleted,
    # because the reason it stopped being load-bearing is the interesting part. When this
    # pass was written, a failed merge got its FTS insert trigger back only from SQLite's
    # transactional DDL rolling the DROP away, so any COMMIT in between made the DROP
    # durable and the rollback undid the restoring CREATE instead. Committing here would
    # have left the working copy unable to index, and the short-circuit was the fix.
    #
    # That hole is now closed at its root: the merge captures the trigger's DDL before the
    # transaction opens and re-creates it AFTER the rollback, in autocommit, so the trigger
    # survives whether or not anything committed. MEASURED after that landed: removing the
    # short-circuit fails NOTHING -- test_a_failed_merge_leaves_the_working_copy_able_to_index
    # no longer discriminates for it, because the post-rollback restore repairs what the
    # mutation breaks. A guard written here that watched for the COMMIT directly was tried
    # and DELETED earlier for a different reason (its trace never saw the merge's own
    # connection), so nothing pins this line today.
    #
    # It stays because it is still free and still correct -- a single-window pass has no
    # reason to COMMIT/BEGIN at all -- not because anything depends on it. Anyone deleting
    # it should know they are trading a small saving, not breaking a contract.
    if hi_max - lo_min <= step:
        _one(lo_min, hi_max)
        return {"articles_enriched": rows, "by_column": by_group}

    lo = lo_min
    while lo < hi_max:
        hi = min(lo + step, hi_max)
        _one(lo, hi)
        con.execute("COMMIT")
        con.execute("BEGIN IMMEDIATE")
        lo = hi
    return {"articles_enriched": rows, "by_column": by_group}


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
        "INSERT INTO articles (url, canonical_url, source_id, title, content,"  # nosec B608 - every fragment is a literal; _WINDOW_MARK is a module constant replaced by a bound-parameter clause, never input
        " compressed_content, published_at, language, hash, created_at, updated_at, region,"
        " country, author, word_count, reading_time, sentiment_score, sentiment_label,"
        # 2026-08-03 (the AST column diff): three groups added to the model AFTER this
        # INSERT was written, and therefore dropped by every merge since. Each arrived
        # as a plausible NULL, which is why no restore report ever showed it.
        #   * detected_language -- the ENTIRE deduced-language channel. It is a distinct,
        #     labelled class beside the source-asserted `language` (never overwriting it),
        #     so dropping it resets every merged article to "never detected" and the
        #     langdetect ride-along re-runs at model cost over work already done.
        #   * server_ip / ip_observed_at / server_ip_reason -- a SOCKET-TIME observation.
        #     The connection is gone: no re-index can rebuild it and no re-fetch can
        #     recover it (a later fetch observes a later CDN edge). Unrecoverable is the
        #     reason this one is not merely untidy.
        #   * content_multihash / canon_version -- the K1/K2 identity seams.
        " detected_language, server_ip, ip_observed_at, server_ip_reason,"
        " content_multihash, canon_version,"
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
        " i.detected_language, i.server_ip, i.ip_observed_at, i.server_ip_reason,"
        " i.content_multihash, i.canon_version,"
        " i.quarantined, i.quarantine_reason, i.quarantine_criteria_version, i.quarantined_at"
        " FROM inc.articles i JOIN temp.map_sources ms ON ms.old = i.source_id"
        " WHERE NOT EXISTS (SELECT 1 FROM articles m WHERE m.hash = i.hash)"
        + _WINDOW_MARK,
        src="articles",
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
    # A duplicate article keeps its local row -- but a column this machine never filled
    # is not a local value to defend, it is an absence. See _adopt_article_metadata.
    results["_article_metadata"] = _adopt_article_metadata(con)
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
    #
    # Materialised ONCE rather than inlined, because this step is windowed: an
    # inline GROUP BY over the whole source re-runs per window (see
    # _materialise_rep for the measurement). `keywords` is the largest table the
    # merge still copies -- ~6.9M rows on the field corpus -- so this is the step
    # where that mattered most.
    _materialise_rep(
        con, "rep_keywords",
        "SELECT MIN(id) FROM inc.keywords GROUP BY normalized_term, COALESCE(language,'en')",
    )
    r.new = _insert_tracked(
        con, batch_id, "keywords",
        "INSERT INTO keywords (term, normalized_term, language, frequency, category_id,"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " is_ngram, ngram_size, is_entity, entity_type, relevance_score, extractor,"
        " created_at, updated_at)"
        " SELECT i.term, i.normalized_term, i.language, i.frequency, mc.new,"
        " i.is_ngram, i.ngram_size, i.is_entity, i.entity_type, i.relevance_score,"
        " i.extractor, i.created_at, i.updated_at"
        " FROM inc.keywords i LEFT JOIN temp.map_kwcat mc ON mc.old = i.category_id"
        " JOIN temp.rep_keywords rep ON rep.rep_id = i.id"
        f" WHERE NOT EXISTS (SELECT 1 FROM keywords m WHERE {key})"
        + _WINDOW_MARK,
        src="keywords",
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
        # Windowed on `article_id`, not `id`: both tables have a COMPOSITE primary
        # key and no surrogate. Safe to window (see _WINDOWED_STEPS) precisely
        # because of the OR IGNORE above -- the target's real PRIMARY KEY is what
        # collapses a second candidate for the same pair, so the whole-corpus and
        # windowed shapes cannot disagree.
        r.new += _insert_tracked(
            con, batch_id, table,
            f"INSERT OR IGNORE INTO {table} (article_id, keyword_id, {cols})"  # noqa: S608  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
            f" SELECT ma.new, mk.new, {icols} FROM inc.{table} i"
            " JOIN temp.map_articles ma ON ma.old = i.article_id"
            " JOIN temp.map_keywords mk ON mk.old = i.keyword_id"
            f" WHERE NOT EXISTS (SELECT 1 FROM {table} t"
            "  WHERE t.article_id = ma.new AND t.keyword_id = mk.new)"
            + _WINDOW_MARK,
            src=table,
            src_key="article_id",
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
        # `ring_id` added 2026-08-03 (the AST column diff), and it is the subtlest of the
        # fourteen: it is not data ABOUT the member, it is the marker of WHICH KIND of
        # member this is. Its own migration records "NULL ring_id = a plain family member"
        # as the pre-existing meaning, so a dropped ring id does not arrive as missing --
        # it arrives as a different, entirely legal member kind. `_supergroup_totals` then
        # takes the family branch and the super-group silently stops spanning languages,
        # which is the one capability the super-ring model exists to provide.
        "INSERT INTO keyword_supergroup_members (supergroup_id, normalized_term, ring_id,"
        " created_at)"
        " SELECT mg.new, i.normalized_term, i.ring_id, i.created_at"
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
        " social_media_followers, is_verified, last_verified_at, created_at, updated_at,"
        # 2026-08-03 (the AST column diff): `discovered_via` IS the Q4a ruling -- which
        # channel found this domain. It ended the table's dormancy, and a merged row with
        # it NULL is indistinguishable from one nothing ever discovered.
        " discovered_via)"
        " SELECT i.domain, i.name, i.url, i.source_type, i.credibility_score,"
        " i.political_bias, i.country, i.language, i.description, i.founded_year,"
        " i.alexa_rank, i.social_media_followers, i.is_verified, i.last_verified_at,"
        " i.created_at, i.updated_at, i.discovered_via FROM inc.external_sources i"
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
    # Materialised once (see _materialise_rep): this step is windowed, and
    # article_links is corpus-proportional -- roughly one row per outbound link
    # per article, so millions on any real corpus.
    _materialise_rep(
        con, "rep_links",
        "SELECT MIN(id) FROM inc.article_links"
        " GROUP BY article_id, url, COALESCE(position,-1)",
    )
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
        " JOIN temp.rep_links rep ON rep.rep_id = i.id"
        f" WHERE NOT EXISTS (SELECT 1 FROM article_links t WHERE {link_key})"
        + _WINDOW_MARK,
        src="article_links",
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
    # Materialised once, for the same reason -- this step is windowed too.
    _materialise_rep(
        con, "rep_asr",
        "SELECT MIN(id) FROM inc.article_source_relationships"
        " GROUP BY article_id, COALESCE(source_id,-1), COALESCE(relationship_type,'')",
    )
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
        " JOIN temp.rep_asr rep ON rep.rep_id = i.id"
        f" WHERE NOT EXISTS (SELECT 1 FROM article_source_relationships t WHERE {rel_key})"
        + _WINDOW_MARK,
        src="article_source_relationships",
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
        # `prompt_text` added 2026-08-03 (the AST column diff): the verbatim prompt is the
        # provenance of an AI output. `prompt_version` alone is a label -- it says which
        # revision, not what was actually asked -- so no AI text should be shown without it.
        "INSERT INTO article_analyses (article_id, kind, result, model, prompt_version,"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " prompt_text, created_at)"
        " SELECT ma.new, i.kind, i.result, i.model, i.prompt_version, i.prompt_text,"
        " i.created_at"
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
        f" WHERE NOT EXISTS (SELECT 1 FROM article_mentioned_dates t WHERE {md_key})"
        + _WINDOW_MARK,
        src="article_mentioned_dates",
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
        " baseline_text, last_revid, last_checked_at, missing, wiki_categories, created_at,"
        # 2026-08-03 (the AST column diff): the living-source payload. `baseline_text` is
        # the FIRST version seen; `latest_text` is the one the reader actually shows (the
        # maintainer's "the article shown is ALWAYS the LATEST version" ruling). Dropping
        # it silently reverted every merged page to its baseline.
        " latest_text, latest_text_revid)"
        " SELECT i.wiki, i.title, i.pageid, i.watched, i.category, i.baseline_revid,"
        " i.baseline_text, i.last_revid, i.last_checked_at, i.missing, i.wiki_categories,"
        " i.created_at, i.latest_text, i.latest_text_revid FROM inc.wiki_pages i"
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
        " ores_goodfaith, ores_provenance, flagged, flag_reasons, created_at,"
        # 2026-08-03 (the AST column diff): the maintainer ruled per-revision FULL TEXT
        # stored (2026-06-12) precisely BECAUSE the truncated `diff` summary cannot
        # materialise a past version locally. Dropping it on merge reinstated the exact
        # gap that ruling closed, leaving the tracked-changes history unreadable.
        " full_text)"
        " SELECT mw.new, i.revid, i.parent_revid, i.timestamp, i.editor,"
        " i.editor_anon, i.comment, i.size, i.delta_bytes, i.tags, i.minor, i.bot, i.diff,"
        " i.ores_damaging, i.ores_goodfaith, i.ores_provenance, i.flagged, i.flag_reasons,"
        " i.created_at, i.full_text"
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
        " last_checked_at, last_status, created_at,"
        # 2026-08-03 (the AST column diff). `language` is the LANGUAGE OF THE LAW, which
        # is not the country's spoken language -- Cambodian law published in French is
        # the case the law-sources acquisition contract was written around. It reaches
        # `index_article`, so dropping it hands French text to the keyword engine as
        # unknown-language and the stoplist/segmenter path degrades with no error.
        # `latest_text` is the law side of the same living-source payload as wiki above.
        " country, language, latest_text, latest_text_revid)"
        " SELECT i.jurisdiction, i.title, i.url, i.official_url, i.category,"
        " i.consolidated, i.watched, i.baseline_text, i.baseline_hash, i.last_hash,"
        " i.last_size, i.last_checked_at, i.last_status, i.created_at,"
        " i.country, i.language, i.latest_text, i.latest_text_revid"
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
        " diff, flagged, flag_reasons, created_at,"
        # 2026-08-03 (the AST column diff): as wiki_revisions above -- the stored full
        # text is what makes a past version of a law readable at all.
        " full_text)"
        " SELECT ml.new, i.observed_at, i.content_hash, i.size, i.delta_bytes, i.diff,"
        " i.flagged, i.flag_reasons, i.created_at, i.full_text"
        " FROM inc.law_revisions i JOIN temp.map_law ml ON ml.old = i.document_id"
        " WHERE NOT EXISTS (SELECT 1 FROM law_revisions t"
        "  WHERE t.document_id = ml.new AND t.content_hash = i.content_hash)",
    )
    results["law_documents"] = r
    results["law_revisions"] = rev

    # The AI summaries hang off a revision, so they need the revision's own id map --
    # built on the SAME key the dedup above uses, which is the only key that identifies
    # a revision across corpora (its local id certainly does not).
    _build_map(
        con, "map_law_rev",
        "SELECT i.id, t.id FROM inc.law_revisions i"
        " JOIN temp.map_law ml ON ml.old = i.document_id"
        " JOIN law_revisions t ON t.document_id = ml.new AND t.content_hash = i.content_hash",
    )
    summ = DomainResult()
    # IDENTITY RULED 2026-08-03 (maintainer): (revision, model) -- one summary per model,
    # so two models' readings of the same legal change sit SIDE BY SIDE rather than one
    # replacing the other. Comparing two readings of one change is the point; the table is
    # small, so keeping both costs nothing. prompt_version is deliberately NOT in the key:
    # re-running the same model under a tuned prompt updates in place instead of doubling.
    summ_key = "t.revision_id = mr.new AND t.model = i.model"
    summ.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.law_revision_summaries i"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " JOIN temp.map_law_rev mr ON mr.old = i.revision_id"
        f" WHERE EXISTS (SELECT 1 FROM law_revision_summaries t WHERE {summ_key})",
    )
    summ.new = _insert_tracked(
        con, batch_id, "law_revision_summaries",
        "INSERT INTO law_revision_summaries (revision_id, summary, model, prompt_version,"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " prompt_text, created_at)"
        " SELECT mr.new, i.summary, i.model, i.prompt_version, i.prompt_text, i.created_at"
        " FROM inc.law_revision_summaries i"
        " JOIN temp.map_law_rev mr ON mr.old = i.revision_id"
        f" WHERE NOT EXISTS (SELECT 1 FROM law_revision_summaries t WHERE {summ_key})",
    )
    results["law_revision_summaries"] = summ


def _merge_watches(con, batch_id, results) -> None:
    """The user's saved watch conditions and the history of when they fired.

    IDENTITY RULED 2026-08-03 (maintainer): a watch is identified by its NAME.

    The alternative was the condition tuple (query + threshold + window). Name won because
    a watch's name is the thing the user typed and the way they recognise it in the list,
    so the failure mode is visible and one click from fixed: rename a watch on one machine
    and a merge gives you two rows you can see and delete. Keying on the condition instead
    makes a mere window tweak produce two IDENTICAL-LOOKING rows with no way to tell them
    apart, which is the worse of the two errors.

    These are hand-authored content -- a saved condition is something the user wrote, not
    something the app can recompute -- and a fresh-install restore dropped them entirely.
    """
    w = DomainResult()
    w.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.watches i"
        " WHERE EXISTS (SELECT 1 FROM watches m WHERE m.name = i.name)",
    )
    # Local wins, the merge's standing policy: a watch that already exists here keeps ITS
    # query/threshold/window. The incoming differences are reported rather than applied.
    for row in _q(
        con,
        "SELECT i.name, i.query, m.query FROM inc.watches i"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " JOIN watches m ON m.name = i.name"
        " WHERE COALESCE(i.query,'') <> COALESCE(m.query,'')"
        f" LIMIT {_SAMPLE_LIMIT}",
    ):
        w.conflicts.append({"name": row[0], "incoming_query": row[1], "local_query": row[2]})
    w.conflict = _count(
        con,
        "SELECT COUNT(*) FROM inc.watches i JOIN watches m ON m.name = i.name"
        " WHERE COALESCE(i.query,'') <> COALESCE(m.query,'')",
    )
    w.new = _insert_tracked(
        con, batch_id, "watches",
        "INSERT INTO watches (name, query, threshold, window_days, enabled, created_at,"
        " last_evaluated_at, last_matched_at, last_seen_ids)"
        " SELECT i.name, i.query, i.threshold, i.window_days, i.enabled, i.created_at,"
        " i.last_evaluated_at, i.last_matched_at, i.last_seen_ids"
        " FROM inc.watches i"
        " WHERE NOT EXISTS (SELECT 1 FROM watches m WHERE m.name = i.name)",
    )
    results["watches"] = w

    # Follows the watch ruling with no separate decision: once a watch has a stable
    # cross-corpus identity, a firing is identified by (that watch, when it fired).
    # ``matched_at`` is a real event timestamp, so two genuine firings of one watch are
    # never the same row, and re-importing the same backup collapses correctly.
    _build_map(
        con, "map_watches",
        "SELECT i.id, m.id FROM inc.watches i JOIN watches m ON m.name = i.name",
    )
    wm = DomainResult()
    wm_key = "t.watch_id = mw.new AND t.matched_at IS i.matched_at"
    wm.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.watch_matches i"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " JOIN temp.map_watches mw ON mw.old = i.watch_id"
        f" WHERE EXISTS (SELECT 1 FROM watch_matches t WHERE {wm_key})",
    )
    wm.new = _insert_tracked(
        con, batch_id, "watch_matches",
        "INSERT INTO watch_matches (watch_id, matched_at, n_articles, new_articles, article_ids)"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " SELECT mw.new, i.matched_at, i.n_articles, i.new_articles, i.article_ids"
        " FROM inc.watch_matches i JOIN temp.map_watches mw ON mw.old = i.watch_id"
        f" WHERE NOT EXISTS (SELECT 1 FROM watch_matches t WHERE {wm_key})",
    )
    # NOTE on article_ids: it is a JSON list of the INCOMING corpus's article ids, carried
    # verbatim and NOT remapped. Remapping would need a per-id lookup through map_articles
    # for every historical firing, and the ids of articles the incoming corpus had but this
    # one does not cannot be resolved at all. So the count columns stay exactly true while
    # the id list is a record of what fired THERE -- which is why the UI reads the counts
    # and treats the id list as best-effort.
    results["watch_matches"] = wm


def _merge_ai_layer(con, batch_id, results) -> None:
    """The user's custom extractors and the AI-derived metadata they produce.

    Both are the labelled "AI-derived - unreliable" lens, never the trusted index, and
    neither is recomputable without re-running a model over the whole corpus.

    IDENTITY RULED 2026-08-03 (maintainer), for each in turn:

    ``ai_custom_prompt`` -> (output_kind, prompt_text). The alternative was the LABEL, and
    the maintainer chose text deliberately: with label-identity plus the standing
    local-wins policy, a prompt improved on a secondary machine would never travel -- the
    local row would win and the better text would be silently discarded. Keying on the
    text means an edit arrives as a second row: visible, comparable, and the user picks.
    ``output_kind`` joins the key because it is the metadata TYPE the prompt produces, so
    the same text under two kinds really is two different extractors.

    ``ai_keyword`` -> (article, kind, term, model). Two DIFFERENT models reading the same
    article both survive, because two independent models agreeing is itself the evidence
    worth keeping. ``prompt_version`` is deliberately excluded: including it would double
    every term in the corpus on each prompt re-tune, and this is the largest of the five
    tables. What that loses is which prompt revision said it -- the least load-bearing part
    of the record, and the honest trade for not multiplying the table.
    """
    p = DomainResult()
    p_key = "m.output_kind = i.output_kind AND m.prompt_text = i.prompt_text"
    p.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.ai_custom_prompt i"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        f" WHERE EXISTS (SELECT 1 FROM ai_custom_prompt m WHERE {p_key})",
    )
    p.new = _insert_tracked(
        con, batch_id, "ai_custom_prompt",
        "INSERT INTO ai_custom_prompt (label, output_kind, prompt_text, run_on_ingest,"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " enabled, created_at)"
        " SELECT i.label, i.output_kind, i.prompt_text, i.run_on_ingest, i.enabled,"
        " i.created_at FROM inc.ai_custom_prompt i"
        f" WHERE NOT EXISTS (SELECT 1 FROM ai_custom_prompt m WHERE {p_key})",
    )
    results["ai_custom_prompt"] = p

    k = DomainResult()
    # COALESCE on language is NOT part of the key -- the key is exactly what was ruled.
    k_key = "t.article_id = ma.new AND t.kind = i.kind AND t.term = i.term AND t.model = i.model"
    k.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.ai_keyword i"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " JOIN temp.map_articles ma ON ma.old = i.article_id"
        f" WHERE EXISTS (SELECT 1 FROM ai_keyword t WHERE {k_key})",
    )
    # OR IGNORE for the same reason the article-keyword links use it: map_articles can
    # collapse two incoming articles onto one local row, so two incoming ai_keyword rows
    # can target an identical key within THIS statement, which the NOT EXISTS guard (a
    # check against the pre-statement table) cannot see.
    k.new = _insert_tracked(
        con, batch_id, "ai_keyword",
        "INSERT OR IGNORE INTO ai_keyword (article_id, term, kind, language, model,"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " prompt_version, confirmed, evidence, created_at)"
        " SELECT ma.new, i.term, i.kind, i.language, i.model, i.prompt_version,"
        " i.confirmed, i.evidence, i.created_at"
        " FROM inc.ai_keyword i JOIN temp.map_articles ma ON ma.old = i.article_id"
        f" WHERE NOT EXISTS (SELECT 1 FROM ai_keyword t WHERE {k_key})",
    )
    results["ai_keyword"] = k


def _merge_statistics(con, batch_id, results) -> None:
    """Official-statistics figures + the user's auto-refresh subscriptions.

    These rode inside every artifact and no handler copied them, so a FRESH-INSTALL
    restore silently dropped them (P0 validation 2026-08-03: 35,000 figures on the
    operator's own corpus). A self-restore could never reveal it -- every row reads as
    a duplicate -- which is why it survived the field run that found it.

    A figure is NOT recomputable: it is a networked observation from a documented
    endpoint, and its VINTAGES are the point (a re-fetch at a later ``extracted_at`` is
    a NEW row, never an overwrite -- revisions are evidence). So the dedup key is the
    table's own unique constraint INCLUDING ``extracted_at``: two vintages of the same
    (agency, series, area, period) are two rows here exactly as they are in the live
    store, and merging must not collapse them into one.
    """
    fig = DomainResult()
    fig_key = (
        "t.agency = i.agency AND t.series_id = i.series_id AND t.ref_area = i.ref_area"
        " AND t.time_period = i.time_period AND t.extracted_at = i.extracted_at"
    )
    fig.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.stat_figures i"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        f" WHERE EXISTS (SELECT 1 FROM stat_figures t WHERE {fig_key})",
    )
    fig.new = _insert_tracked(
        con, batch_id, "stat_figures",
        "INSERT OR IGNORE INTO stat_figures (agency, series_id, ref_area, time_period,"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " value, unit, methodology_ref, adjustment, base_year, extracted_at, created_at)"
        " SELECT i.agency, i.series_id, i.ref_area, i.time_period, i.value, i.unit,"
        " i.methodology_ref, i.adjustment, i.base_year, i.extracted_at, i.created_at"
        " FROM inc.stat_figures i"
        f" WHERE NOT EXISTS (SELECT 1 FROM stat_figures t WHERE {fig_key})",
    )
    results["stat_figures"] = fig

    # A subscription is the user's own tracking choice. Local wins on collision: the
    # local ``enabled`` / ``interval_days`` / ``last_fetched_at`` describe THIS machine's
    # schedule, and adopting an incoming corpus's cadence would silently retune it.
    sub = DomainResult()
    sub_key = (
        "t.source = i.source AND t.indicator = i.indicator"
        " AND COALESCE(t.country,'') = COALESCE(i.country,'')"
        " AND COALESCE(t.dataset,'') = COALESCE(i.dataset,'')"
        " AND COALESCE(t.params_json,'') = COALESCE(i.params_json,'')"
        " AND COALESCE(t.agency,'') = COALESCE(i.agency,'')"
    )
    sub.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.stat_subscriptions i"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        f" WHERE EXISTS (SELECT 1 FROM stat_subscriptions t WHERE {sub_key})",
    )
    sub.new = _insert_tracked(
        con, batch_id, "stat_subscriptions",
        "INSERT OR IGNORE INTO stat_subscriptions (source, indicator, country, dataset,"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " params_json, agency, interval_days, enabled, created_at, last_fetched_at, last_status)"
        " SELECT i.source, i.indicator, i.country, i.dataset, i.params_json, i.agency,"
        " i.interval_days, i.enabled, i.created_at, i.last_fetched_at, i.last_status"
        " FROM inc.stat_subscriptions i"
        f" WHERE NOT EXISTS (SELECT 1 FROM stat_subscriptions t WHERE {sub_key})",
    )
    results["stat_subscriptions"] = sub


def _merge_hazard_details(con, batch_id, results) -> None:
    """Provider-asserted hazard metadata (magnitude / coords / event time).

    NOT recomputable: it is a snapshot of an ephemeral GDACS/USGS feed, so once the
    provider drops the event the only copy is the one in the corpus.

    Two unique constraints have to be honoured at once -- ``(provider, event_id)`` and
    ``(article_id)`` -- so the guard tests BOTH. Skipping the article_id check would let
    a row whose provider/event_id is new but whose mapped article already carries a
    detail pass the NOT-EXISTS and then violate the constraint on insert, which is the
    exact failure the article_mentioned_dates key bug caused in the field (2026-06-22).
    """
    r = DomainResult()
    key = (
        "(t.provider = i.provider AND t.event_id = i.event_id) OR t.article_id = ma.new"
    )
    r.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.hazard_event_details i"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " JOIN temp.map_articles ma ON ma.old = i.article_id"
        f" WHERE EXISTS (SELECT 1 FROM hazard_event_details t WHERE {key})",
    )
    r.new = _insert_tracked(
        con, batch_id, "hazard_event_details",
        "INSERT OR IGNORE INTO hazard_event_details (article_id, provider, event_id,"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " event_type, severity, magnitude, lat, lon, place, event_time, source_url,"
        " created_at, updated_at)"
        " SELECT ma.new, i.provider, i.event_id, i.event_type, i.severity, i.magnitude,"
        " i.lat, i.lon, i.place, i.event_time, i.source_url, i.created_at, i.updated_at"
        " FROM inc.hazard_event_details i JOIN temp.map_articles ma ON ma.old = i.article_id"
        f" WHERE NOT EXISTS (SELECT 1 FROM hazard_event_details t WHERE {key})",
    )
    results["hazard_event_details"] = r


def _merge_keyword_tags(con, batch_id, results) -> None:
    """Per-keyword tag assignments (the Item-AC two-axis taxonomy).

    Partly config-seeded and partly grown by the analyzer + the operator's own review,
    and the reviewed half is not reconstructable -- re-seeding restores the baseline and
    nothing else. Keyed on the table's own unique constraint, with ``source`` in the key
    so a curated assignment and an analyzer-proposed one for the same tag stay distinct
    rows rather than one silently standing in for the other.
    """
    r = DomainResult()
    key = (
        "t.keyword_id = mk.new AND t.axis = i.axis AND t.tag = i.tag"
        " AND COALESCE(t.source,'') = COALESCE(i.source,'')"
    )
    r.duplicate = _count(
        con,
        "SELECT COUNT(*) FROM inc.keyword_tags i"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " JOIN temp.map_keywords mk ON mk.old = i.keyword_id"
        f" WHERE EXISTS (SELECT 1 FROM keyword_tags t WHERE {key})",
    )
    r.new = _insert_tracked(
        con, batch_id, "keyword_tags",
        "INSERT OR IGNORE INTO keyword_tags (keyword_id, axis, tag, source, created_at)"  # nosec B608 - table/column names come from the app's OWN fixed schema maps (design doc D3), never input
        " SELECT mk.new, i.axis, i.tag, i.source, i.created_at"
        " FROM inc.keyword_tags i JOIN temp.map_keywords mk ON mk.old = i.keyword_id"
        f" WHERE NOT EXISTS (SELECT 1 FROM keyword_tags t WHERE {key})",
    )
    results["keyword_tags"] = r


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
def verify_copy(
    working_copy: Path, staged_corpus: Path, batch_id: int, *, timings: object = None
) -> dict:
    """Post-merge verification, all on the copy. Any failure aborts the restore
    BEFORE the swap -- the live DB never sees an unverified merge.

    ``timings`` (optional): a StageTimings-like recorder. SPLIT for the same reason
    ``prepare_staged`` is, and with more urgency: this stage runs once per queued
    backup over the WHOLE working copy, so on an 18-backup import it walks a
    growing multi-GB file eighteen times -- and it had never once been observed at
    field scale, because no run had survived long enough to reach it. The aggregate
    alone would not say which half to act on, and the halves are unrelated work:
    ``quick_check`` is a page walk of the entire file (and the working copy
    PRESERVES the live at-rest state, so on an encrypted corpus every one of those
    pages is decrypted), ``foreign_key_check`` is index-driven, and the content
    sample is a bounded join. Optional, so every existing caller and test is
    untouched and a timing failure can never break a restore.
    """
    from src.database.connect import attach
    from src.database.connect import connect as db_connect

    _sub = _sub_timer(timings)
    con = db_connect(working_copy, check_same_thread=False)
    try:
        v: dict = {}
        # The size the page walk below actually traverses. Recorded because a
        # duration alone is not portable between machines or corpus sizes: with
        # this, "2414 s" becomes "17 MB/s", which is the form that can be compared
        # against another box, against the standalone probe, or against itself
        # after the corpus doubles.
        with suppress(OSError):
            v["working_copy_bytes"] = working_copy.stat().st_size
        with _sub("verify:quick_check"):
            v["quick_check"] = con.execute("PRAGMA quick_check").fetchone()[0]
        with _sub("verify:foreign_key_check"):
            fk = con.execute("PRAGMA foreign_key_check").fetchall()
        v["foreign_key_violations"] = len(fk)

        has_fts = bool(
            con.execute(
                "SELECT 1 FROM sqlite_master WHERE name='article_fts' LIMIT 1"
            ).fetchone()
        )
        with _sub("verify:counts"):
            v["articles"] = _count(con, "SELECT COUNT(*) FROM articles")
            v.update(_verify_fts(con, has_fts, v["articles"]))

        # The merge SUSPENDS the FTS insert trigger and restores it in a finally
        # (see _fts_insert_suspended). This is the net beneath that: a working copy
        # whose trigger is missing must never become the live corpus, because the
        # damage would be SILENT and open-ended -- search would simply stop
        # indexing new articles, with nothing failing and nothing to notice. The
        # index being complete right now (checked above) says nothing about
        # whether the NEXT article will be indexed, so it needs its own check.
        v["fts_trigger_present"] = (not has_fts) or bool(
            con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?",
                (_FTS_INSERT_TRIGGER,),
            ).fetchone()
        )

        # Sampled transfer-integrity check: merged articles' content must equal
        # the staged source's content byte-for-byte (joined on the content hash).
        with _sub("verify:content_sample"):
            attach(con, staged_corpus, "inc")
            bad = _count(
                con,
                "SELECT COUNT(*) FROM ("
                " SELECT m.id FROM merged_rows r"
                " JOIN articles m ON m.id = r.row_id"
                " JOIN inc.articles i ON i.hash = m.hash"
                " WHERE r.batch_id = ? AND r.table_name = 'articles'"
                " AND i.content <> m.content"
                " LIMIT 32)",
                (batch_id,),
            )
        v["sampled_content_mismatches"] = bad
        v["ok"] = (
            v["quick_check"] == "ok"
            and v["foreign_key_violations"] == 0
            and v["fts_matches_articles"]
            and v["fts_trigger_present"]
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

    # Generated, non-reconstructable JSON documents: persisted Bulletin editions and
    # the persisted import reports. Both are collected into the artifact by
    # artifact._collect_members; until now only the collection side existed for
    # import_reports, so every restore carried them and silently dropped them on the
    # floor. A member exported with no handler is worse than one not exported: the
    # manifest says it travelled, and nothing says it did not land.
    #
    # ADDITIVE, never overwrite. Both filenames embed a timestamp plus a random id,
    # so a same-name collision means the same file; and a local document is the
    # user's own record — a merge that replaced it would rewrite history to import
    # history, which is the one thing an additive restore must never do.
    docs: dict = {}
    for role, subdir in (("bulletin", "bulletin/editions"), ("import_reports", "import_reports")):
        restored = 0
        kept_local = 0
        refused: list[str] = []
        for name, path in staged.member_paths(role):
            # Member names become filesystem paths, so they are guarded here even
            # though verify already checked them: EVERY name-to-path field runs
            # through a guard, not only the ones that motivated the rule.
            rel = Path(name)
            if rel.is_absolute() or ".." in rel.parts or not str(rel).startswith(subdir):
                refused.append(name)
                continue
            local = base / rel
            if local.exists():
                kept_local += 1
                continue
            try:
                local.parent.mkdir(parents=True, exist_ok=True)
                tmp = local.with_name(local.name + ".tmp")
                tmp.write_bytes(path.read_bytes())
                os.replace(tmp, local)
                restored += 1
            except OSError as exc:
                refused.append(f"{name}: {exc}")
        docs[role] = {"restored": restored, "kept_local": kept_local, "refused": refused}
    report["documents"] = docs

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

#: A merge that has begun but not finished. It exists because windowed steps
#: COMMIT mid-merge (see _insert_tracked), so a killed import can leave a
#: half-merged working copy carrying a batch row. Stamped `merged` only once
#: every step has run -- so the already-merged skip below, which matches
#: `status IN ('merged', 'reindexed')`, can never mistake a partial import for a
#: complete one and strand the rows it never reached.
_STATUS_MERGING = "merging"
_STATUS_MERGED = "merged"
_STATUS_REINDEXED = "reindexed"


def artifact_source_digest(src: str | os.PathLike[str]) -> str | None:
    """The identity of the BYTES in a backup folder, or None if it has none.

    Reads only the container manifest -- one small JSON file -- so this is
    answerable in milliseconds, BEFORE verify, parity-recovery, reassembly and
    staging. That is the whole point: on the field's largest run those stages cost
    2.96 h and the merge that followed them changed nothing.

    Returns None rather than raising for every reason a digest might be absent (no
    manifest, a legacy container, an unreadable folder). None means "cannot tell",
    which callers MUST treat as "do the work" -- never as "already done".
    """
    try:
        from src.backup.volumes import load_manifest

        digest = load_manifest(src).get("plaintext_sha256")
    except Exception:  # noqa: BLE001 - an unreadable manifest is an unknown, not an error
        return None
    if not isinstance(digest, str) or len(digest) != 64:
        return None
    return digest


def find_completed_import(digest: str | None) -> dict | None:
    """The batch that already merged this exact artifact, or None.

    Only a COMMITTED batch counts. The merge writes its row inside the same
    transaction as the data, so a row existing is proof the merge reached COMMIT;
    an aborted or crashed restore leaves nothing behind and is correctly retried.

    Both 'merged' and 'reindexed' count as done for THIS purpose: the distinction
    between them is whether the post-swap re-index finished, and re-importing the
    artifact would not advance that -- the re-index backlog is its own resumable
    job. Skipping here never hides a re-index backlog, which reindex_backlog()
    reports independently.
    """
    if not digest:
        return None
    from sqlalchemy import text

    from src.database.session import session_scope

    try:
        with session_scope() as session:
            row = session.execute(
                text(
                    "SELECT id, imported_at, artifact_kind, status FROM merge_batches"
                    " WHERE source_digest = :d AND status IN ('merged', 'reindexed')"
                    " ORDER BY id LIMIT 1"
                ),
                {"d": digest},
            ).fetchone()
    except Exception:  # noqa: BLE001 - a store we cannot read must not veto an import
        _LOG.warning("could not check whether this artifact was already merged", exc_info=True)
        return None
    if row is None:
        return None
    return {
        "batch_id": int(row[0]),
        "imported_at": row[1],
        "artifact_kind": row[2],
        "status": row[3],
    }


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


def peek_reindex_cursor() -> dict | None:
    """The cursor file's RAW contents, whoever it belongs to.

    :func:`_load_reindex_cursor` deliberately answers ``None`` both when no
    cursor exists and when one exists for a DIFFERENT batch -- correct for
    resuming, and a conflation for diagnosing: "never checkpointed" and
    "checkpoint discarded as foreign" are different answers to "did this resume
    or restart?". The journal records this instead of the boolean.
    """
    try:
        raw = json.loads(_reindex_state_path().read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except Exception:  # noqa: BLE001 - absent/torn cursor is a real, reportable state
        return None


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


#: The backlog read, shared by :func:`pending_reindex_batches` and
#: :func:`reindex_backlog` so the two can never drift apart again.
#:
#: ``imported_at`` is MergeBatch's own timestamp column. It was written as
#: ``created_at`` in both copies of this query until 2026-08-02, which made every
#: call raise ``no such column: b.imported_at`` on every store that ever existed:
#: ``reindex_backlog()`` degraded to ``available: false`` and
#: ``pending_reindex_batches()`` swallowed it into ``[]`` -- i.e. the ONE instrument
#: the option-(a) ruling calls its mandatory guard reported "nothing pending" while
#: a real backlog sat behind it. Field bundle 2026-08-02: 686,317 of 785,481
#: articles carried no keyword mentions and nothing said so.
_BACKLOG_SQL = (
    "SELECT b.id, b.imported_at, COUNT(m.row_id) AS n"
    " FROM merge_batches b"
    " LEFT JOIN merged_rows m"
    "   ON m.batch_id = b.id AND m.table_name = 'articles'"
    " WHERE b.status = :s"
    " GROUP BY b.id, b.imported_at"
    " HAVING COUNT(m.row_id) > 0"
    " ORDER BY b.id"
)


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
            rows = session.execute(text(_BACKLOG_SQL), {"s": _STATUS_MERGED}).fetchall()
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
            rows = session.execute(text(_BACKLOG_SQL), {"s": _STATUS_MERGED}).fetchall()
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

        # "Did this resume or start over?" -- answered from the artefact, with the
        # raw cursor so a FOREIGN checkpoint (a different batch's, correctly
        # ignored) is distinguishable from no checkpoint at all.
        from src.backup import runlog as _runlog

        _raw = peek_reindex_cursor()
        _runlog.milestone(
            "reindex_resume",
            batch_id=batch_id,
            cursor_on_disk=_raw,
            cursor_batch_id=(_raw or {}).get("batch_id"),
            resumed_after_id=resume_after,
            already_done=already,
            # BOTH denominators, named. `remaining` is what this invocation will
            # walk; `batch_total` is the batch. "3000/686896" meant different
            # things in different lines before they were both stated.
            remaining=len(ids),
            batch_total=len(all_ids),
        )
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


def _meminfo_mb(*keys: str) -> dict[str, int]:
    """Read the named ``/proc/meminfo`` fields, in MiB.

    ``/proc/meminfo`` rather than ``psutil`` for the same reason
    ``vllm_lifecycle._total_ram_bytes`` does: psutil is an optional extra
    ([analysis]) and a core install must not silently lose the measurement.

    A key absent from the result means "could not be read" -- an honest unknown,
    never a fabricated number, and the caller falls back to the fixed default."""
    want = set(keys)
    out: dict[str, int] = {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                name, _, rest = line.partition(":")
                if name in want:
                    # "MemAvailable:   10261176 kB"
                    out[name] = int(rest.split()[0]) // 1024
                    if len(out) == len(want):
                        break
    except (OSError, ValueError, IndexError):
        return {}
    return out


def _available_ram_mb() -> int | None:
    """Currently AVAILABLE RAM in MiB (``MemAvailable``) -- the kernel's own
    estimate of what a new allocation can get without swapping."""
    return _meminfo_mb("MemAvailable").get("MemAvailable")


def _total_ram_mb() -> int | None:
    """TOTAL physical RAM in MiB (``MemTotal``)."""
    return _meminfo_mb("MemTotal").get("MemTotal")


#: Share of AVAILABLE RAM an owning import may claim for the merge page cache.
_IMPORT_CACHE_RAM_SHARE = 0.25
#: Share of TOTAL RAM it may claim, whatever happens to be free right now.
#:
#: These two shares now only ever scale the budget DOWN on a small machine. The
#: ceiling below is what actually decides it on anything bigger, and the reason
#: is a measurement that refuted this comment's own previous reasoning.
#:
#: WHAT THE PREVIOUS VERSION CLAIMED, AND WHY IT WAS WRONG (field 2026-08-03):
#: it argued that because the whole 14-step merge runs inside ONE
#: ``BEGIN IMMEDIATE``, "pages dirtied early cannot be evicted until the final
#: COMMIT", so a page cache handed to a long transaction is "closer to a floor
#: on residency than a ceiling" -- and concluded that a bigger machine should
#: therefore get a bigger cache.
#:
#: SQLite does not behave that way. It SPILLS dirty pages to the database file
#: as the cache fills, keeping the transaction atomic via the rollback journal /
#: WAL. Memory during an open transaction is bounded by ``cache_size``, NOT by
#: transaction size. Measured directly (encrypted, WAL, page_size 16384, a 1 GB
#: incoming corpus, the merge's own INSERT..SELECT-with-NOT-EXISTS shape):
#:
#:     cache_size    RSS held during the open transaction    spilled to the file
#:      2048 MiB                  2042 MiB                        --
#:       989 MiB                  2026 MiB                        96 MB
#:       512 MiB                  1545 MiB                       ...
#:       256 MiB                  1286 MiB                       765 MB
#:        64 MiB                  1093 MiB                       941 MB
#:        32 MiB                  1060 MiB                       984 MB
#:
#: So the cache was never a throughput lever here -- it was a residency dial,
#: and the old rule turned it up on exactly the machines least able to pay. The
#: field cost: a ~35-42 GB corpus merging into a 2.49 GB one on an 8.3 GB box
#: got a 989 MiB cache, drove RSS to 6.4 GB, pinned all 1 GB of swap 55 minutes
#: in, and spent 15.9 HOURS inside merge step 3 without finishing it. The same
#: code merged 20k-45k-article backups in 17-91 SECONDS.
#:
#: WHY A BIGGER CACHE CANNOT HELP THIS WORKLOAD: the merge's dominant step is a
#: bulk INSERT..SELECT over the whole incoming corpus. Its working set is the
#: incoming corpus -- tens of GB, always vastly larger than any cache this would
#: hand out -- so the hit rate is ~0 whatever the size. The pages are touched
#: once. Cache exists to serve re-reads, and there are none.
#:
#: NOT CLAIMED: a specific speedup. The sandbox these numbers come from has too
#: much I/O noise to state a factor, and the field scale is 35x the probe's. The
#: RSS relationship above is monotonic and reproducible; the timing relationship
#: is not, beyond "the largest cache was never the fastest".
_IMPORT_CACHE_TOTAL_SHARE = 0.125
#: Small enough that a merge cannot squeeze the OS out of the page cache it
#: needs to stream a multi-GB staged corpus; large enough to stay well clear of
#: the region where SQLite's own defaults start to hurt.
_IMPORT_CACHE_FLOOR_MB = 32
#: MEASURED (see the table above): past this the cache buys no throughput on the
#: merge's dominant shape and only adds resident bytes. This is the bound that
#: decides the budget on any machine with more than ~2 GB of RAM.
_IMPORT_CACHE_CEIL_MB = 256


def import_cache_mb() -> int:
    """Enlarged SQLite page-cache MiB for the import merge connection
    specifically (field-feedback Session A §4, "import owns the machine") --
    SEPARATE from the app's general ``OO_SQLITE_CACHE_MB``
    (``src/config/power_profiles.py``), which never reaches this connection
    (opened via the raw ``connect()`` factory, not the pooled app engine).

    SCALES DOWN ONLY. The budget is the smaller of a quarter of what is
    available right now and an eighth of the machine's total, clamped to
    [32, 256] MiB -- so a small machine gets less, and no machine gets more.

    THE CEILING IS THE POINT, and it replaces a rule that scaled UP with RAM.
    That rule was built on the belief that an open transaction pins its dirty
    pages in memory until COMMIT; SQLite actually spills them to the file as the
    cache fills, so the cache is a residency dial and not a throughput lever for
    this workload. :data:`_IMPORT_CACHE_TOTAL_SHARE` carries the measurements and
    the field failure that produced them (15.9 hours in one merge step on an
    8.3 GB box that had been handed a 989 MiB cache).

    Because the merge's dominant step streams the whole incoming corpus exactly
    once, its working set is always far larger than any cache worth handing out
    and the hit rate is ~0 at every size. Bigger simply costs more resident bytes
    that the OS then cannot use to buffer the staged file.

    ``OO_IMPORT_CACHE_MB`` still overrides absolutely -- an operator's explicit
    number is never second-guessed, in either direction, and it remains the
    escape hatch in both directions. A machine whose RAM cannot be read falls
    back to the ceiling (the measured value), never to a guess.

    A resource-usage tuning knob only, never a behaviour change: the merge's
    results are byte-identical at any cache size."""
    raw = os.getenv("OO_IMPORT_CACHE_MB", "").strip()
    if raw:
        try:
            return max(2, int(raw))
        except ValueError:
            pass
    budgets = [
        int(v * share)
        for v, share in (
            (_available_ram_mb(), _IMPORT_CACHE_RAM_SHARE),
            (_total_ram_mb(), _IMPORT_CACHE_TOTAL_SHARE),
        )
        if v and v > 0
    ]
    if not budgets:
        # Unreadable RAM falls back to the MEASURED value, not to a guess and not
        # to the floor: the ceiling is what the measurement endorses, and the
        # shares exist only to come down from it on a small machine.
        return _IMPORT_CACHE_CEIL_MB
    return max(_IMPORT_CACHE_FLOOR_MB, min(_IMPORT_CACHE_CEIL_MB, min(budgets)))


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
    source_digest: str | None = None,
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

    # The journal sink is separate from on_start on purpose: on_start drives the
    # user-visible phase counter (whose denominator is restore_stage_plan()), the
    # sink is the durable record. Sub-stages reach the second and not the first.
    def _journal_stage(kind: str, name: str, seconds: float | None) -> None:
        from src.backup import runlog

        if kind == "begin":
            runlog.milestone("stage_begin", name=name)
        else:
            runlog.milestone("stage_end", name=name, seconds=seconds)

    timings = StageTimings(on_start=stage_progress_cb, sink=_journal_stage)

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
        # SPLIT, because the aggregate cannot be acted on. On the field's largest
        # import this ONE number was 5773 s -- 54% of the entire run, more than the
        # merge and verification combined -- and it covers two unrelated things: a
        # PRAGMA quick_check that reads every page of a multi-GB file, and an
        # alembic upgrade chain over a 700k-article corpus (report #15's artifact
        # was several revisions behind). Optimising either without knowing which is
        # the guessing that already cost a night on this import.
        original_rev = prepare_staged_corpus(
            staged, allow_unverified=allow_unverified, timings=timings
        )

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
        # Identity of the source BYTES, supplied by the caller that read the
        # container manifest. None when the caller could not tell -- recorded as
        # NULL, which never matches, so an unknown can only ever cost a redundant
        # import, never a skipped one.
        "source_digest": source_digest,
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

    def _step_tick(index: int, total: int, name: str, elapsed_s: float) -> None:
        """Liveness from INSIDE a running merge step (see _step_watch).

        Elapsed seconds only. NOT a percentage and NOT an ETA: the tick comes
        from a VDBE operation counter, which bears no honest relation to rows
        remaining, and a fraction derived from it would be invented. What it
        proves is that the step is executing -- which is precisely the question
        sixteen hours of an unchanging "2/19" could not answer.
        """
        from src.backup import runlog

        runlog.milestone(
            "merge_step_tick", durable=False,
            step=index, steps=total, label=name, step_elapsed_s=elapsed_s,
        )
        if progress_cb is not None:
            progress_cb(index - 1, total, f"{name} ({elapsed_s:.0f}s)")

    #: Statements slower than this get their own durable journal line. Below it a
    #: merge step's setup statements would bury the one that matters; the per-step
    #: rollup still carries every statement's total regardless.
    _STMT_DURABLE_S = 30.0
    _stmt_totals: dict[str, dict[str, float]] = {}

    def _stmt_tick(step: int, step_name: str, label: str, seconds: float, begin: bool) -> None:
        """Per-STATEMENT timing inside a merge step (see _step_watch).

        Emitted as each statement ENDS, not batched to the end of the step: the
        field import this was built for was killed at hour 14 and never reached
        any exit path, so anything held until then would have been lost with it.
        """
        from src.backup import runlog

        try:
            if begin:
                # A STORE, not a write. This published a journal line per statement
                # in its first version, on the mistaken belief that `durable=False`
                # meant ring-buffered; it means only "skip the fsync", so every one
                # of them was appended and flushed to the untrimmed milestone
                # stream. A 24 h merge wrote 1.6 GB and the app could no longer
                # boot, because `promote_incomplete_runs` reads that directory
                # before the unlock screen. The beat carries it now: capped,
                # already sampled every 15 s, and free per statement.
                runlog.statement(label)
                return
            agg = _stmt_totals.setdefault(label, {"seconds": 0.0, "n": 0})
            agg["seconds"] = round(agg["seconds"] + seconds, 3)
            agg["n"] += 1
            if seconds >= _STMT_DURABLE_S:
                runlog.milestone(
                    "merge_statement", durable=True,
                    step=step, label=step_name, sql=label, seconds=seconds,
                )
        except Exception:  # noqa: BLE001 - reporting never breaks a merge
            pass

    _abort_point("merge")
    with timings.stage("merge"):
        _step_clock["t"] = time.monotonic()
        counts, batch_id = merge_corpus(
            staged.corpus_path, working, meta,
            progress_cb=_timed_progress_cb, cache_mb=merge_cache_mb,
            should_stop=should_stop, step_cb=_step_tick, stmt_cb=_stmt_tick,
        )
    # Per-statement rollup into the import report: the SUM per statement, so a
    # step whose cost is spread over several executions is still attributable.
    # Slow individual statements were already journalled durably as they ended,
    # so a killed run keeps its evidence and this is the complete picture for a
    # run that finished.
    for _sql, _agg in sorted(
        _stmt_totals.items(), key=lambda kv: kv[1]["seconds"], reverse=True
    )[:40]:
        with suppress(Exception):
            timings.record(f"merge_sql:{_sql}", float(_agg["seconds"]))
    _abort_point("verify")
    with timings.stage("verify"):
        verification = verify_copy(
            working, staged.corpus_path, batch_id, timings=timings
        )

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
            # THE SWAP BARRIER (2026-08-11). os.replace has never been covered by the
            # single-writer gate -- pause_for_exclusive_operation's own docstring says
            # so -- and the gate cannot cover it: a re-index batch holds a connection
            # through its whole read-and-extract phase while holding no gate at all, so
            # a swap landing there sends its later flush to the old, now-unlinked inode.
            # Lost silently, and worse than lost: a durable cursor has already moved past
            # those articles, so nothing goes back for them.
            #
            # The exclusive window stops any new batch from STARTING; this waits out the
            # one that had already begun. On timeout the restore ABORTS -- here, at the
            # last point where aborting is free and the live corpus is byte-identical --
            # naming who was holding it. Waiting forever would trade a data-loss window
            # for a hang; swapping anyway would BE the data loss.
            #
            # The wait honours a Stop and then RE-CHECKS the abort point, in that order:
            # this wait sits past `_abort_point("swap")` above, so without both halves a
            # Stop pressed during it would be ignored for the full timeout and the swap
            # would commit anyway -- ruling item 15 says a pre-swap Stop aborts NOW. The
            # re-check must come BEFORE the still_held refusal, or a user who stopped is
            # told "another job is writing", which is the wrong cause.
            from src.database.corpus_lease import wait_for_quiescence

            still_held = wait_for_quiescence(_SWAP_QUIESCE_S, should_stop=should_stop)
            _abort_point("swap")
            if still_held:
                raise RestoreAborted(
                    "another job is still writing to your corpus ("
                    + ", ".join(still_held)
                    + f") after waiting {_SWAP_QUIESCE_S:.0f}s — nothing was written to "
                    "your corpus. Stop that job, or let it finish, and import again."
                )
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
