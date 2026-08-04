"""Covering index for the per-language corpus-growth feed.

snapshots.article_counts_by_language runs a created_at range scan that reads
`language` on every matching row to GROUP BY it. idx_article_created_at alone
finds the rows and then fetches each FULL article row to read one 10-char
column — the SQLCipher column-order perf trap (content sits before language in
the row, so the codec decrypts ~35 KB to reach it), the same one
ix_article_observed and idx_article_source_sentiment already fixed for their
own shapes.

detected_language is carried as a third column only so the unassigned/deduced
tally in the same call stays index-only too; it is never read as a language for
the series (an asserted value and a deduced one are never pooled).

if_not_exists on both directions: init_db()'s boot self-heal
(maintenance.ensure_hot_indexes) may have created it already on installs that
boot before they migrate.

Revision ID: 7b1e4a93c26d
Revises: d4e9c1a7b036
Create Date: 2026-08-04
"""

from __future__ import annotations

from alembic import op

revision = "7b1e4a93c26d"
down_revision = "d4e9c1a7b036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "idx_article_created_lang",
        "articles",
        ["created_at", "language", "detected_language"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("idx_article_created_lang", table_name="articles", if_exists=True)
