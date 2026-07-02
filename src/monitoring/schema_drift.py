"""
Schema / index drift report — the "does the live DB match what the code expects?" log.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Recursive-augmentation log #4 (maintainer 2026-07-02): at a decade-scale corpus a
single MISSING INDEX is a massive, silent perf bug, and a column the self-heal path
skipped makes an analytic quietly wrong. This compares the LIVE database (SQLite
PRAGMA introspection) against what the SQLAlchemy models + the migration head expect,
so a drift shows in one glance — instead of the maintainer feeling a slowdown and me
reasoning about which index is absent.

Honesty: read-only, network-free, counts + names only (no score). It reports facts —
"table X is missing column Y", "index Z the model declares is absent", "the DB is
stamped at revision R while head is H" — never a fix it applies silently.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.database.models import Base


def _head_revision() -> str | None:
    """The latest migration revision id the code ships (None if alembic is absent)."""
    try:
        from src.database.migrate import _alembic_config
        from alembic.script import ScriptDirectory

        script = ScriptDirectory.from_config(_alembic_config())
        return script.get_current_head()
    except Exception:  # noqa: BLE001 - a diagnostic must never break; alembic may be trimmed in a wheel
        return None


def _stamped_revision(session: Session) -> str | None:
    """The revision the live DB is stamped at (None if the table is absent)."""
    try:
        row = session.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()
        return row[0] if row else None
    except Exception:  # noqa: BLE001 - unstamped / non-sqlite; report as None
        return None


def schema_drift(session: Session) -> dict[str, Any]:
    """Compare the live SQLite schema to the models + migration head.

    Returns a structured report: per-table missing/extra columns, missing indexes the
    model declares, the migration stamp vs head, and the FTS virtual-table presence.
    SQLite-only introspection (the app's store); other backends report ``supported:false``.
    """
    bind = session.get_bind()
    dialect = getattr(getattr(bind, "dialect", None), "name", "")
    if dialect != "sqlite":
        return {
            "supported": False,
            "dialect": dialect,
            "note": "schema-drift introspection is implemented for SQLite (the app's store).",
        }

    insp = sa_inspect(bind)
    actual_tables = set(insp.get_table_names())

    tables_report: list[dict[str, Any]] = []
    missing_tables: list[str] = []
    total_missing_cols = 0
    total_missing_idx = 0

    for tname, table in sorted(Base.metadata.tables.items()):
        if tname not in actual_tables:
            missing_tables.append(tname)
            tables_report.append({"table": tname, "present": False})
            continue
        actual_cols = {c["name"] for c in insp.get_columns(tname)}
        expected_cols = {c.name for c in table.columns}
        missing_cols = sorted(expected_cols - actual_cols)
        # Extra columns are informational (a rolled-back model, or a self-heal column
        # the current models dropped) — never a fault by themselves.
        extra_cols = sorted(actual_cols - expected_cols)

        # Indexes the MODEL declares (explicit Index() + index=True columns) vs what
        # the DB actually has. Unique constraints create their own indexes; we compare
        # by the columns each index covers so a rename doesn't produce a false "missing".
        actual_idx = insp.get_indexes(tname)
        actual_idx_colsets = {tuple(ix.get("column_names") or []) for ix in actual_idx}
        expected_idx_colsets = {
            tuple(c.name for c in ix.columns) for ix in table.indexes
        }
        missing_idx_colsets = sorted(
            ",".join(cs) for cs in (expected_idx_colsets - actual_idx_colsets) if cs
        )

        total_missing_cols += len(missing_cols)
        total_missing_idx += len(missing_idx_colsets)
        if missing_cols or missing_idx_colsets or extra_cols:
            tables_report.append(
                {
                    "table": tname,
                    "present": True,
                    "missing_columns": missing_cols,
                    "extra_columns": extra_cols,
                    "missing_indexes": missing_idx_colsets,
                }
            )

    head = _head_revision()
    stamped = _stamped_revision(session)
    migration_behind = bool(head) and bool(stamped) and head != stamped

    # FTS virtual table — the search index the triggers keep in sync; its absence is
    # a real bug (search would silently return nothing for content).
    fts_present = "article_fts" in actual_tables

    drift = bool(missing_tables) or total_missing_cols > 0 or total_missing_idx > 0

    return {
        "supported": True,
        "dialect": dialect,
        "drift": drift,
        "migration": {
            "head": head,
            "stamped": stamped,
            "behind": migration_behind,
        },
        "fts_present": fts_present,
        "missing_tables": missing_tables,
        "counts": {
            "expected_tables": len(Base.metadata.tables),
            "actual_tables": len(actual_tables),
            "missing_tables": len(missing_tables),
            "missing_columns": total_missing_cols,
            "missing_indexes": total_missing_idx,
        },
        "tables": tables_report,
        "method": (
            "Live SQLite PRAGMA introspection vs the SQLAlchemy models + the migration "
            "head. Missing tables/columns/indexes are facts the self-heal or a migration "
            "should close; extra columns are informational. Read-only; no score."
        ),
    }
