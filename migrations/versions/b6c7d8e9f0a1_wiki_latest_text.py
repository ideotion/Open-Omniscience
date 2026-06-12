"""Wiki pages carry the LATEST full text (the living-source default view).

Maintainer-ruled 2026-06-12: a Wikipedia article is shown as its NEWEST
version by default, with the tracked change history beneath — so the page
row stores the latest fetched text alongside the immutable baseline, plus
the revid that text corresponds to (honest version anchoring).

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-06-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b6c7d8e9f0a1"
down_revision = "a5b6c7d8e9f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("wiki_pages", sa.Column("latest_text", sa.LargeBinary(), nullable=True))
    op.add_column("wiki_pages", sa.Column("latest_text_revid", sa.Integer(), nullable=True))
    # Per-revision FULL TEXT (maintainer-agreed storage ruling): exact local
    # version materialization; compressed; nullable (older rows stay summary-only).
    op.add_column("wiki_revisions", sa.Column("full_text", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("wiki_revisions", "full_text")
    op.drop_column("wiki_pages", "latest_text_revid")
    op.drop_column("wiki_pages", "latest_text")
