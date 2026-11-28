"""articles.feed_entry_published_at -- the feed entry's own date, for an article whose page gave none (row 457, R847)

The page's metadata is the only source of ``published_at`` (src/ingest/extract.py), and the date the feed gave the item was
dropped: only its link was kept. This column keeps that date, as the FEED's claim, for an article stored without a date of its
own. It is never written into ``published_at``, so no surface shows it unless it reads it and flags it as the feed's date.

Nullable, additive, NO backfill and no rewrite of stored rows: an article stored before it keeps NULL, "not recorded", since
the feed entry that brought it is gone. One ADD COLUMN, so it costs the same on a 2M-article store as on an empty one.
Self-healed identically at boot (src.database.maintenance.ensure_article_feed_entry_date_column). Idempotent.

Revision ID: c2f6a8e4d1b7
Revises: b8d4f2a6c1e9
Create Date: 2026-11-28

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c2f6a8e4d1b7"
down_revision: str | None = "b8d4f2a6c1e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    cols = _columns("articles")
    if not cols:
        return  # no articles table yet (a brand-new store; create_all builds it)
    if "feed_entry_published_at" not in cols:
        op.add_column("articles", sa.Column("feed_entry_published_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    # A plain ALTER TABLE ... DROP COLUMN (SQLite 3.35+), never batch_alter_table: a batch rebuilds the table, and the
    # rebuilt articles table has none of its triggers (the full-text and title-search sync triggers among them).
    if "feed_entry_published_at" in _columns("articles"):
        op.drop_column("articles", "feed_entry_published_at")
