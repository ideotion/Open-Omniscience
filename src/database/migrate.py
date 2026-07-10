"""
Alembic integration helpers.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Fresh installs build the schema with ``init_db()`` (create_all) for speed/simplicity;
this module marks such databases at the current migration baseline so future
schema changes apply cleanly via ``alembic upgrade head``. Stamping happens ONLY
when a database has no alembic version yet, so an in-progress migration state is
never clobbered.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"


def _alembic_config():
    from alembic.config import Config

    # A wheel install carries the migrations/ scripts but not the repo-root
    # alembic.ini (only logging prefs live there); Config() without a file is
    # fully functional once script_location is set explicitly below.
    cfg = Config(str(_ALEMBIC_INI)) if _ALEMBIC_INI.is_file() else Config()
    cfg.set_main_option("script_location", str(_REPO_ROOT / "migrations"))
    return cfg


def file_revision(path: Path) -> str | None:
    """Read the alembic revision stamped in a SQLite file (None if unstamped).

    Read-only URI open: safe on a staged/untrusted file.
    """
    import sqlite3

    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        try:
            row = conn.execute("SELECT version_num FROM alembic_version LIMIT 1").fetchone()
        except sqlite3.OperationalError:
            return None  # no alembic_version table
        return row[0] if row else None
    finally:
        conn.close()


def known_revisions() -> list[str]:
    """All revision ids in the migration script directory (history order not needed
    by callers; membership checks only)."""
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_config())
    return [rev.revision for rev in script.walk_revisions()]


def upgrade_database_file(path: Path, target: str = "head") -> str | None:
    """Run ``alembic upgrade`` against an ARBITRARY SQLite file -- never the live DB.

    This is the staged-copy path of the backup/restore pipeline (design §3): an
    older-schema artifact is upgraded on its staged copy before any merge, so a
    failure here is consequence-free. Returns the file's revision afterwards.
    Raises on migration failure (the caller treats the staged copy as disposable).
    """
    from alembic import command
    from sqlalchemy import create_engine

    eng = create_engine(f"sqlite:///{path}", future=True)
    try:
        with eng.begin() as conn:
            cfg = _alembic_config()
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, target)
    finally:
        eng.dispose()
    return file_revision(path)


def stamp_if_unstamped(engine) -> bool:
    """Stamp the DB at the latest migration if it has no alembic version yet.

    Returns True if a stamp was applied. Best-effort and guarded: never raises,
    so it cannot block app startup.
    """
    try:
        if "alembic_version" in inspect(engine).get_table_names():
            return False  # already managed by alembic; leave it alone
        from alembic import command

        command.stamp(_alembic_config(), "head")
        return True
    except Exception:
        return False


def _head_revision() -> str | None:
    """The single alembic head revision id (None if it can't be resolved)."""
    from alembic.script import ScriptDirectory

    try:
        heads = ScriptDirectory.from_config(_alembic_config()).get_heads()
    except Exception:  # noqa: BLE001 - a guarded helper degrades, never raises
        return None
    return heads[0] if len(heads) == 1 else None


def _current_stamp(engine) -> str | None:
    """The revision stamped on an OPEN engine's DB (None if unstamped/unreadable)."""
    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()
        return row[0] if row else None
    except Exception:  # noqa: BLE001 - no alembic_version table -> unstamped
        return None


# FTS5 external-content shadow tables (article_fts + its _data/_idx/_docsize/_config) are
# created by ensure_fts, NOT the ORM, so compare_metadata always reports them as "extra"
# (remove_table). They are the only benign schema difference on an at-head store, so we
# filter them and treat every OTHER diff as evidence the schema is not at head.
_FTS_SHADOW_PREFIX = "article_fts"


def _schema_diffs_vs_head(engine) -> list[str] | None:
    """Real schema differences between the live DB and the ORM head (empty == at head).

    Uses alembic's own ``compare_metadata`` (its drift detector) and filters ONLY the FTS5
    shadow tables it cannot know about. CONSERVATIVE by construction: any diff we cannot
    classify as benign counts AGAINST parity, so we never falsely claim head. ``None`` if
    the comparison itself failed (treated as "cannot verify" -> do not advance)."""
    try:
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext

        from src.database.models import Base

        real: list[str] = []
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            for diff in compare_metadata(ctx, Base.metadata):
                entries = diff if isinstance(diff, list) else [diff]
                for entry in entries:
                    op = str(entry[0])
                    obj = entry[-1]
                    name = str(getattr(obj, "name", obj))
                    if op == "remove_table" and name.startswith(_FTS_SHADOW_PREFIX):
                        continue  # ensure_fts's shadow table, not an ORM object
                    real.append(f"{op}:{name}")
        return real
    except Exception:  # noqa: BLE001 - cannot verify parity -> caller must not advance
        return None


def align_stamp_to_head(engine) -> dict:
    """Advance the alembic stamp to head IFF the live schema is verified fully at head (DB-8).

    The boot self-heals (``ensure_*`` + ``ensure_hot_indexes`` + ``ensure_fts``) bring an
    old store's SCHEMA to head without touching the alembic stamp, leaving a "lying stamp"
    — behind head while the schema is ahead. That lie breaks the next real migration and the
    cross-version restore's ``alembic upgrade`` (it re-adds already-present columns/indexes →
    "duplicate column"/"index already exists"). This aligns the stamp so the stamp tells the
    truth.

    SAFE BY CONSTRUCTION: it advances ONLY when ``compare_metadata`` (FTS-shadow-filtered)
    reports the schema is fully at head, so a store that is GENUINELY behind (a missing
    column) keeps its stamp and still migrates. Best-effort and never raises into boot. The
    cheap stamp check runs first, so the (metadata-only, corpus-size-independent)
    compare_metadata cost is paid only on the transient behind-stamp store, never at steady
    state.

    Returns a small verdict dict ``{"action": …}`` — one of ``unstamped`` (fresh; leave to
    stamp_if_unstamped), ``at-head``, ``unknown-revision`` (a newer/foreign fork; leave
    alone), ``no-head`` (couldn't resolve head), ``schema-behind`` (genuinely behind — the
    stamp is KEPT so it migrates), ``cannot-verify`` (the parity check errored — stamp
    KEPT), or ``advanced`` (the fix).

    HONEST RESIDUAL: parity is verified at the SCHEMA level (tables/columns/indexes). The one
    pure DATA migration with no schema signature (``normalize_country_codes``, a catalog
    normalization) is not separately verified; its effect is re-achieved by the boot catalog
    seed/normalization, so advancing past it risks at most a minor un-normalized catalog
    value, never corruption or data loss."""
    try:
        current = _current_stamp(engine)
        if current is None:
            return {"action": "unstamped"}  # stamp_if_unstamped owns the fresh path
        head = _head_revision()
        if head is None:
            return {"action": "no-head"}
        if current == head:
            return {"action": "at-head", "rev": current}
        if current not in known_revisions():
            return {"action": "unknown-revision", "rev": current}  # newer/foreign: leave alone
        diffs = _schema_diffs_vs_head(engine)
        if diffs is None:
            return {"action": "cannot-verify", "from": current}  # never advance on doubt
        if diffs:
            return {"action": "schema-behind", "from": current, "diffs": diffs[:10]}
        # Verified at head: safe to tell the truth in the stamp.
        from alembic import command

        with engine.begin() as conn:
            cfg = _alembic_config()
            cfg.attributes["connection"] = conn
            command.stamp(cfg, "head")
        return {"action": "advanced", "from": current, "to": head}
    except Exception:  # noqa: BLE001 - a stamp-alignment must never break app startup
        return {"action": "error"}
