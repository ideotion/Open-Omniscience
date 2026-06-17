"""keyword_tags: per-keyword type/topic tags (Item AC, slice 1)

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-06-17 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3f4a5b6c7d8"
down_revision: str | None = "d2e3f4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "keyword_tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("keyword_id", sa.Integer(), nullable=False),
        sa.Column("axis", sa.String(length=16), nullable=False),  # "type" | "topic"
        sa.Column("tag", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),  # "baseline" | "user"
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["keyword_id"], ["keywords.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("keyword_id", "axis", "tag", "source", name="uq_keyword_tag"),
    )
    with op.batch_alter_table("keyword_tags", schema=None) as batch_op:
        batch_op.create_index("ix_keyword_tags_keyword_id", ["keyword_id"], unique=False)
        batch_op.create_index("ix_keyword_tags_axis_tag", ["axis", "tag"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("keyword_tags", schema=None) as batch_op:
        batch_op.drop_index("ix_keyword_tags_axis_tag")
        batch_op.drop_index("ix_keyword_tags_keyword_id")
    op.drop_table("keyword_tags")
