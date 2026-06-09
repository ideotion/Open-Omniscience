"""drop the useless B-tree index on articles.content (finding PERF-02)

A B-tree index over the full article body was never used by any query -- full
text search goes through the FTS5 virtual table -- yet it cost ~224 MB on a
50k-article DB (63% of the file) and slowed every insert. Drop it. FTS5 search
is unaffected. Re-running create_all on a fresh DB no longer creates it.

Revision ID: f1a2b3c4d5e6
Revises: b1c2d3e4f5a6
Create Date: 2026-06-09 00:00:00.000000
"""
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # IF EXISTS: older DBs have it; a fresh create_all (post model change) does not.
    op.execute(text("DROP INDEX IF EXISTS idx_article_content"))


def downgrade() -> None:
    op.execute(text("CREATE INDEX IF NOT EXISTS idx_article_content ON articles (content)"))
