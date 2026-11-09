"""keyword_day_counts, keyword_day_dirty, keyword_day_state -- the per-day keyword counts trending reads (R623, R625)

``trending`` (src/analytics/queries.py) sums ``keyword_mentions.count`` per keyword over its windows; with the DuckDB
rollup off or not built that is a scan of ``ix_mention_date_keyword`` per window, 42 s on the 2026-11-07 field
bundle's Home load. These three tables hold the same sums per day (src/analytics/day_counts.py): the six sums of the
Home poll fall from 4.2 s to 0.10 s plain and from 5.1 s to 0.2 s encrypted on a 12 M-mention store.

Additive: three new tables and two triggers on ``keyword_mentions`` (AFTER DELETE, AFTER UPDATE OF keyword_id,
observed_on, count) that only mark a day as stale; no INSERT trigger (R625: it cost new mentions past the 5 % gate).
The tables are left empty: the build is the visible ``keyword-day-counts`` job the app starts after its start-up
steps, never this migration. ``src.analytics.day_counts.install`` is the shared body; the app runs it at every boot,
so an already-migrated store is a no-op here.

Revision ID: c4e8a2d6f1b9
Revises: a7c3e5f19b20
Create Date: 2026-11-09

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4e8a2d6f1b9"
down_revision: str | None = "a7c3e5f19b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    tables = set(sa.inspect(bind).get_table_names())
    if "keyword_day_counts" not in tables:
        op.create_table(
            "keyword_day_counts",
            sa.Column("observed_on", sa.Date(), nullable=False),
            sa.Column("keyword_id", sa.Integer(), nullable=False),
            sa.Column("mentions", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("observed_on", "keyword_id"),
            sqlite_with_rowid=False,
        )
    if "keyword_day_dirty" not in tables:
        op.create_table(
            "keyword_day_dirty",
            sa.Column("observed_on", sa.Date(), nullable=False),
            sa.PrimaryKeyConstraint("observed_on"),
            sqlite_with_rowid=False,
        )
    if "keyword_day_state" not in tables:
        op.create_table(
            "keyword_day_state",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("complete", sa.Boolean(), nullable=False),
            sa.Column("built_epoch", sa.Integer(), nullable=True),
            sa.Column("watermark", sa.Integer(), nullable=True),
            sa.Column("reuse_floor", sa.Integer(), nullable=True),
            sa.Column("floor_gen", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cursor", sa.Date(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("built_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    from src.analytics.day_counts import install

    install(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    op.execute("DROP TRIGGER IF EXISTS trg_keyword_day_dirty_ad")
    op.execute("DROP TRIGGER IF EXISTS trg_keyword_day_dirty_au")
    op.execute("DROP TABLE IF EXISTS keyword_day_state")
    op.execute("DROP TABLE IF EXISTS keyword_day_dirty")
    op.execute("DROP TABLE IF EXISTS keyword_day_counts")
