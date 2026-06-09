"""article mentioned dates (extracted, human-confirmable date tags)

Revision ID: b1c2d3e4f5a6
Revises: a7b8c9d0e1f2
Create Date: 2026-06-09 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "article_mentioned_dates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("mentioned_on", sa.Date(), nullable=False),
        sa.Column("precision", sa.String(length=10), nullable=False),
        sa.Column("snippet", sa.String(length=300), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("extractor", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("article_id", "mentioned_on", "precision", name="uq_amd_article_date"),
    )
    with op.batch_alter_table("article_mentioned_dates", schema=None) as batch_op:
        batch_op.create_index("ix_amd_article_id", ["article_id"], unique=False)
        batch_op.create_index("ix_amd_mentioned_on", ["mentioned_on"], unique=False)
        batch_op.create_index("ix_amd_status", ["status"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("article_mentioned_dates", schema=None) as batch_op:
        batch_op.drop_index("ix_amd_status")
        batch_op.drop_index("ix_amd_mentioned_on")
        batch_op.drop_index("ix_amd_article_id")
    op.drop_table("article_mentioned_dates")
