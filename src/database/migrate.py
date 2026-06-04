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
