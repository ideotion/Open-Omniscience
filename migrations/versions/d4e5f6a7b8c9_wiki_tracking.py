"""wikipedia page + revision tracking

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-06 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wiki_pages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("wiki", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("pageid", sa.Integer(), nullable=True),
        sa.Column("watched", sa.Boolean(), nullable=True),
        sa.Column("category", sa.String(length=255), nullable=True),
        sa.Column("baseline_revid", sa.Integer(), nullable=True),
        sa.Column("baseline_text", sa.LargeBinary(), nullable=True),
        sa.Column("last_revid", sa.Integer(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("wiki_pages", schema=None) as batch_op:
        batch_op.create_index("ix_wikipage_wiki_title", ["wiki", "title"], unique=True)
        batch_op.create_index("ix_wikipage_watched", ["watched"], unique=False)
        batch_op.create_index("ix_wikipage_category", ["category"], unique=False)

    op.create_table(
        "wiki_revisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("page_id", sa.Integer(), nullable=False),
        sa.Column("revid", sa.Integer(), nullable=False),
        sa.Column("parent_revid", sa.Integer(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
        sa.Column("editor", sa.String(length=255), nullable=True),
        sa.Column("editor_anon", sa.Boolean(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("size", sa.Integer(), nullable=True),
        sa.Column("delta_bytes", sa.Integer(), nullable=True),
        sa.Column("tags", sa.String(length=500), nullable=True),
        sa.Column("minor", sa.Boolean(), nullable=True),
        sa.Column("bot", sa.Boolean(), nullable=True),
        sa.Column("diff", sa.LargeBinary(), nullable=True),
        sa.Column("ores_damaging", sa.Float(), nullable=True),
        sa.Column("ores_goodfaith", sa.Float(), nullable=True),
        sa.Column("ores_provenance", sa.String(length=80), nullable=True),
        sa.Column("flagged", sa.Boolean(), nullable=True),
        sa.Column("flag_reasons", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["page_id"], ["wiki_pages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("wiki_revisions", schema=None) as batch_op:
        batch_op.create_index("ix_wikirev_page_revid", ["page_id", "revid"], unique=True)
        batch_op.create_index("ix_wikirev_page_time", ["page_id", "timestamp"], unique=False)
        batch_op.create_index("ix_wikirev_flagged", ["flagged"], unique=False)
        batch_op.create_index(batch_op.f("ix_wiki_revisions_timestamp"), ["timestamp"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("wiki_revisions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_wiki_revisions_timestamp"))
        batch_op.drop_index("ix_wikirev_flagged")
        batch_op.drop_index("ix_wikirev_page_time")
        batch_op.drop_index("ix_wikirev_page_revid")
    op.drop_table("wiki_revisions")
    with op.batch_alter_table("wiki_pages", schema=None) as batch_op:
        batch_op.drop_index("ix_wikipage_category")
        batch_op.drop_index("ix_wikipage_watched")
        batch_op.drop_index("ix_wikipage_wiki_title")
    op.drop_table("wiki_pages")
