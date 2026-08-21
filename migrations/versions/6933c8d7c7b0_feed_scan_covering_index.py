"""A covering index for the Feed's admissibility scan.

Rulings 8-13 (field feedback 2026-08-07). The Feed's shuffled order is an
expression over the article id -- a seeded permutation -- so no index can
provide that order, and every page walks the whole admissible set. That walk is
unavoidable; whether it reads article ROWS is not.

The filter is exactly two things (the article is not quarantined, and its source
has been qualified, which is reached through source_id) and the order key is
computed from the id. Putting those three columns in one index lets SQLite
answer the scan index-only, without touching a single article row.

Measured on a synthetic 200,000-article corpus, plaintext: 314 ms -> 35 ms per
page. On the encrypted store this matters more than the ratio suggests, because
there a skipped row read is also a skipped SQLCipher decrypt.

Index-only and additive: no column is added, no data is written, no existing
query changes shape. if_not_exists on both directions because the boot self-heal
(src/database/maintenance.py HOT_INDEXES) creates the same index on installs
that never run `make migrate`, so either half may already have run.

Revision ID: 6933c8d7c7b0
Revises: 3f9c17ab42de
Create Date: 2026-08-20
"""

from __future__ import annotations

from alembic import op

revision = "6933c8d7c7b0"
down_revision = "3f9c17ab42de"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "idx_article_feed_scan",
        "articles",
        ["quarantined", "source_id", "id"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("idx_article_feed_scan", table_name="articles", if_exists=True)
