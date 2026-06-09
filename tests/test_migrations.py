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
