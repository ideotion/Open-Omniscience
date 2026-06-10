"""source candidates -- transparent offline discovery staging (RM-19, WP5)

Revision ID: a9b8c7d6e5f4
Revises: f1a2b3c4d5e6
Create Date: 2026-06-10 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9b8c7d6e5f4"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("suggested_name", sa.String(length=200), nullable=True),
        sa.Column("channel", sa.String(length=30), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("first_seen", sa.DateTime(), nullable=True),
        sa.Column("last_seen", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("domain"),
    )
    with op.batch_alter_table("source_candidates", schema=None) as batch_op:
        batch_op.create_index("idx_source_candidate_status", ["status"], unique=False)
        batch_op.create_index("idx_source_candidate_channel", ["channel"], unique=False)


def downgrade() -> None:
    op.drop_table("source_candidates")
