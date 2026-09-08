"""index articles.keyword_indexed_at -- backfill_corpus's PRH-01 sort key

backfill_corpus (src/analytics/store.py) orders its whole candidate queue by
`keyword_indexed_at ASC NULLS FIRST, id ASC` on EVERY call -- the PRH-01
livelock fix, so an article the pass has never attempted always sorts ahead
of one it has already examined. The column carried no index, so that sort
fell back to a full table scan plus a temp B-tree, worst exactly when the
un-indexed backlog is large -- the scenario the PRH-01 ordering exists to
handle, and the routine path behind Insights' silent auto-index top-up
(UI invariant #21), not a rare maintenance run.

SINGLE-COLUMN, not a compound (keyword_indexed_at, id) index: `id` is a plain
`Integer, primary_key=True` with no composite key, so SQLite treats it as a
rowid alias, and every index on a rowid table already carries the rowid as an
implicit trailing key breaking ties -- an index on `keyword_indexed_at` alone
already orders the (overwhelmingly NULL, "never attempted") ties by rowid
ascending, i.e. exactly `id ASC`, for free.

EXPLAIN QUERY PLAN, measured against a synthetic 50,000-article backlog (all
NULL keyword_indexed_at, zero keyword_mentions -- the worst case this query
exists for), same LIMIT-200 candidate page both times:

  before  SCAN articles
          USE TEMP B-TREE FOR ORDER BY
          (11.1 ms)
  after   SCAN articles USING COVERING INDEX idx_article_keyword_indexed_at
          (no temp B-tree; 0.2 ms)

IF NOT EXISTS on both directions: this index is also mirrored into the boot
self-heal (src/database/maintenance.py HOT_INDEXES, guarded by
_INDEX_REQUIRES since the column itself is additive), so a store that ran a
newer app before this migration was stamped may already have built it --
same precedent as idx_article_link_dedup (migration d4e9c1a7b036) and the
other self-heal-mirrored indexes in this table.

ROLLOUT: purely additive -- CREATE INDEX on an existing nullable column
changes no query results, only cost. The one-time build is a single-column
B-tree over `articles.id`, comparable in shape to the sibling
idx_article_created_at/idx_article_language indexes this table has always
carried, and the app's own hot-index self-heal already builds equivalents of
that size at boot for existing installs, so no separate maintenance-window
note is expected. On a very large encrypted store the build still costs one
read pass over `articles.id` and `keyword_indexed_at`; the migration is not
a row rewrite (SQLite ADD-COLUMN semantics do not apply here, this is a plain
CREATE INDEX) so it should stay proportionate to that read.

Revision ID: 1f504b87844f
Revises: b5684999c1e1
Create Date: 2026-09-08

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "1f504b87844f"
down_revision: str | None = "b5684999c1e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # IF NOT EXISTS: the boot self-heal (HOT_INDEXES) may have built it already on a
    # store that ran a newer app before its migration was stamped.
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_article_keyword_indexed_at"
            " ON articles (keyword_indexed_at)"
        )
    )


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS idx_article_keyword_indexed_at"))
