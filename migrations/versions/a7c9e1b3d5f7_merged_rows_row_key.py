"""merged_rows.row_key -- the natural key of a text-keyed row a restore added (R71 b)

Places (``id``) and Wikidata items (``qid``) have no integer key, so ``merged_rows.row_id`` holds
their SQLite ``rowid``, which VACUUM may renumber. ``row_key`` records the key itself, and the
provenance lookup for those two tables reads it. Nullable and partial-indexed: every other table
leaves it NULL, so an existing merged_rows of millions of rows costs nothing.

GUARDED like the head migrations: the boot path's ``create_all`` may have built the column first
on a fresh database (an existing table is never altered by it).

Revision ID: a7c9e1b3d5f7
Revises: e5f7a9b1c3d5
Create Date: 2026-09-30

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "a7c9e1b3d5f7"
down_revision: str | None = "e5f7a9b1c3d5"
branch_labels: str | None = None
depends_on: str | None = None


def _columns() -> set[str]:
    insp = sa.inspect(op.get_bind())
    if "merged_rows" not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns("merged_rows")}


def upgrade() -> None:
    cols = _columns()
    if not cols:
        return
    if "row_key" not in cols:
        op.add_column("merged_rows", sa.Column("row_key", sa.String(length=64), nullable=True))
    existing = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("merged_rows")}
    if "ix_merged_rows_key" not in existing:
        op.create_index(
            "ix_merged_rows_key", "merged_rows", ["table_name", "row_key"],
            sqlite_where=sa.text("row_key IS NOT NULL"),
        )


def downgrade() -> None:
    cols = _columns()
    if not cols:
        return
    existing = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("merged_rows")}
    if "ix_merged_rows_key" in existing:
        op.drop_index("ix_merged_rows_key", table_name="merged_rows")
    if "row_key" in cols:
        with op.batch_alter_table("merged_rows") as batch:
            batch.drop_column("row_key")
