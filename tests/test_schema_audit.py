"""The schema-freeze inventory is generated from the code and cannot drift from it (0.8 row B, S08-02 S5).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``scripts/schema_audit.py`` writes ``docs/product/SCHEMA_FREEZE_INVENTORY.md`` from the models, the Alembic scripts and the
source text. These tests hold the committed file to the code (a new column, table, migration or format identifier without a
regenerated file is a red, by line), and run the mutation the brief asks for: a column dropped from the schema reddens the
comparison by its name.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _audit():
    spec = importlib.util.spec_from_file_location("schema_audit", _ROOT / "scripts" / "schema_audit.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_the_committed_inventory_matches_the_code(capsys):
    rc = _audit().main(["--check"])
    out = capsys.readouterr().out
    assert rc == 0, "docs/product/SCHEMA_FREEZE_INVENTORY.md is out of date; run python scripts/schema_audit.py\n" + out


def test_the_inventory_names_every_table_column_and_the_head():
    audit = _audit()
    text = audit.render()
    from src.database.models import Base
    from src.versioned.models import LaneBase

    for md in (Base.metadata, LaneBase.metadata):
        for name, table in md.tables.items():
            assert f"### `{name}`" in text, name
            for col in table.columns:
                assert f"| `{col.name}` |" in text, (name, col.name)
    heads, chain = audit._migrations()
    assert len(heads) == 1, f"the migration chain has {len(heads)} heads: {heads}"
    assert f"Head: `{heads[0]}`" in text
    assert len(chain) == len(list((_ROOT / "migrations" / "versions").glob("*.py"))), "a migration file is outside the chain"
    for want in ("`STREAM_KIND`", "`VOLUME_KIND`", "`BACKUP_SCHEMA`", "`EXPORT_SCHEMA`"):
        assert want in text, want


def test_a_dropped_column_reddens_the_comparison_by_name():
    """Mutation check (S08-02 §4): the same schema with one column removed renders a different inventory, naming it."""
    from types import SimpleNamespace

    from src.database.models import Base

    audit = _audit()
    real = audit._tables(Base.metadata)
    # A view of the schema with articles.title left out: the app's own metadata is never touched.
    mutated = SimpleNamespace(tables={
        name: SimpleNamespace(columns=[c for c in t.columns if not (name == "articles" and c.name == "title")])
        for name, t in Base.metadata.tables.items()
    })
    after = audit._tables(mutated)
    assert after != real
    import difflib

    diff = [d for d in difflib.unified_diff(real, after, lineterm="", n=0) if d[:1] in "+-" and d[:3] not in ("---", "+++")]
    assert len(diff) == 1 and diff[0].startswith("-| `title` |"), diff


def test_a_table_named_through_a_module_constant_is_listed():
    """``CREATE TABLE IF NOT EXISTS {TABLE}`` reads the constant's value; a keyword is never taken for a name."""
    audit = _audit()
    rows = "\n".join(audit._ddl_tables(set()))
    assert "| `event_imports` |" in rows and "| `app_state` |" in rows
    for keyword in ("IF", "AS", "SELECT"):
        assert f"| `{keyword}` |" not in rows, keyword


def test_the_output_is_deterministic():
    audit = _audit()
    assert audit.render() == audit.render()
