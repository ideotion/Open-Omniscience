"""Covering index for corpus-wide keyword aggregations (performance batch).

The diagnostics export and the insights rankings aggregate
SUM(count) / COUNT(DISTINCT article_id) / MIN-MAX(observed_on) GROUP BY
keyword_id over the whole keyword_mentions table. Without count/observed_on
in an index, every mention row costs a table b-tree page read — a decrypt
each, under SQLCipher. This index makes those scans index-only.

if_not_exists on both directions: init_db()'s boot self-heal
(maintenance.ensure_hot_indexes) may have created it already on installs
that boot before they migrate.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-06-12
"""

from __future__ import annotations

from alembic import op

revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_mention_covering",
        "keyword_mentions",
        ["keyword_id", "article_id", "count", "observed_on"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_mention_covering", table_name="keyword_mentions", if_exists=True)
