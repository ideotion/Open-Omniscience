"""screening_pending -- imported articles the junk screening has not reached yet (R827 R10, R830; row 408 PR 3).

One new table, no backfill: an existing corpus has no pending article. A restore writes a row per article it adds, before the
swap; a background worker judges each one and removes its row. See ``ScreeningPending`` in ``src/database/models.py``.

GUARDED like the other steps: the boot path's ``create_all`` and the restore path's chain may either reach the table first.

Revision ID: a7c2e9d4b1f3
Revises: e4b7c1d9a2f6
Create Date: 2026-11-24

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "a7c2e9d4b1f3"
down_revision: str | None = "e4b7c1d9a2f6"
branch_labels: str | None = None
depends_on: str | None = None

_TABLE = "screening_pending"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "articles" not in tables or _TABLE in tables:
        return
    op.create_table(
        _TABLE,
        sa.Column(
            "article_id",
            sa.Integer(),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("queued_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    if _TABLE in _tables():
        op.drop_table(_TABLE)
