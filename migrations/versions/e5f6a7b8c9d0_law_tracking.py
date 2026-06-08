"""world-law document + revision tracking

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-08 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "law_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("jurisdiction", sa.String(length=8), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("official_url", sa.String(length=1000), nullable=True),
        sa.Column("category", sa.String(length=40), nullable=True),
        sa.Column("consolidated", sa.Boolean(), nullable=True),
        sa.Column("watched", sa.Boolean(), nullable=True),
        sa.Column("baseline_text", sa.LargeBinary(), nullable=True),
        sa.Column("baseline_hash", sa.String(length=64), nullable=True),
        sa.Column("last_hash", sa.String(length=64), nullable=True),
        sa.Column("last_size", sa.Integer(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.Column("last_status", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("law_documents", schema=None) as batch_op:
        batch_op.create_index("ix_lawdoc_jurisdiction_url", ["jurisdiction", "url"], unique=True)
        batch_op.create_index("ix_lawdoc_watched", ["watched"], unique=False)
        batch_op.create_index("ix_lawdoc_category", ["category"], unique=False)

    op.create_table(
        "law_revisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=True),
        sa.Column("delta_bytes", sa.Integer(), nullable=True),
        sa.Column("diff", sa.LargeBinary(), nullable=True),
        sa.Column("flagged", sa.Boolean(), nullable=True),
        sa.Column("flag_reasons", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["law_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("law_revisions", schema=None) as batch_op:
        batch_op.create_index("ix_lawrev_doc_hash", ["document_id", "content_hash"], unique=True)
        batch_op.create_index("ix_lawrev_doc_time", ["document_id", "observed_at"], unique=False)
        batch_op.create_index("ix_lawrev_flagged", ["flagged"], unique=False)
        batch_op.create_index(batch_op.f("ix_law_revisions_observed_at"), ["observed_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("law_revisions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_law_revisions_observed_at"))
        batch_op.drop_index("ix_lawrev_flagged")
        batch_op.drop_index("ix_lawrev_doc_time")
        batch_op.drop_index("ix_lawrev_doc_hash")
    op.drop_table("law_revisions")
    with op.batch_alter_table("law_documents", schema=None) as batch_op:
        batch_op.drop_index("ix_lawdoc_category")
        batch_op.drop_index("ix_lawdoc_watched")
        batch_op.drop_index("ix_lawdoc_jurisdiction_url")
    op.drop_table("law_documents")
