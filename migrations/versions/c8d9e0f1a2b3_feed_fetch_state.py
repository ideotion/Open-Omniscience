"""Per-feed conditional-GET validators (ETag / Last-Modified).

Field log 2026-06-13: at 1-minute collection intervals ~93% of RSS/Atom feed
items were duplicates — the feeds had not changed, yet each was re-downloaded
and re-parsed. The new ``feed_fetch_state`` table stores the HTTP validators per
source feed so an unchanged feed is answered with a cheap ``304 Not Modified``
and skipped. (create_all already materialises this table on existing databases
at boot; this migration keeps alembic-managed stores consistent.)

Revision ID: c8d9e0f1a2b3
Revises: b6c7d8e9f0a1
Create Date: 2026-06-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c8d9e0f1a2b3"
down_revision = "b6c7d8e9f0a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feed_fetch_state",
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("etag", sa.String(length=512), nullable=True),
        sa.Column("last_modified", sa.String(length=128), nullable=True),
        sa.Column("last_status", sa.Integer(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("source_id"),
    )


def downgrade() -> None:
    op.drop_table("feed_fetch_state")
