"""keyword super-groups (groups of families)

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-09 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "keyword_supergroups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("color", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "keyword_supergroup_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("supergroup_id", sa.Integer(), nullable=False),
        sa.Column("normalized_term", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["supergroup_id"], ["keyword_supergroups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("keyword_supergroup_members", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_keyword_supergroup_members_normalized_term"),
            ["normalized_term"], unique=False)
        batch_op.create_index("ix_kwsg_member_unique", ["supergroup_id", "normalized_term"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("keyword_supergroup_members", schema=None) as batch_op:
        batch_op.drop_index("ix_kwsg_member_unique")
        batch_op.drop_index(batch_op.f("ix_keyword_supergroup_members_normalized_term"))
    op.drop_table("keyword_supergroup_members")
    op.drop_table("keyword_supergroups")
