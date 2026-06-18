"""AI-derived keyword table (ai_keyword) in the MAIN database.

Maintainer ruling 2026-06-18 (REVERSES the earlier separate-AI-database design): AI
analytics live in their OWN tables in the main corpus DB — for seamless UI integration
and fast corpus-wide selection (a real indexed JOIN on ``article_id``). The integrity
guarantee is preserved by construction: own table, no score column, model provenance,
and an invariant test that the trusted rule-based keyword index never reads it.

``create_all`` makes this on fresh stores; this keeps alembic-managed databases
consistent. It is a whole NEW table, so the boot ``create_all`` adds it to existing
stores too.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-06-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d0e1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade() -> None:
    if _has_table("ai_keyword"):
        return
    op.create_table(
        "ai_keyword",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "article_id",
            sa.Integer(),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("term", sa.String(length=300), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="keyword"),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_ai_keyword_article_kind", "ai_keyword", ["article_id", "kind"])
    op.create_index("ix_ai_keyword_term", "ai_keyword", ["term"])


def downgrade() -> None:
    op.drop_index("ix_ai_keyword_term", table_name="ai_keyword")
    op.drop_index("ix_ai_keyword_article_kind", table_name="ai_keyword")
    op.drop_table("ai_keyword")
