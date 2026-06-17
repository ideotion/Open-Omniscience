"""Convergence watch engine tables: watches + watch_matches.

Ruling 2026-06-17 #3: the convergence WATCH engine, ON by default. A ``watch`` is a
saved local condition (an FTS query + a threshold + a recent window) the engine
re-evaluates after each scrape pass; when the corpus gains enough NEW matching
articles it FIRES, recording a ``watch_matches`` history row and surfacing a "watch"
Lead card. Local-only, no notifications/network/telemetry, no score column.

(``create_all`` makes these on fresh stores; this keeps alembic-managed databases
consistent. Both are whole NEW tables, so the boot ``create_all`` adds them to
existing stores too.)

Revision ID: b8c9d0e1f2a3
Revises: 3138d0b2be46
Create Date: 2026-06-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b8c9d0e1f2a3"
down_revision = "3138d0b2be46"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade() -> None:
    if not _has_table("watches"):
        op.create_table(
            "watches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("query", sa.Text(), nullable=False),
            sa.Column("threshold", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("window_days", sa.Integer(), nullable=False, server_default="7"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("last_evaluated_at", sa.DateTime(), nullable=True),
            sa.Column("last_matched_at", sa.DateTime(), nullable=True),
            sa.Column("last_seen_ids", sa.Text(), nullable=True),
        )
        op.create_index("ix_watches_enabled", "watches", ["enabled"])
    if not _has_table("watch_matches"):
        op.create_table(
            "watch_matches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "watch_id", sa.Integer(),
                sa.ForeignKey("watches.id", ondelete="CASCADE"), nullable=False,
            ),
            sa.Column("matched_at", sa.DateTime(), nullable=True),
            sa.Column("n_articles", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("new_articles", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("article_ids", sa.Text(), nullable=True),
        )
        op.create_index("ix_watch_matches_watch", "watch_matches", ["watch_id", "matched_at"])


def downgrade() -> None:
    op.drop_index("ix_watch_matches_watch", table_name="watch_matches")
    op.drop_table("watch_matches")
    op.drop_index("ix_watches_enabled", table_name="watches")
    op.drop_table("watches")
