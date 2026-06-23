"""Denormalised source_id on keyword_mentions (flood/bury concentration card #4).

Per-source analytics otherwise hit the keyword_mentions->articles decrypt trap over
millions of rows. Denormalise source_id (like observed_on/country already are),
populated FORWARD at index time -- a re-index fills an existing corpus, NOT a heavy
boot UPDATE join. Additive nullable column + index; self-healed identically at boot
(src.database.maintenance.ensure_keyword_mention_source_column). Idempotent.

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-06-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d6e7f8a9b0c1"
down_revision: str | None = "c5d6e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "keyword_mentions"
_COLUMN = "source_id"
_INDEX = "ix_keyword_mentions_source_id"


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table: str, name: str) -> bool:
    if not _has_table(table):
        return False
    return any(c["name"] == name for c in sa.inspect(op.get_bind()).get_columns(table))


def _has_index(table: str, name: str) -> bool:
    if not _has_table(table):
        return False
    return any(i["name"] == name for i in sa.inspect(op.get_bind()).get_indexes(table))


def upgrade() -> None:
    if _has_table(_TABLE) and not _has_column(_TABLE, _COLUMN):
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.Integer(), nullable=True))
    if _has_table(_TABLE) and not _has_index(_TABLE, _INDEX):
        op.create_index(_INDEX, _TABLE, [_COLUMN])


def downgrade() -> None:
    if _has_index(_TABLE, _INDEX):
        op.drop_index(_INDEX, table_name=_TABLE)
    if _has_column(_TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
