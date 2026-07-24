"""AI change-summary layer for law revisions (2026-07-24 field-feedback A3).

Adds ``law_revision_summaries`` -- a LINKED layer over ``law_revisions`` (mirroring
``article_analyses``'s exact provenance shape: model + prompt_version + the verbatim
prompt_text used), holding an AI-generated plain-language summary of what changed in
one legal-document revision. NEVER the trusted diff/revision record itself; the
corpus keyword-indexing pass never reads this table. Rendered "AI-derived -
unreliable" (the established third class); append-only (a revision may be
re-summarized later with a better prompt, never overwritten in place).

(``create_all`` already creates this on fresh stores; this migration keeps
alembic-managed databases consistent.)

Revision ID: 286c5087fb13
Revises: 95120f685050
Create Date: 2026-07-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "286c5087fb13"
down_revision = "95120f685050"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade() -> None:
    if _has_table("law_revision_summaries"):  # create_all may have already made it
        return
    op.create_table(
        "law_revision_summaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("revision_id", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=50), nullable=True),
        sa.Column("prompt_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["revision_id"], ["law_revisions.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_law_revision_summaries_revision_id", "law_revision_summaries", ["revision_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_law_revision_summaries_revision_id", table_name="law_revision_summaries")
    op.drop_table("law_revision_summaries")
