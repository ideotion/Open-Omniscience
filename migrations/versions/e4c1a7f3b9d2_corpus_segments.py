"""corpus_segments + corpus_id_counter -- the split corpus's registry and id counter (R826, row 409, stage 1).

Two new tables, no backfill, no row written: an empty registry means the corpus is one file (legacy segment 0), so an
existing corpus keeps working untouched (R826 g) and the change is additive (R755 F2).

GUARDED like ``article_www_stamps``: the boot path's ``create_all`` and the restore path's chain may either reach the
tables first.

Revision ID: e4c1a7f3b9d2
Revises: e4b7c1d9a2f6
Create Date: 2026-11-24

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "e4c1a7f3b9d2"
down_revision: str | None = "e4b7c1d9a2f6"
branch_labels: str | None = None
depends_on: str | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "corpus_segments" not in tables:
        op.create_table(
            "corpus_segments",
            sa.Column("seg_no", sa.Integer(), primary_key=True, autoincrement=False),
            sa.Column("file_name", sa.String(length=32), nullable=True, unique=True),
            sa.Column("state", sa.String(length=16), nullable=False),
            sa.Column("id_lo", sa.Integer(), nullable=False),
            sa.Column("id_hi", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("state_at", sa.DateTime(), nullable=True),
        )
    if "corpus_id_counter" not in tables:
        op.create_table(
            "corpus_id_counter",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
            sa.Column("next_id", sa.Integer(), nullable=False),
        )


def downgrade() -> None:
    tables = _tables()
    for name in ("corpus_id_counter", "corpus_segments"):
        if name in tables:
            op.drop_table(name)
