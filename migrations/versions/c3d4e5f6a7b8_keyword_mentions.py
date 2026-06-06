"""keyword mentions + keyword extractor provenance

Revision ID: c3d4e5f6a7b8
Revises: b7c1d2e3f4a5
Create Date: 2026-06-06 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b7c1d2e3f4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("keywords", schema=None) as batch_op:
        batch_op.add_column(sa.Column("extractor", sa.String(length=40), nullable=True))

    op.create_table(
        "keyword_mentions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("keyword_id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("first_offset", sa.Integer(), nullable=True),
        sa.Column("observed_on", sa.Date(), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("extractor", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["keyword_id"], ["keywords.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("keyword_mentions", schema=None) as batch_op:
        batch_op.create_index("ix_mention_keyword_article", ["keyword_id", "article_id"], unique=True)
        batch_op.create_index("ix_mention_keyword_date", ["keyword_id", "observed_on"], unique=False)
        batch_op.create_index("ix_mention_country", ["country"], unique=False)
        batch_op.create_index("ix_mention_article", ["article_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_keyword_mentions_observed_on"), ["observed_on"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("keyword_mentions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_keyword_mentions_observed_on"))
        batch_op.drop_index("ix_mention_article")
        batch_op.drop_index("ix_mention_country")
        batch_op.drop_index("ix_mention_keyword_date")
        batch_op.drop_index("ix_mention_keyword_article")
    op.drop_table("keyword_mentions")
    with op.batch_alter_table("keywords", schema=None) as batch_op:
        batch_op.drop_column("extractor")
