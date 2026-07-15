"""Source article-count counter: a maintained per-source article count + freshness watermark.

S6 (2026-07-14): ``GET /api/source_io/sources`` and the reader's per-source count each ran a
live ``COUNT(*)`` per source, scaling with corpus size. Add a maintained ``sources.article_count``
(nullable — NULL = never reconciled, so read surfaces fall back to a live count and are never
wrong) + ``sources.counter_reconciled_at`` (the freshness watermark the honesty envelope reads).
Additive, no backfill (``reconcile_source_counters`` populates it forward; the boot self-heal
``ensure_source_counter_columns`` adds these on an existing DB, this migration keeps
alembic-managed stores consistent).

Revision ID: d2f8a9df7168
Revises: 7d4f2a9c1e6b
Create Date: 2026-07-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d2f8a9df7168"
down_revision = "7d4f2a9c1e6b"
branch_labels = None
depends_on = None

_ADD = (
    ("sources", "article_count", sa.Integer()),
    ("sources", "counter_reconciled_at", sa.DateTime()),
)


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    for table, col, typ in _ADD:
        if not _has_column(table, col):
            op.add_column(table, sa.Column(col, typ, nullable=True))


def downgrade() -> None:
    for table, col, _typ in reversed(_ADD):
        if _has_column(table, col):
            op.drop_column(table, col)
