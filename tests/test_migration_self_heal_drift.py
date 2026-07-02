"""Migration ↔ boot-self-heal drift guard (release-0.1 blocker, the reopen-proof).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The live DB is never alembic-migrated (only staged restore copies are), so EVERY
``add_column`` a migration ships must have a matching idempotent boot self-heal in
``src/database/maintenance.py`` (the ensure_* battery) — otherwise an existing store
opened by newer code raises "no such column" on the first ORM query (the 0.1 upgrade
audit found four such holes: keywords.extractor, the wiki living-source columns, and
keyword_supergroup_members.ring_id).

This test AST-sweeps ``migrations/versions/`` for every ``add_column`` — both the
``op.add_column(table, sa.Column(...))`` and the ``batch_alter_table`` forms, with
module-level string constants resolved — and asserts each (table, column) pair is
declared in ``maintenance.SELF_HEALED_COLUMNS`` or carries a RECORDED, reasoned
exemption below. A future migration that adds a column without a self-heal fails
here instead of breaking a user's store at upgrade.
"""

from __future__ import annotations

import ast
from pathlib import Path

from src.database.maintenance import SELF_HEALED_COLUMNS

_VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"

# (table, column) pairs DELIBERATELY left without a boot self-heal, each with an
# honest, specific reason. Keep this EMPTY unless a missing column genuinely cannot
# break an upgraded live store — e.g. a column that is only ever SELECTed behind a
# feature flag whose enablement requires a fresh database, or a table that alembic
# alone manages and the ORM never maps. Never blanket-exempt a table.
EXEMPT: dict[tuple[str, str], str] = {}


def _module_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level string constants (``_TABLE = "articles"``), plain or annotated."""
    consts: dict[str, str] = {}
    for node in tree.body:
        target = None
        value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        if (
            isinstance(target, ast.Name)
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
        ):
            consts[target.id] = value.value
    return consts


def _resolve_str(node: ast.expr, consts: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    return None


def _column_name(node: ast.expr, consts: dict[str, str]) -> str | None:
    """The name inside a ``sa.Column("name", ...)`` call."""
    if (
        isinstance(node, ast.Call)
        and getattr(node.func, "attr", None) == "Column"
        and node.args
    ):
        return _resolve_str(node.args[0], consts)
    return None


def added_columns(path: Path) -> set[tuple[str, str]]:
    """Every (table, column) an alembic migration file adds via add_column."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    consts = _module_constants(tree)
    pairs: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        # with op.batch_alter_table("t", ...) as batch_op: batch_op.add_column(sa.Column("c", ...))
        if isinstance(node, ast.With):
            table = None
            for item in node.items:
                call = item.context_expr
                if (
                    isinstance(call, ast.Call)
                    and getattr(call.func, "attr", None) == "batch_alter_table"
                    and call.args
                ):
                    table = _resolve_str(call.args[0], consts)
            if table:
                for sub in ast.walk(node):
                    if (
                        isinstance(sub, ast.Call)
                        and getattr(sub.func, "attr", None) == "add_column"
                        and len(sub.args) == 1
                    ):
                        col = _column_name(sub.args[0], consts)
                        if col:
                            pairs.add((table, col))
        # op.add_column("t", sa.Column("c", ...)) — table may be a module constant.
        elif (
            isinstance(node, ast.Call)
            and getattr(node.func, "attr", None) == "add_column"
            and len(node.args) >= 2
        ):
            table = _resolve_str(node.args[0], consts)
            col = _column_name(node.args[1], consts)
            if table and col:
                pairs.add((table, col))
    return pairs


def _all_migration_columns() -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for f in sorted(_VERSIONS.glob("*.py")):
        pairs |= added_columns(f)
    return pairs


def test_the_sweep_actually_sees_the_migrations():
    """Parser sanity: the sweep must find the known real corpus of add_columns
    (20 distinct pairs as of 2026-07), including the constant-resolved and
    batch forms — a silently-empty sweep would make the drift guard vacuous."""
    pairs = _all_migration_columns()
    assert len(pairs) >= 20, f"only {len(pairs)} add_column pairs found — parser regression?"
    # One of each extraction form:
    assert ("wiki_pages", "latest_text") in pairs  # op.add_column(literal, ...)
    assert ("keywords", "extractor") in pairs  # batch_alter_table form
    assert ("articles", "detected_language") in pairs  # _TABLE/_COLUMN constants


def test_every_add_column_has_a_self_heal_or_a_recorded_exemption():
    missing = sorted(
        (table, col)
        for (table, col) in _all_migration_columns()
        if col not in SELF_HEALED_COLUMNS.get(table, frozenset())
        and (table, col) not in EXEMPT
    )
    assert not missing, (
        "migration add_column(s) with NO boot self-heal (the live DB is never "
        f"alembic-migrated — an existing store would hit 'no such column'): {missing}. "
        "Add an ensure_* self-heal in src/database/maintenance.py (wired into init_db) "
        "and register it in SELF_HEALED_COLUMNS, or record a REASONED exemption here."
    )


def test_exemptions_are_reasoned_not_blanket():
    """Every exemption must name a real (table, column) and carry a substantive
    reason — no blanket or lazy entries."""
    for (table, col), reason in EXEMPT.items():
        assert table and col, "an exemption must name a concrete (table, column)"
        assert isinstance(reason, str) and len(reason.split()) >= 8, (
            f"exemption ({table}, {col}) needs an honest, specific reason, "
            f"not: {reason!r}"
        )
        # An exempted pair must not ALSO be self-healed (stale exemption).
        assert col not in SELF_HEALED_COLUMNS.get(table, frozenset()), (
            f"({table}, {col}) is exempt AND self-healed — remove the stale exemption"
        )
