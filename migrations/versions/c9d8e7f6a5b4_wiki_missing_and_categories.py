"""wiki pages: missing-page flag + Wikipedia's own categories (live test 2026-06-10)

A misspelled watch title used to fail silently (no baseline, no warning).
``missing`` records the wiki's own verdict so the UI can shout; ``wiki_categories``
stores the article's REAL Wikipedia categories (JSON list) for classification —
the maintainer's keyword question: yes, Wikipedia stores them, so we keep them.

Revision ID: c9d8e7f6a5b4
Revises: a9b8c7d6e5f4
Create Date: 2026-06-10 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9d8e7f6a5b4"
down_revision: str | None = "a9b8c7d6e5f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("wiki_pages", schema=None) as batch_op:
        batch_op.add_column(sa.Column("missing", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("wiki_categories", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("wiki_pages", schema=None) as batch_op:
        batch_op.drop_column("wiki_categories")
        batch_op.drop_column("missing")
