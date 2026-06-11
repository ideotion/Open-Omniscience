"""merge provenance: merge_batches + merged_rows

The DB-reliability batch (docs/design/DB_RELIABILITY_02_DESIGN.md §3.3): rows
arriving via backup merge stay traceable to their import batch, so merged
material is never laundered into first-party evidence. A mapping table instead
of an origin column on every domain table -- no churn on existing schemas.

Revision ID: d1e2f3a4b5c6
Revises: a3b4c5d6e7f8
Create Date: 2026-06-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1e2f3a4b5c6"
down_revision: str | None = "a3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "merge_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("imported_at", sa.DateTime(), nullable=True),
        sa.Column("artifact_kind", sa.String(length=20), nullable=False),
        sa.Column("origin_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("app_version", sa.String(length=20), nullable=True),
        sa.Column("alembic_rev", sa.String(length=32), nullable=True),
        sa.Column("manifest_json", sa.Text(), nullable=True),
        sa.Column("counts_json", sa.Text(), nullable=True),
        sa.Column("report_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("merge_batches", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_merge_batches_imported_at"), ["imported_at"], unique=False
        )

    op.create_table(
        "merged_rows",
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("table_name", sa.String(length=64), nullable=False),
        sa.Column("row_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["merge_batches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("batch_id", "table_name", "row_id"),
    )
    with op.batch_alter_table("merged_rows", schema=None) as batch_op:
        batch_op.create_index("ix_merged_rows_lookup", ["table_name", "row_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("merged_rows", schema=None) as batch_op:
        batch_op.drop_index("ix_merged_rows_lookup")
    op.drop_table("merged_rows")
    with op.batch_alter_table("merge_batches", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_merge_batches_imported_at"))
    op.drop_table("merge_batches")
