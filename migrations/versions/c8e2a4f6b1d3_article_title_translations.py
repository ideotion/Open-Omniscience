"""the tentative article-title table (Q513 = b), so ≈ titles are never the article row

Brief S05-08 S2: article titles and one-line summaries translated by the local model,
≈-marked, shown in lists and on hover, opt-in, NEVER stored as the article. They get a
table of their own, keyed (article_id, target_lang, model, prompt_version) -- the
`keyword_translations` vintage shape -- so the article row stays byte-identical.

ROLLOUT: an additive CREATE TABLE, guarded the way `5adfcc0ed33e_keyword_translations`
is, because `Base.metadata.create_all` at boot routinely creates the table before the
stamp advances.

Revision ID: c8e2a4f6b1d3
Revises: b3d7f1a9c5e2
Create Date: 2026-09-28

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8e2a4f6b1d3"
down_revision: str | None = "b3d7f1a9c5e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    return table in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    if _has_table("article_title_translations"):
        return
    op.create_table(
        "article_title_translations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("source_lang", sa.String(length=16), nullable=False),
        sa.Column("target_lang", sa.String(length=16), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("prompt_version", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "article_id", "target_lang", "model", "prompt_version",
            name="uq_article_title_translation",
        ),
    )
    op.create_index(
        "ix_article_title_translations_lookup",
        "article_title_translations",
        ["target_lang", "article_id"],
    )


def downgrade() -> None:
    if _has_table("article_title_translations"):
        op.drop_index(
            "ix_article_title_translations_lookup", table_name="article_title_translations"
        )
        op.drop_table("article_title_translations")
