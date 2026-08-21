"""The article's own top keyword: precompute columns + their indexes.

Rulings 23/38/39 (field feedback 2026-08-07). The Articles tab must SORT the
whole corpus by "this article's own top keyword", which a per-row query cannot
do at ~1M articles, and the Feed shows each post's own top three. Both need the
answer already on the row.

Three additive NULLABLE columns, on the detected_language/quarantined pattern:

  * top_keyword_count -- the highest occurrence count any one keyword reached in
    this article (the verifiable evidence number).
  * top_keyword_tied_n -- how many keywords reached it; 1 = unambiguous.
  * top_keyword_id -- a deterministic REPRESENTATIVE of the top set (the lowest
    keyword id among those at the max), never "the winner". Readers render it
    with tied_n so a tie is never presented as a single answer.

NO BACKFILL. An article indexed before these columns existed keeps NULL, which
means "never computed" and is deliberately distinct from "no keywords" -- the
same honest-NULL convention as detected_language and quarantined. index_article
fills it forward on ingest, and a re-index fills an existing corpus, so the work
rides a path the operator already runs rather than a boot pass over every row.

Two indexes, both mirrored in src/database/maintenance.py HOT_INDEXES for
installs that never run `make migrate`:

  * idx_article_top_keyword -- the Articles-tab sort key.
  * ix_mention_article_count -- makes the per-article top-keyword read (Feed
    top-three, the tied set for visible rows) index-only instead of a heap page
    read per mention row, which under SQLCipher is a decrypt per row.

if_not_exists / if_exists on both directions: the boot self-heal may have added
either the columns or the indexes already on an install that booted before it
migrated.

Revision ID: 3f9c17ab42de
Revises: 7b1e4a93c26d
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "3f9c17ab42de"
down_revision = "7b1e4a93c26d"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("top_keyword_id", sa.Integer()),
    ("top_keyword_count", sa.Integer()),
    ("top_keyword_tied_n", sa.Integer()),
)


def _existing_columns() -> set[str]:
    bind = op.get_bind()
    return {c["name"] for c in sa.inspect(bind).get_columns("articles")}


def upgrade() -> None:
    existing = _existing_columns()
    for name, type_ in _COLUMNS:
        if name not in existing:
            # Plain INTEGER, no ForeignKey -- matching the model, which declares none
            # for the same reason (see Article.top_keyword_id): SQLite cannot add a
            # constraint without rebuilding the table, so a declared FK would exist on
            # fresh stores and never on upgraded ones.
            op.add_column("articles", sa.Column(name, type_, nullable=True))

    op.create_index(
        "idx_article_top_keyword",
        "articles",
        ["top_keyword_count", "top_keyword_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_mention_article_count",
        "keyword_mentions",
        ["article_id", "count", "keyword_id"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_mention_article_count", table_name="keyword_mentions", if_exists=True)
    op.drop_index("idx_article_top_keyword", table_name="articles", if_exists=True)
    existing = _existing_columns()
    for name, _type in _COLUMNS:
        if name in existing:
            op.drop_column("articles", name)
