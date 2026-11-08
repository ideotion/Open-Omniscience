"""article_www_stamps -- which www engine, on which inputs, produced an article's places and entities (R415).

One new table, one row per CERTIFIED article, no backfill: every existing article has
no row, meaning "not certified by any www engine this store can name", the SAFE reading
(a restore carries only stamped rows). The twin of ``article_index_stamps`` (R24); see
``src/analytics/engine_identity.py`` for what ``engine`` and ``inputs`` hash.

GUARDED like its twin: the boot path's ``create_all`` and the restore path's chain may
either reach the table first.

Revision ID: b3d8f1a6c4e2
Revises: a1c4e7b9d2f6
Create Date: 2026-11-04

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "b3d8f1a6c4e2"
down_revision: str | None = "a1c4e7b9d2f6"
branch_labels: str | None = None
depends_on: str | None = None

_TABLE = "article_www_stamps"


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
        sa.Column("engine", sa.String(length=40), nullable=False),
        sa.Column("inputs", sa.String(length=40), nullable=False),
        sa.Column("stamped_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    if _TABLE in _tables():
        op.drop_table(_TABLE)
