"""article_index_stamps -- which engine, on which inputs, produced an article's rows (R24).

One new table, one row per CERTIFIED article, no backfill: every existing article has
no row, which means "not certified by any engine this store can name" -- exactly true
of an article indexed before the stamp existed, and the SAFE reading, because a restore
carries only stamped rows. An unstamped article is re-extracted exactly as it was
before this table existed.

WHY. R24 (2026-09-22) rules that a same-engine backup carries its derived rows instead
of re-extracting them. Sameness is a property of each ARTICLE's rows, not of the backup,
and it is only honest together with the INPUTS the rows were computed from -- a wiki
body replaced after it was indexed, or a country adopted by a later merge, leaves rows a
re-index would not reproduce. See ``src/analytics/engine_identity.py``.

A SIDE TABLE rather than a column on ``articles``, because a column appended there sits
after ``content`` and SQLite reaches it only through the article's overflow pages -- a
full read of the corpus to learn one short string per article. See the model docstring.

GUARDED, on the head migration's pattern: the boot path's ``create_all`` builds the
table on a store that lacks it, while the restore path runs this chain straight at a
staged copy. Either may reach it first.

Revision ID: c7015865aba2
Revises: ea0be5f53d2f
Create Date: 2026-09-24

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "c7015865aba2"
down_revision: str | None = "ea0be5f53d2f"
branch_labels: str | None = None
depends_on: str | None = None

_TABLE = "article_index_stamps"


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
