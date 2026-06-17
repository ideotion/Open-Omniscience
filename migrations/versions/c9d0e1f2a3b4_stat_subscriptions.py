"""Official-statistics subscriptions: tracked fetches for scheduled vintage refresh.

Ruling 2026-06-17 #12: keep figure fetching user-initiated AND add a scheduled
auto-refresh of vintages. A ``stat_subscriptions`` row records a fetch the user ran
(World Bank indicator+country, or an SDMX dataset+params) so the scheduler can replay
it on a cadence, each replay storing a new VINTAGE (the figure store is vintage-
additive). Freshness-gated (``interval_days``) and airplane-gated (the guarded fetch
refuses under the kill switch). No score column.

(``create_all`` makes this on fresh stores; this keeps alembic-managed databases
consistent — a whole new table, so the boot ``create_all`` adds it to existing stores.)

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-06-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade() -> None:
    if _has_table("stat_subscriptions"):
        return
    op.create_table(
        "stat_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("indicator", sa.String(length=120), nullable=True),
        sa.Column("country", sa.String(length=24), nullable=True),
        sa.Column("dataset", sa.String(length=120), nullable=True),
        sa.Column("params_json", sa.Text(), nullable=True),
        sa.Column("agency", sa.String(length=40), nullable=True),
        sa.Column("interval_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("last_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("last_status", sa.String(length=200), nullable=True),
        sa.UniqueConstraint("source", "indicator", "country", "dataset", "params_json", "agency",
                            name="uq_stat_subscription"),
    )
    op.create_index("ix_stat_subscriptions_enabled", "stat_subscriptions", ["enabled"])


def downgrade() -> None:
    op.drop_index("ix_stat_subscriptions_enabled", table_name="stat_subscriptions")
    op.drop_table("stat_subscriptions")
