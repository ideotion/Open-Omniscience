"""articles.fetched_host -- where the stored page was actually fetched from, after its redirects (queue item 61)

A feed item's link is followed wherever it redirects (feeds stay unscoped, R635), and the article is credited to the
source. This column is what says the page came from another site: the host of the address the fetch ended on, as
urllib.parse reads it (lower-cased, no login, no port). Nullable, additive, NO backfill: an article stored before it
keeps NULL, "not recorded", since its redirects were never kept. Self-healed identically at boot
(src.database.maintenance.ensure_article_fetched_host_column). Idempotent.

Revision ID: f61a2b3c4d5e
Revises: c4e8a2d6f1b9
Create Date: 2026-11-09

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f61a2b3c4d5e"
down_revision: str | None = "c4e8a2d6f1b9"
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
    if "fetched_host" not in cols:
        op.add_column("articles", sa.Column("fetched_host", sa.String(length=255), nullable=True))


def downgrade() -> None:
    # A plain ALTER TABLE ... DROP COLUMN (SQLite 3.35+), never batch_alter_table: a batch rebuilds the table, and the
    # rebuilt articles table has none of its triggers (the full-text and title-search sync triggers among them).
    if "fetched_host" in _columns("articles"):
        op.drop_column("articles", "fetched_host")
