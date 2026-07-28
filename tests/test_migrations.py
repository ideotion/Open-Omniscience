"""
Tests for the Alembic migration path (Action Plan Phase 6.3).

Proves:
  * `alembic upgrade head` on an empty DB builds the full current schema;
  * the baseline migration matches the models (`alembic check` finds no drift) --
    a durable guard that migrations stay in sync as models change;
  * init_db() stamps a fresh create_all DB at head (alembic-aware), and does not
    clobber an already-managed DB.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

REPO = Path(__file__).resolve().parents[1]


def _alembic(args: list[str], data_dir: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "OO_DATA_DIR": str(data_dir)}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
    )


def test_upgrade_head_builds_full_schema(tmp_path):
    res = _alembic(["upgrade", "head"], tmp_path)
    assert res.returncode == 0, res.stdout + res.stderr
    db = tmp_path / "open_omniscience.db"
    tables = set(inspect(create_engine(f"sqlite:///{db}")).get_table_names())
    for required in (
        "articles",
        "sources",
        "article_analyses",
        "commodity_prices",
        "alembic_version",
    ):
        assert required in tables


def test_no_model_drift(tmp_path):
    # Upgrade, then `alembic check` must report no new operations -> migration
    # matches the models exactly.
    assert _alembic(["upgrade", "head"], tmp_path).returncode == 0
    res = _alembic(["check"], tmp_path)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "No new upgrade operations detected" in (res.stdout + res.stderr)


def test_init_db_stamps_fresh_database(tmp_path, monkeypatch):
    # A DB built by create_all should end up alembic-aware (stamped at head).
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    code = (
        "import os;"
        "from src.database.session import init_db, engine;"
        "from sqlalchemy import inspect;"
        "init_db();"
        "insp = inspect(engine);"
        "ver = list(insp.get_table_names());"
        "import sys;"
        "sys.exit(0 if 'alembic_version' in ver and 'articles' in ver else 1)"
    )
    res = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO,
        env={**os.environ, "OO_DATA_DIR": str(tmp_path)},
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stdout + res.stderr


def test_env_py_fileconfig_never_disables_pre_existing_loggers(tmp_path):
    """2026-07-26 hardware-diagnostics regression: ``migrations/env.py`` called
    ``fileConfig(config.config_file_name)`` with its ``disable_existing_loggers``
    DEFAULT (True) -- Python's stdlib then silently sets ``.disabled = True`` on
    EVERY pre-existing logger not listed in ``alembic.ini``'s ``[loggers]`` (root,
    sqlalchemy, alembic only), for the rest of the PROCESS. Any Alembic call that
    stamps/upgrades against a real engine (``stamp_if_unstamped``, run at EVERY app
    boot's self-heal) triggered this -- silently and permanently swallowing every
    ERROR+ record from any OTHER already-imported logger (live-caught via
    ``trafilatura``/``trafilatura.metadata``/``htmldate``, imported earlier in
    ``src.api.main``'s import chain). Pinned generically -- a fresh, unrelated
    marker logger, not tied to any specific third-party module -- so this guards
    the mechanism, not just the one library that happened to surface it."""
    from src.database.migrate import stamp_if_unstamped
    from src.database.models import Base

    marker = logging.getLogger("test_env_py_fileconfig_marker")
    marker.disabled = False  # a real, pre-existing logger object

    engine = create_engine(f"sqlite:///{tmp_path / 'stamp.db'}", future=True)
    try:
        Base.metadata.create_all(engine)
        # This is the exact call app boot's self-heal makes; it must NOT disable
        # any pre-existing logger it doesn't own.
        assert stamp_if_unstamped(engine) is True
    finally:
        engine.dispose()

    assert marker.disabled is False, (
        "Alembic's env.py fileConfig() disabled a pre-existing logger it never "
        "listed -- pass disable_existing_loggers=False to fileConfig() in "
        "migrations/env.py"
    )
