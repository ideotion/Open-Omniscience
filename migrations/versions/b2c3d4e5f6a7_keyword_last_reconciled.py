"""Keyword counter freshness watermark: keywords.last_reconciled_at.

Data-architecture build Slice 2 (honesty envelope over the maintained counters).
The denormalised ``mention_count`` / ``article_count`` (a2b3c4d5e6f7) are maintained
incrementally at index time and exact by construction, BUT a cascade delete
(``ondelete=CASCADE`` bypasses the ORM maintenance hook) can drift them. This column
records when the bounded background reconcile last recomputed them exactly, so the hot
endpoints can disclose the counters as ``exact`` (fresh watermark) vs ``estimated``
(NULL/stale) via the honesty envelope -- never silently wrong.

Nullable, no default: a freshly-added column is NULL = "never reconciled" = honestly
``estimated`` until the first reconcile stamps it. Adding it does NOT touch the counter
values, so there is no backfill here. Self-healed identically at boot for stores that
don't run alembic (src.database.maintenance.ensure_keyword_counter_columns). Idempotent.

Revision ID: b2c3d4e5f6a7
Revises: a2b3c4d5e6f7
Create Date: 2026-06-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a2b3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    cols = _columns("keywords")
    if not cols:
        return  # no keywords table yet (a brand-new store; create_all builds it)
    if "last_reconciled_at" not in cols:
        with op.batch_alter_table("keywords", schema=None) as batch_op:
            batch_op.add_column(sa.Column("last_reconciled_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    if "last_reconciled_at" in _columns("keywords"):
        with op.batch_alter_table("keywords", schema=None) as batch_op:
            batch_op.drop_column("last_reconciled_at")
