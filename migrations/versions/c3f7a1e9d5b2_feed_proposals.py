"""feed_proposals -- feed addresses proposed for feed-less sources, awaiting a click (row 463, R852).

A proposal is found without a request of its own (a feed link on a start page the crawl supplement already fetched) and changes nothing until the operator accepts it. Additive: a new table, no row of
any existing table touched, nothing re-extracted (R755).

(``create_all`` already creates this on fresh stores; this migration keeps alembic-managed databases consistent.)

Revision ID: c3f7a1e9d5b2
Revises: b8d4f2a6c1e9
Create Date: 2026-11-28

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3f7a1e9d5b2"
down_revision: str | None = "b8d4f2a6c1e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "feed_proposals"


def _has_table(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _has_table(_TABLE):  # create_all may have made it first
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("found_at", sa.DateTime(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("source_id", "url", name="uq_feed_proposal_source_url"),
    )
    op.create_index("idx_feed_proposal_status", _TABLE, ["status"])


def downgrade() -> None:
    if not _has_table(_TABLE):
        return
    op.drop_index("idx_feed_proposal_status", table_name=_TABLE)
    op.drop_table(_TABLE)
