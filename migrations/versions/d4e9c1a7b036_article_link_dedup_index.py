"""covering index for the restore-merge link dedup

The link-graph step asks "does this article already have this url at this
position?" once per INCOMING link row. Field logs 2026-07-31, report #15:
4,163,474 incoming link rows -- every one a duplicate -- and the step cost
2483 s, which is 87% of that import's whole 2857 s merge.

EXPLAIN QUERY PLAN, measured both ways:

  before  SEARCH t USING INDEX idx_article_link_article_id (article_id=?)
  after   SEARCH t USING COVERING INDEX idx_article_link_dedup
                                        (article_id=? AND url=?)

The old plan seeks by article_id and then READS THE ROW to compare url and
position -- two String(1000) columns, so under SQLCipher each of those is a page
decrypt. The new plan answers from the index and never touches the table.

Revision ID: d4e9c1a7b036
Revises: b7d41f9a2c83
Create Date: 2026-07-31 05:10:00.000000
"""
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "d4e9c1a7b036"
down_revision: str | None = "b7d41f9a2c83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # IF NOT EXISTS: the boot self-heal (HOT_INDEXES) may have built it already on
    # a store that ran a newer app before its migration was stamped.
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_article_link_dedup"
            " ON article_links (article_id, url, position)"
        )
    )


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS idx_article_link_dedup"))
