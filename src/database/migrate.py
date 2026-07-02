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

    cfg = Config(str(_ALEMBIC_INI))
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
