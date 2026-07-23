"""Covering index for the per-source-country map-coverage aggregation.

/api/insights/map-coverage (queries.source_country_counts) runs
SELECT sources.country, count(articles.id), avg(articles.sentiment_score),
count(articles.sentiment_score) JOIN sources GROUP BY sources.country. EXPLAIN
QUERY PLAN confirmed the existing idx_article_source_id is only a plain SEARCH
(not COVERING) for this query — SQLite finds matching rows by source_id but still
fetches the full table row to read sentiment_score, dragging every ~35 KB article
row through the SQLCipher codec (the same column-order perf trap ix_article_observed
/ ix_mention_covering already fixed elsewhere). Measured 447 ms -> 38 ms on a
300k-article synthetic PLAINTEXT store.

if_not_exists on both directions: init_db()'s boot self-heal
(maintenance.ensure_hot_indexes) may have created it already on installs that
boot before they migrate.

Revision ID: 04c029205aa8
Revises: 8249f1450472
Create Date: 2026-07-23
"""

from __future__ import annotations

from alembic import op

revision = "04c029205aa8"
down_revision = "8249f1450472"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "idx_article_source_sentiment",
        "articles",
        ["source_id", "sentiment_score"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("idx_article_source_sentiment", table_name="articles", if_exists=True)
