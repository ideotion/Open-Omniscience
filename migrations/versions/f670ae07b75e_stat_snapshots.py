"""Library-counter snapshot history (2026-07-23 field-feedback S2).

Adds ``stat_snapshots`` — an hourly, append-only EAV table (metric, taken_at,
value) recording a handful of cheap Library-tab ``COUNT(*)`` counters (sources,
keywords, Wikipedia pages/revisions tracked, law documents/revisions tracked) so
they can be shown as small evolution graphs instead of a bare live figure. NO
score/rating column, and retention is INFINITE by design — nothing here ever
prunes a row; a bounded read window is a query-time concern only. The unique
constraint on (metric, taken_at) doubles as the "already snapped this hour"
freshness gate, so no separate marker file is needed.

(``create_all`` already creates this on fresh stores; this migration keeps
alembic-managed databases consistent.)

Revision ID: f670ae07b75e
Revises: 04c029205aa8
Create Date: 2026-07-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f670ae07b75e"
down_revision = "04c029205aa8"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade() -> None:
    if _has_table("stat_snapshots"):  # create_all may have already made it
        return
    op.create_table(
        "stat_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("metric", sa.String(length=40), nullable=False),
        sa.Column("taken_at", sa.DateTime(), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("metric", "taken_at", name="uq_stat_snapshot_metric_hour"),
    )
    op.create_index(
        "ix_stat_snapshots_metric_time", "stat_snapshots", ["metric", "taken_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_stat_snapshots_metric_time", table_name="stat_snapshots")
    op.drop_table("stat_snapshots")
