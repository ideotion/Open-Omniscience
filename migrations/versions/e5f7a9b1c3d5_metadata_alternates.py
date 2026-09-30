"""metadata_alternates -- the other value a restore brought, kept beside the local one (R61)

The maintainer's rule (2026-09-29, item 12): deduced metadata is brought over into backups with
its provenance; on a contradiction the imported value never prevails over the local one, both
are kept and reachable, and the operator may discard afterwards. This is the table that keeps
the imported value; the deduced tables themselves are never written by the capture.

GUARDED like the head migrations: the boot path's ``create_all`` may have built it first.

Revision ID: e5f7a9b1c3d5
Revises: d4e6f8a0b2c4
Create Date: 2026-09-30

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "e5f7a9b1c3d5"
down_revision: str | None = "d4e6f8a0b2c4"
branch_labels: str | None = None
depends_on: str | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "metadata_alternates" in tables or "merge_batches" not in tables:
        return
    op.create_table(
        "metadata_alternates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("table_name", sa.String(length=64), nullable=False),
        sa.Column("identity", sa.Text(), nullable=False),
        sa.Column("local_row_id", sa.Integer(), nullable=True),
        sa.Column("fields", sa.Text(), nullable=False),
        sa.Column("provenance", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["merge_batches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_metadata_alternates_batch_id", "metadata_alternates", ["batch_id"])
    op.create_index(
        "ix_metadata_alternates_item", "metadata_alternates", ["table_name", "identity"]
    )


def downgrade() -> None:
    if "metadata_alternates" in _tables():
        op.drop_index("ix_metadata_alternates_item", table_name="metadata_alternates")
        op.drop_index("ix_metadata_alternates_batch_id", table_name="metadata_alternates")
        op.drop_table("metadata_alternates")
